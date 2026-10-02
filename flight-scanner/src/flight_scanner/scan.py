#!/usr/bin/env python3
"""
scan.py -- Odense (DK) <-> Salerno (IT) cheap-trip scanner.

It live-queries Ryanair's public fare feed for every Italian airport reachable
from the airports around Odense, attaches realistic train/bus transfer cost and
time on both ends, and ranks whole round-trips by

    score = total_cost(EUR) + time_value(EUR/h) * total_hours

so you can dial how much an hour of your life is worth.

Examples
--------
# Always the next 30 days (the default), ~1-week trips:
python3 scan.py --pickup-naples

# A tighter window or a one-way search:
python3 scan.py --days 14
python3 scan.py --oneway --days 10

# Show flight numbers, ground service IDs and fare distributions:
python3 scan.py --details
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from . import ground, ryanair
from .live_rail import ProviderUnavailable, build_provider, live_ground_lines

IT_AIRPORTS = set(ground.ITALY_AIRPORT_TO_SALERNO)


@dataclass
class Leg:
    kind: str  # "out" | "back"
    fly_from: str  # IATA flown out of
    fly_to: str  # IATA flown into
    day: str
    fare: float  # EUR, one-way, per adult
    depart: str
    arrive: str
    flight_h: float
    ground_from: str  # description of Odense->airport leg
    ground_to: str  # description of airport->Salerno leg
    cost: float  # fare + both ground legs
    hours: float  # overhead + ground + flight
    flight_no: str = ""  # e.g. FR406, filled in for displayed legs
    service_from: str = ""  # ground identifier: Odense -> departure airport
    service_to: str = ""  # ground identifier: arrival airport -> Salerno
    seg_from: tuple[ground.Segment, ...] = ()  # Odense -> departure airport
    seg_to: tuple[ground.Segment, ...] = ()  # arrival airport -> Salerno

    def label(self) -> str:
        return f"{self.fly_from}->{self.fly_to} {self.day}"


def _hm_to_minutes(text: str) -> int | None:
    try:
        hours, minutes = text.split(":")
        return int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None


def _hhmm_to_hours(depart: str, arrive: str) -> float:
    dep_m = _hm_to_minutes(depart)
    arr_m = _hm_to_minutes(arrive)
    if dep_m is None or arr_m is None:
        return 2.5  # unknown schedule: assume a typical 2.5h hop
    delta = arr_m - dep_m
    if delta < 0:  # crosses midnight
        delta += 24 * 60
    return max(delta, 30) / 60.0


def build_legs(
    kind: str,
    origin: str,
    dest: str,
    fares: list[ryanair.Fare],
    overhead_h: float,
    pickup: bool,
    ground_mode: str = "min",
) -> list[Leg]:
    g_from = ground.odense_to_airport(origin)
    g_to = ground.airport_to_salerno(dest, pickup=pickup)
    if g_from is None or g_to is None:
        return []
    service_from = ground.odense_service(origin)
    service_to = ground.airport_service(dest, pickup=pickup)
    seg_from = ground.odense_segments(origin)
    seg_to = ground.airport_segments(dest, pickup=pickup)
    g_from_cost = g_from.cost_min if ground_mode == "min" else g_from.cost_typ
    g_to_cost = g_to.cost_min if ground_mode == "min" else g_to.cost_typ
    legs: list[Leg] = []
    for f in fares:
        flight_h = _hhmm_to_hours(f.depart_time, f.arrive_time)
        cost = f.price + g_from_cost + g_to_cost
        hours = overhead_h + g_from.hours + flight_h + g_to.hours
        legs.append(
            Leg(
                kind=kind,
                fly_from=f.origin,
                fly_to=f.dest,
                day=f.day,
                fare=round(f.price, 2),
                depart=f.depart_time,
                arrive=f.arrive_time,
                flight_h=round(flight_h, 2),
                ground_from=g_from.mode,
                ground_to=g_to.mode,
                cost=round(cost, 2),
                hours=round(hours, 2),
                flight_no=f.flight_no,
                service_from=service_from,
                service_to=service_to,
                seg_from=seg_from,
                seg_to=seg_to,
            )
        )
    return legs


@dataclass
class ScanResult:
    """Everything one scan produced."""

    out_legs: list[Leg]
    back_legs: list[Leg]
    routes: dict[str, str]


def trip_window(
    days: int, trip_min: int, trip_max: int, today: date | None = None
) -> tuple[date, date, date, date]:
    """Rolling window: depart within ``days``, return ``trip_min``-``trip_max`` later."""
    start = today or date.today()
    return (
        start,
        start + timedelta(days=days),
        start + timedelta(days=trip_min),
        start + timedelta(days=days + trip_max),
    )


def scan(
    origins: list[str],
    out_start: date,
    out_end: date,
    ret_start: date,
    ret_end: date,
    overhead_h: float,
    pickup: bool,
    use_cache: bool,
    ground_mode: str = "min",
    workers: int = 8,
    quiet: bool = False,
) -> ScanResult:
    disc_start = min(out_start, ret_start)
    disc_end = max(out_end, ret_end)

    routes: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    for origin in origins:
        if ground.odense_to_airport(origin) is None:
            continue
        try:
            destinations = ryanair.discover_destinations(
                origin, disc_start, disc_end, use_cache
            )
        except RuntimeError as err:
            if not quiet:
                print(f"  ! {origin}: discovery failed ({err})")
            continue
        it_dests = sorted(d for d in destinations if d in IT_AIRPORTS)
        if not quiet:
            print(
                f"  {origin}: {len(it_dests)} Italian destinations "
                f"[{', '.join(it_dests) if it_dests else '-'}]"
            )
        for dest in it_dests:
            routes[f"{origin}->{dest}"] = destinations[dest]
            pairs.append((origin, dest))

    def fetch(pair: tuple[str, str]) -> tuple[str, str, list, list]:
        origin, dest = pair
        out_fares = ryanair.cheapest_over_window(
            origin, dest, out_start, out_end, use_cache
        )
        back_fares = ryanair.cheapest_over_window(
            dest, origin, ret_start, ret_end, use_cache
        )
        return origin, dest, out_fares, back_fares

    out_legs: list[Leg] = []
    back_legs: list[Leg] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch, pair): pair for pair in pairs}
        for future in as_completed(futures):
            origin, dest = futures[future]
            done += 1
            try:
                _, _, out_fares, back_fares = future.result()
            except Exception as err:  # noqa: BLE001 - keep scanning other routes
                if not quiet:
                    print(f"  ! {origin}->{dest} failed: {err}")
                continue
            out_legs += build_legs(
                "out", origin, dest, out_fares, overhead_h, pickup, ground_mode
            )
            back_legs += build_legs(
                "back", origin, dest, back_fares, overhead_h, pickup, ground_mode
            )
            if not quiet:
                print(
                    f"  [{done}/{len(pairs)}] {origin}->{dest}: "
                    f"{len(out_fares)} out / {len(back_fares)} back days"
                )
    return ScanResult(out_legs, back_legs, routes)


@dataclass
class Trip:
    out: Leg
    back: Leg
    cost: float
    hours: float
    days: int
    score: float


def combine(
    out_legs: list[Leg],
    back_legs: list[Leg],
    time_value: float,
    trip_min: int,
    trip_max: int,
    pool: int = 60,
) -> list[Trip]:
    def score(leg: Leg) -> float:
        return leg.cost + time_value * leg.hours

    out_pool = sorted(out_legs, key=score)[:pool]
    back_pool = sorted(back_legs, key=score)[:pool]

    trips: list[Trip] = []
    for o in out_pool:
        od = date.fromisoformat(o.day)
        for b in back_pool:
            bd = date.fromisoformat(b.day)
            days = (bd - od).days
            if days < trip_min or days > trip_max:
                continue
            cost = o.cost + b.cost
            hours = o.hours + b.hours
            trips.append(
                Trip(
                    out=o,
                    back=b,
                    cost=round(cost, 2),
                    hours=round(hours, 2),
                    days=days,
                    score=round(cost + time_value * hours, 2),
                )
            )
    trips.sort(key=lambda t: t.score)
    return trips


def pareto(trips: list[Trip]) -> list[Trip]:
    """Cheapest trips that are not dominated on both cost and hours."""
    best_by_cost = sorted(trips, key=lambda t: (t.cost, t.hours))
    front: list[Trip] = []
    best_h = math.inf
    for t in best_by_cost:
        if t.hours < best_h:
            front.append(t)
            best_h = t.hours
    return front


def leg_ground_cost(leg: Leg) -> float:
    """The ground-transfer part of a leg's cost (total minus the air fare)."""
    return round(leg.cost - leg.fare, 2)


