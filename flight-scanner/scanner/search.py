"""Orchestrazione: raccolta da Travelpayouts (A/R) e Ryanair (tratte), filtro e unione."""
from __future__ import annotations

import datetime as dt
import os
import time

from .config import Config
from .models import FlightOption, OneWayFare
from .notifier import resolve_ntfy
from .output import render_results, write_results_file
from .ryanair import RyanairClient
from .travelpayouts import ApiError, TravelpayoutsClient


def months_in_window(start: dt.date, end: dt.date) -> list[str]:
    months, d = [], start.replace(day=1)
    while d <= end:
        months.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return months


def filter_offers(
    offers, cfg: Config, start: dt.date, end: dt.date, ignore_price: bool = False
) -> list[FlightOption]:
    """Applica finestra di date, notti minime, scali e soglia di prezzo; deduplica."""
    s = cfg.search
    seen, out = set(), []
    for o in sorted(offers, key=lambda o: o.price):  # a parità di voli resta il più economico
        if not (start <= o.departure_date <= end):  # solo la partenza è vincolata alla finestra
            continue
        if not (s.min_nights <= o.nights <= s.max_nights):
            continue
        if max(o.transfers, o.return_transfers) > s.max_transfers:
            continue
        if o.price > s.max_price and not ignore_price:
            continue
        if o.key in seen:
            continue
        seen.add(o.key)
        out.append(o)
    return out


def pick_top(options: list[FlightOption], n: int, unique: bool) -> list[FlightOption]:
    """Primi `n` per prezzo; con `unique` ogni singolo volo (andata o ritorno) compare una volta sola."""
    if not unique:
        return options[:n]
    used, top = set(), []
    for o in options:
        out_leg = (o.origin, o.destination, o.departure_at)
        back_leg = (o.return_origin, o.return_destination, o.return_at)
        if out_leg in used or back_leg in used:
            continue
        used.update((out_leg, back_leg))
        top.append(o)
        if len(top) == n:
            break
    return top


def top_per_airport(
    options: list[FlightOption], airports: list[str], n: int, unique: bool
) -> dict[str, list[FlightOption]]:
    """Migliori `n` per aeroporto di arrivo dell'andata (ordine di `airports`)."""
    ordered = sorted(options, key=lambda o: o.price)
    return {
        a: pick_top([o for o in ordered if o.destination == a], n, unique) for a in airports
    }


def combine_one_way(
    fares: list[OneWayFare],
    origins: list[str],
    destinations: list[str],
    max_price: float | None,
    min_nights: int,
    open_jaw: bool,
    max_nights: int = 365,
) -> list[FlightOption]:
    """Abbina tratte di andata (origine→destinazione) e di ritorno (destinazione→origine).

    Con `open_jaw` il ritorno può partire da un'altra destinazione e/o arrivare a
    un'altra origine rispetto all'andata; altrimenti solo la stessa rotta.
    """
    outs = [f for f in fares if f.origin in origins and f.destination in destinations]
    rets = [f for f in fares if f.origin in destinations and f.destination in origins]
    # una tratta già sopra soglia non può far parte di una combinazione valida
    if max_price is not None:
        outs = [f for f in outs if f.price < max_price]
        rets = [f for f in rets if f.price < max_price]
    combos = []
    for a in outs:
        for b in rets:
            if not open_jaw and (b.origin, b.destination) != (a.destination, a.origin):
                continue
            if not (min_nights <= (b.departure_at.date() - a.departure_at.date()).days <= max_nights):
                continue
            total = round(a.price + b.price, 2)
            if max_price is not None and total > max_price:
                continue
            combos.append(
                FlightOption(
                    origin=a.origin,
                    destination=a.destination,
                    departure_at=a.departure_at,
                    return_at=b.departure_at,
                    price=total,
                    airline="Ryanair",
                    link=a.link,
                    return_link=b.link,
                    source="ryanair",
                    return_origin=b.origin,
                    return_destination=b.destination,
                    arrival_out=a.arrival_at,
                    arrival_back=b.arrival_at,
                    price_out=a.price,
                    price_back=b.price,
                )
            )
    return combos


def _pause(cfg: Config) -> None:
    if cfg.search.request_delay_seconds > 0:
        time.sleep(cfg.search.request_delay_seconds)


