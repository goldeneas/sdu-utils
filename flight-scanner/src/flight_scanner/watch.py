#!/usr/bin/env python3
"""
watch.py -- periodically scan for good Odense <-> Salerno deals and push an
ntfy notification to your phone when something is genuinely worth booking.

It reuses the live scanner, remembers the best prices it has ever seen, and
only alerts on *changes*:

* **first scan**  -- baseline (unless ``deals.notify_first_run = false``)
* **new best**    -- the cheapest total ever beats the previous best
* **under threshold** -- any trip at or below ``deals.max_total`` (EUR)
* **price drop**  -- a trip you were already alerted about got cheaper

Examples
--------
    # one check, print instead of sending
    python3 -m flight_scanner.watch --config config.toml --dry-run

    # one real check
    python3 -m flight_scanner.watch --config config.toml

    # stay resident, checking every 6 hours
    python3 -m flight_scanner.watch --config config.toml --loop

For phones, run it from a scheduler (systemd user timer or cron) -- see the
README.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import scan
from .config import DealConfig, WatchConfig, default_config_path, load_config
from .live_rail import (
    ProviderUnavailable,
    RailProvider,
    build_provider,
    live_ground_lines,
)
from .notify import (
    Notification,
    build_notifiers,
    send_all,
)
from .state import WatchState, load_state, save_state


@dataclass(slots=True)
class Deal:
    """A trip worth telling the user about, and why."""

    trip: scan.Trip
    reason: str
    previous: float | None = None


def trip_signature(trip: scan.Trip) -> str:
    """Stable identity for a trip shape, independent of price.

    Two scans returning the same flights on the same days share a signature,
    so a price change is detectable while an identical re-run is not.
    """
    out, back = trip.out, trip.back
    return (
        f"{out.fly_from}>{out.fly_to}@{out.day}~"
        f"{back.fly_from}>{back.fly_to}@{back.day}"
    )


def detect_deals(
    trips: list[scan.Trip], state: WatchState, cfg: DealConfig
) -> list[Deal]:
    """Return the alerts this run should send (cheapest first)."""
    if not trips:
        return []
    max_total = cfg.max_total
    improve_by = cfg.improve_by
    max_alerts = cfg.max_alerts
    mode = cfg.mode
    notify_first_run = cfg.notify_first_run

    # A first run with first-run alerts disabled is purely a baseline.
    if state.runs == 0 and not notify_first_run:
        return []

    ordered = sorted(trips, key=lambda t: t.cost)
    alerts: list[Deal] = []
    used: set[str] = set()

    if mode in ("best", "both"):
        best = ordered[0]
        sig = trip_signature(best)
        previous = state.best_total
        if previous is None:
            alerts.append(Deal(best, "first scan", None))
            used.add(sig)
        elif best.cost <= previous - improve_by:
            alerts.append(Deal(best, "new best", previous))
            used.add(sig)

    if mode in ("threshold", "both") and max_total > 0:
        for trip in ordered:
            if trip.cost > max_total or len(alerts) >= max_alerts:
                break
            sig = trip_signature(trip)
            if sig in used:
                continue
            previous = state.deals.get(sig)
            if previous is None:
                alerts.append(Deal(trip, "under threshold", None))
                used.add(sig)
            elif trip.cost <= previous - improve_by:
                alerts.append(Deal(trip, "price drop", previous))
                used.add(sig)

    alerts.sort(key=lambda d: d.trip.cost)
    return alerts[:max_alerts]


def apply_state(state: WatchState, trips: list[scan.Trip], max_total: float) -> None:
    """Fold this run's results into the memory (best total + per-trip bests)."""
    if trips:
        best = min(t.cost for t in trips)
        if state.best_total is None or best < state.best_total:
            state.best_total = round(best, 2)

    for trip in sorted(trips, key=lambda t: t.cost):
        if max_total > 0 and trip.cost > max_total:
            break
        if len(state.deals) >= 500:
            break
        sig = trip_signature(trip)
        previous = state.deals.get(sig)
        if previous is None or trip.cost < previous:
            state.deals[sig] = round(trip.cost, 2)

    state.note_run()