def trip_air_cost(trip: Trip) -> float:
    """Combined air fares for both legs of a trip."""
    return round(trip.out.fare + trip.back.fare, 2)


def trip_ground_cost(trip: Trip) -> float:
    """Combined ground transfers for both legs of a trip."""
    return round(leg_ground_cost(trip.out) + leg_ground_cost(trip.back), 2)


def trip_cost_line(trip: Trip) -> str:
    """``air EURx + ground EURy`` -- the split that precedes the total."""
    return f"air EUR{trip_air_cost(trip):.0f} + ground EUR{trip_ground_cost(trip):.0f}"


def fmt_trip(t: Trip) -> str:
    o, b = t.out, t.back
    out_id = f"{o.flight_no} " if o.flight_no else ""
    back_id = f"{b.flight_no} " if b.flight_no else ""
    return (
        f"EUR{t.cost:7.2f} ({trip_cost_line(t)}) | {t.hours:6.1f}h | {t.days:2d}d | "
        f"OUT {o.fly_from}->{o.fly_to} {o.day} {o.depart}-{o.arrive} "
        f"({out_id}EUR{o.fare:.0f}) || "
        f"BACK {b.fly_from}->{b.fly_to} {b.day} {b.depart}-{b.arrive} "
        f"({back_id}EUR{b.fare:.0f})"
    )