def run_search(
    cfg: Config, client=None, ryanair=None, today: dt.date | None = None
) -> list[FlightOption]:
    s = cfg.search
    src = cfg.sources
    today = today or dt.date.today()  # noqa: DTZ011
    start = today + dt.timedelta(days=1)
    end = today + dt.timedelta(days=s.window_days)
    months = months_in_window(start, end)  # mesi di partenza
    return_months = months_in_window(start, end + dt.timedelta(days=s.max_nights))
    origins, dests = cfg.airports.origins, cfg.airports.destinations
    routes = [(o, d) for o in origins for d in dests if o != d]

    if src.travelpayouts and client is None:
        client = TravelpayoutsClient(os.getenv("TRAVELPAYOUTS_TOKEN", "").strip(), s.currency)
    if src.ryanair and ryanair is None:
        ryanair = RyanairClient(s.currency)
    notifier = resolve_ntfy(cfg)

    names = [n for n, on in (("Travelpayouts", src.travelpayouts), ("Ryanair", src.ryanair)) if on]
    print(f"Flight Scanner ({' + '.join(names)})")
    print(f"  partenze: {start} → {end} (il ritorno può cadere fino a {s.max_nights} notti dopo)")
    print(f"  origini: {', '.join(origins)}")
    print(f"  destinazioni: {', '.join(dests)}")
    print(
        f"  soglia: ≤ €{s.max_price:.0f} A/R · {s.min_nights}-{s.max_nights} notti · "
        f"max {s.max_transfers} scali"
        + (" · open-jaw" if src.ryanair and src.open_jaw else "")
    )
    print()

    candidates: list[FlightOption] = []   # tutte le offerte valide, senza soglia di prezzo

    if src.travelpayouts:
        print("Travelpayouts (A/R, prezzi in cache):")
        for origin, dest in routes:
            raw: list[FlightOption] = []
            for month in months:
                try:
                    raw += client.search_month(origin, dest, month)
                except ApiError as exc:
                    print(f"  [warn] {origin}→{dest} {month}: {exc}")
                _pause(cfg)
            valid = filter_offers(raw, cfg, start, end, ignore_price=True)
            hits = [o for o in valid if o.price <= s.max_price]
            if raw:
                cheapest = min(o.price for o in raw)
                print(f"  {origin}→{dest}: {len(hits)} ≤ soglia (più economico in assoluto: €{cheapest:.0f})")
            else:
                print(f"  {origin}→{dest}: nessun dato in cache")
            candidates += valid

    if src.ryanair:
        print("\nRyanair (tratte singole, prezzi live):")
        fares: list[OneWayFare] = []
        legs = [(o, d) for o, d in routes] + [(d, o) for o, d in routes]
        for a, b in legs:
            n = 0
            for month in return_months:
                try:
                    got = ryanair.search_month(a, b, month)
                except ApiError as exc:
                    print(f"  [warn] {a}→{b} {month}: {exc}")
                    got = []
                fares += [
                    f for f in got
                    if start <= f.departure_at.date() <= end + dt.timedelta(days=s.max_nights)
                ]
                n += len(got)
                _pause(cfg)
            if n:
                print(f"  {a}→{b}: {n} giorni con tariffa")
        combos = combine_one_way(
            fares, origins, dests, None, s.min_nights, src.open_jaw, s.max_nights
        )
        valid = filter_offers(combos, cfg, start, end, ignore_price=True)
        hits = [o for o in valid if o.price <= s.max_price]
        print(
            f"  combinazioni ≤ soglia: {len(hits)} "
            f"(di cui aeroporti diversi: {sum(1 for h in hits if h.open_jaw)})"
        )
        candidates += valid

    candidates = filter_offers(candidates, cfg, start, end, ignore_price=True)
    found = [o for o in candidates if o.price <= s.max_price]
    top = pick_top(found, s.top_n, s.unique_flights)
    counts = {n: sum(1 for o in found if o.source == n) for n in ("travelpayouts", "ryanair")}
    print(
        f"\nTotale ≤ soglia: {len(found)} (Travelpayouts: {counts['travelpayouts']}, "
        f"Ryanair: {counts['ryanair']}) · mostrati i {len(top)} più economici"
        + (" (senza voli ripetuti)" if s.unique_flights else "")
    )

    if notifier and cfg.ntfy.notify_new_best and found:
        notifier.notify_new_best(found[0], None)

    render_results(top, s.max_price, s.top_n)
    if cfg.output.file:
        by_airport = None
        if cfg.output.top_per_airport > 0:
            by_airport = top_per_airport(
                candidates, dests, cfg.output.top_per_airport, s.unique_flights
            )
        write_results_file(
            top, cfg.output.file, cfg.output.format, by_airport, s.max_price, s.top_n
        )
        print(f"\nRisultati salvati in: {cfg.output.file}")
    if notifier:
        notifier.notify_summary(top, s.max_price)
    return top