def format_deal_notification(
    deals: list[Deal],
    config: WatchConfig,
    danish: RailProvider | None = None,
    italian: RailProvider | None = None,
) -> Notification:
    """Render one notification covering all of this run's deals."""
    cheapest = min(d.trip.cost for d in deals)
    if len(deals) == 1:
        title = f"Cheap trip to Salerno: EUR{cheapest:.0f}"
    else:
        title = f"{len(deals)} cheap trips to Salerno (from EUR{cheapest:.0f})"

    used_live = False

    def ground_lines(leg: scan.Leg) -> list[str]:
        nonlocal used_live
        live = live_ground_lines(
            leg,
            danish,
            italian,
            tz=config.rail.timezone,
            indent="  ",
            pickup=config.trip.pickup_naples,
        )
        if live:
            used_live = True
            return live
        return scan.describe_ground(leg, indent="  ")

    lines: list[str] = []
    for deal in deals:
        trip = deal.trip
        tag = deal.reason
        if deal.previous is not None and deal.previous > trip.cost:
            tag = f"{deal.reason}, was EUR{deal.previous:.0f}"
        lines.append(
            f"**EUR{trip.cost:.0f}** = {scan.trip_cost_line(trip)} — {tag} · "
            f"{trip.days}d · {trip.hours:.1f}h"
        )
        lines.append(f"- OUT  {scan.leg_summary(trip.out)}")
        lines.extend(ground_lines(trip.out))
        lines.append(f"- BACK {scan.leg_summary(trip.back)}")
        lines.extend(ground_lines(trip.back))
    lines.append("")
    note = (
        "_Live times; re-check before booking._"
        if used_live
        else "_Ground hops are reference services — book them for your date._"
    )
    lines.append(note)
    message = "\n".join(lines)

    return Notification(
        title=title,
        message=message,
        priority=config.notify.priority,
        tags=config.notify.tags,
        click=config.notify.click,
    )


def run_once(
    config: WatchConfig,
    *,
    dry_run: bool = False,
    json_path: Path | None = None,
) -> int:
    """Run a single scan/notify cycle. Returns a process exit code."""
    trip = config.trip
    out_start, out_end, ret_start, ret_end = scan.trip_window(
        trip.days, trip.trip_min, trip.trip_max
    )
    try:
        result = scan.scan(
            list(trip.origins),
            out_start,
            out_end,
            ret_start,
            ret_end,
            trip.overhead,
            trip.pickup_naples,
            use_cache=True,
            ground_mode=trip.ground,
            quiet=True,
        )
    except Exception as err:  # noqa: BLE001 - surfaced to the caller/log
        print(f"scan failed: {err}", file=sys.stderr)
        return 2

    trips = scan.combine(
        result.out_legs, result.back_legs, trip.time_value, trip.trip_min, trip.trip_max
    )

    state = load_state(config.state_file)
    deals = detect_deals(trips, state, config.deals)
    scan.enrich_flight_ids([leg for d in deals for leg in (d.trip.out, d.trip.back)])

    print(
        f"checked {len(trips)} round-trips over {len(result.routes)} routes; "
        f"{len(deals)} new deal(s)"
    )
    results: list[str] = []
    if deals:
        danish = italian = None
        if config.rail.live:
            with contextlib.suppress(ProviderUnavailable):
                danish = build_provider(
                    config.rail.danish,
                    rejseplanen_access_id=config.rail.rejseplanen_access_id,
                )
            with contextlib.suppress(ProviderUnavailable):
                italian = build_provider(
                    config.rail.italian,
                    rejseplanen_access_id=config.rail.rejseplanen_access_id,
                )
        note = format_deal_notification(deals, config, danish, italian)
        if dry_run:
            print(f"[{note.title}]")
            print(note.message)
        else:
            notifiers = build_notifiers(config.notify)
            results = send_all(notifiers, note)
            for err in results:
                print(f"! notification error: {err}", file=sys.stderr)
            if not results and notifiers:
                print(f"notified via {', '.join(n.name for n in notifiers)}")
    elif dry_run:
        print("no new deals (baseline/unchanged)")

    apply_state(state, trips, config.deals.max_total)
    save_state(config.state_file, state)

    if json_path is not None:
        scan.write_json(
            str(json_path),
            {
                "trips": [asdict(t) for t in trips],
                "deals": [
                    {
                        "reason": d.reason,
                        "previous": d.previous,
                        "cost": d.trip.cost,
                        "trip": asdict(d.trip),
                    }
                    for d in deals
                ],
            },
        )

    return 1 if results else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="path to config.toml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the alert instead of sending it (no network POST)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="stay resident and check every watch.interval_hours",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=None,
        help="override watch.interval_hours",
    )
    parser.add_argument(
        "--state", type=Path, default=None, help="override the state file path"
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_path",
        help="write this run's trips/deals to JSON",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print scan progress (the default is quiet)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except Exception as err:  # noqa: BLE001 - config errors are user-facing
        print(f"configuration error: {err}", file=sys.stderr)
        return 2

    if args.state is not None:
        config.state_file = args.state.expanduser()
    if args.interval_hours is not None:
        config.interval_hours = max(0.1, args.interval_hours)

    if not args.loop:
        return run_once(config, dry_run=args.dry_run, json_path=args.json_path)

    interval = config.interval_hours * 3600
    print(
        f"watching every {config.interval_hours:g}h "
        f"(state: {config.state_file}); Ctrl-C to stop"
    )
    try:
        while True:
            run_once(config, dry_run=args.dry_run, json_path=args.json_path)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