def leg_services(leg: Leg) -> str:
    """The operator + service/line identifiers for a leg's ground transfers."""
    return " + ".join(p for p in (leg.service_from, leg.service_to) if p)


def leg_summary(leg: Leg) -> str:
    """One leg with a clear air + ground cost split and the flight number."""
    flight = f"Ryanair {leg.flight_no}" if leg.flight_no else "Ryanair"
    return (
        f"{leg.fly_from}->{leg.fly_to} {leg.day} {leg.depart}-{leg.arrive} · "
        f"{flight} · air EUR{leg.fare:.0f} + ground EUR{leg_ground_cost(leg):.0f} "
        f"= EUR{leg.cost:.0f}"
    )


def describe_ground(leg: Leg, indent: str = "       ") -> list[str]:
    """Bookable ground hops: station pair, operator/service, frequency, site."""
    lines: list[str] = []
    for seg in (*leg.seg_from, *leg.seg_to):
        book = f" · {seg.book_at}" if seg.book_at else ""
        lines.append(
            f"{indent}{seg.depart} -> {seg.arrive} · {seg.label()} "
            f"({seg.frequency}, {seg.duration}){book}"
        )
    return lines


def format_trip_detail(trip: Trip) -> str:
    out, back = trip.out, trip.back
    lines = [
        f"EUR{trip.cost:.2f} total = {trip_cost_line(trip)} | "
        f"{trip.hours:.1f}h | {trip.days} days",
        f"  OUT  {leg_summary(out)}",
    ]
    lines.extend(describe_ground(out))
    lines.append(f"  BACK {leg_summary(back)}")
    lines.extend(describe_ground(back))
    return "\n".join(lines)


def enrich_flight_ids(legs: list[Leg], use_cache: bool = True) -> None:
    """Fill in flight numbers for the legs we are about to display."""
    seen: set[tuple[str, str, str]] = set()
    for leg in legs:
        key = (leg.fly_from, leg.fly_to, leg.day)
        if leg.flight_no or key in seen:
            continue
        seen.add(key)
        try:
            fare = ryanair.fare_for_day(*key, use_cache=use_cache)
        except (RuntimeError, ValueError):
            continue
        if fare and fare.flight_no:
            leg.flight_no = fare.flight_no


def write_json(path: str, payload: object) -> None:
    try:
        with open(path, "w") as fh:
            json.dump(payload, fh, indent=2)
    except OSError as err:
        print(f"! could not write {path}: {err}")
        return
    print(f"\nWrote {path}")


