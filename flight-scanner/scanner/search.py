"""Orchestrazione: una query per rotta e mese, poi filtro sui criteri."""
from __future__ import annotations

import datetime as dt
import os
import time

from .config import Config
from .models import FlightOption
from .notifier import resolve_ntfy
from .output import render_results, write_results_file
from .travelpayouts import ApiError, TravelpayoutsClient


def months_in_window(start: dt.date, end: dt.date) -> list[str]:
    months, d = [], start.replace(day=1)
    while d <= end:
        months.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return months


def filter_offers(offers, cfg: Config, start: dt.date, end: dt.date) -> list[FlightOption]:
    """Applica finestra di date, notti minime, scali e soglia di prezzo; deduplica."""
    s = cfg.search
    seen, out = set(), []
    for o in offers:
        if not (start <= o.departure_date <= end and o.return_date <= end):
            continue
        if o.nights < s.min_nights:
            continue
        if max(o.transfers, o.return_transfers) > s.max_transfers:
            continue
        if o.price > s.max_price:
            continue
        if o.key in seen:
            continue
        seen.add(o.key)
        out.append(o)
    out.sort(key=lambda o: o.price)
    return out


def run_search(cfg: Config, client=None, today: dt.date | None = None) -> list[FlightOption]:
    s = cfg.search
    today = today or dt.date.today()  # noqa: DTZ011
    start = today + dt.timedelta(days=1)
    end = today + dt.timedelta(days=s.window_days)
    months = months_in_window(start, end)
    routes = [(o, d) for o in cfg.airports.origins for d in cfg.airports.destinations if o != d]

    if client is None:
        client = TravelpayoutsClient(os.getenv("TRAVELPAYOUTS_TOKEN", "").strip(), s.currency)
    notifier = resolve_ntfy(cfg)

    print("Flight Scanner (Travelpayouts)")
    print(f"  finestra: {start} → {end}")
    print(f"  origini: {', '.join(cfg.airports.origins)}")
    print(f"  destinazioni: {', '.join(cfg.airports.destinations)}")
    print(
        f"  soglia: ≤ €{s.max_price:.0f} A/R · min {s.min_nights} notti · "
        f"max {s.max_transfers} scali"
    )
    print(f"  richieste: {len(routes) * len(months)}\n")

    found: list[FlightOption] = []
    best: float | None = None
    for origin, dest in routes:
        raw: list[FlightOption] = []
        for month in months:
            try:
                raw += client.search_month(origin, dest, month)
            except ApiError as exc:
                print(f"  [warn] {origin}→{dest} {month}: {exc}")
            if s.request_delay_seconds > 0:
                time.sleep(s.request_delay_seconds)
        hits = filter_offers(raw, cfg, start, end)
        cheapest_any = min((o.price for o in raw), default=None)
        info = f"{len(hits)} ≤ soglia"
        if cheapest_any is not None:
            info += f" (A/R più economico in assoluto: €{cheapest_any:.0f})"
        else:
            info = "nessun dato in cache"
        print(f"  {origin}→{dest}: {info}")
        for o in hits:
            if cfg.ntfy.notify_new_best and notifier and (best is None or o.price < best - 1e-9):
                notifier.notify_new_best(o, best)
            best = o.price if best is None else min(best, o.price)
        found += hits

    found.sort(key=lambda o: o.price)
    top = found[: s.top_n]
    render_results(top, s.max_price, s.top_n)
    if cfg.output.file:
        write_results_file(top, cfg.output.file, cfg.output.format)
        print(f"\nRisultati salvati in: {cfg.output.file}")
    if notifier:
        notifier.notify_summary(top, s.max_price)
    return top