def _live_providers(args: argparse.Namespace) -> tuple:
    """Build the Danish and Italian live-rail providers (None if unavailable)."""

    def build(name: str):
        try:
            return build_provider(
                name, rejseplanen_access_id=args.rejseplanen_access_id
            )
        except ProviderUnavailable as err:
            print(f"  ! live rail '{name}' unavailable: {err}")
            return None

    return build(args.rail_danish), build(args.rail_italian)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--days",
        type=int,
        default=30,
        help="rolling window: always look at the next N days (default 30)",
    )
    p.add_argument("--out-start", default=None, help="override window (YYYY-MM-DD)")
    p.add_argument("--out-end", default=None)
    p.add_argument("--ret-start", default=None)
    p.add_argument("--ret-end", default=None)
    p.add_argument("--trip-min", type=int, default=5)
    p.add_argument("--trip-max", type=int, default=9)
    p.add_argument(
        "--details",
        action="store_true",
        help="show flight numbers and the bookable ground hops",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="fetch real train/bus times (DSB for DK, Transitous for IT)",
    )
    p.add_argument(
        "--rail-danish",
        default="rejseplanen",
        help="provider for Danish legs (rejseplanen|transitous)",
    )
    p.add_argument(
        "--rail-italian",
        default="transitous",
        help="provider for Italian legs (transitous|trainline)",
    )
    p.add_argument(
        "--rejseplanen-access-id",
        default="",
        help="free Rejseplanen/DSB accessId (https://labs.rejseplanen.dk/)",
    )
    p.add_argument(
        "--origins",
        default="CPH,AAR,BLL",
        help="comma-separated Danish/nearby departure airports",
    )
    p.add_argument(
        "--time-value",
        type=float,
        default=8.0,
        help="EUR you are willing to pay to save one hour of travel",
    )
    p.add_argument(
        "--overhead",
        type=float,
        default=2.5,
        help="fixed airport overhead hours per flight (check-in, bags)",
    )
    p.add_argument(
        "--ground",
        choices=["min", "typ"],
        default="min",
        help="ground transfer pricing: 'min' = advance/online fare, "
        "'typ' = realistic walk-up fare",
    )
    p.add_argument(
        "--pickup-naples",
        action="store_true",
        help="parents collect you at Naples -> NAP transfer is free",
    )
    p.add_argument("--oneway", action="store_true", help="only scan the outbound")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--json", metavar="FILE", help="write full result set to JSON")
    args = p.parse_args(argv)

    origins = [o.strip().upper() for o in args.origins.split(",") if o.strip()]
    use_cache = not args.no_cache

    if args.out_start and args.ret_start:
        out_start = date.fromisoformat(args.out_start)
        out_end = date.fromisoformat(args.out_end or args.out_start)
        ret_start = date.fromisoformat(args.ret_start)
        ret_end = date.fromisoformat(args.ret_end or args.ret_start)
    else:
        out_start, out_end, ret_start, ret_end = trip_window(
            args.days, args.trip_min, args.trip_max
        )

    print(
        f"Scanning Odense -> Salerno | out {out_start}..{out_end} | "
        f"back {ret_start}..{ret_end} | time value EUR{args.time_value}/h | "
        f"pickup_naples={args.pickup_naples}"
    )
    result = scan(
        origins,
        out_start,
        out_end,
        ret_start,
        ret_end,
        args.overhead,
        args.pickup_naples,
        use_cache,
        args.ground,
    )
    out_legs, back_legs, routes = result.out_legs, result.back_legs, result.routes

    if args.oneway:
        out_legs.sort(key=lambda x: x.cost + args.time_value * x.hours)
        shown_legs = out_legs[: args.top]
        enrich_flight_ids(shown_legs, use_cache)
        print(f"\nBest one-way legs ({len(out_legs)} found):")
        for leg in shown_legs:
            print(f"  EUR{leg.cost:7.2f} | {leg.hours:5.1f}h | {leg_summary(leg)}")
        if args.details:
            print("\nDETAILS — ground hops to book:")
            for leg in shown_legs:
                for line in describe_ground(leg, indent="  "):
                    print(line)
        if args.json:
            write_json(args.json, [asdict(x) for x in out_legs])
        return

    trips = combine(out_legs, back_legs, args.time_value, args.trip_min, args.trip_max)
    print(
        f"\n{len(out_legs)} outbound legs, {len(back_legs)} return legs, "
        f"{len(trips)} valid round-trips after trip length {args.trip_min}-"
        f"{args.trip_max}d filter.\n"
    )

    shown = trips[: args.top]
    front = pareto(trips)[: args.top]
    best_per_pair: dict[tuple[str, str], Trip] = {}
    for t in trips:
        key = (t.out.fly_to, t.back.fly_from)
        if key not in best_per_pair or t.cost < best_per_pair[key].cost:
            best_per_pair[key] = t

    display = shown + front + list(best_per_pair.values())
    enrich_flight_ids([leg for t in display for leg in (t.out, t.back)], use_cache)

    print(f"TOP {args.top} ROUND-TRIPS (best cost/time balance):")
    for t in shown:
        print("  " + fmt_trip(t))

    print("\nPARETO FRONT (cheapest for each achievable travel time):")
    for t in front:
        print("  " + fmt_trip(t))

    print("\nPER-DESTINATION CHEAPEST (showcases the fly-to-hub + train trick):")
    for key, t in sorted(best_per_pair.items(), key=lambda kv: kv[1].cost):
        print(f"  via {key[0]:>3} (back from {key[1]:>3}): {fmt_trip(t)}")

    if args.details:
        print("\nDETAILS — flight numbers and bookable ground hops:")
        danish = italian = None
        if args.live:
            danish, italian = _live_providers(args)
        for t in shown:
            print(format_trip_detail(t))
            if danish is not None or italian is not None:
                for leg in (t.out, t.back):
                    for line in live_ground_lines(
                        leg, danish, italian, pickup=args.pickup_naples
                    ):
                        print(line)
            print()

    if args.json:
        payload = {
            "params": vars(args),
            "routes": routes,
            "trips": [asdict(t) for t in trips],
        }
        write_json(args.json, payload)


if __name__ == "__main__":
    main()
