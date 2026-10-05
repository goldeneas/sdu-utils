"""Orchestrazione della ricerca: one-way per data + combinazione andata/ritorno.

Google Flights mostra una direzione alla volta, quindi per ogni rotta si
interrogano separatamente le tratte di andata e di ritorno (una query per data)
e poi si combinano in Python: prezzo totale = andata + ritorno (esatto per le
low-cost, approssimato per le compagnie tradizionali).
"""
from __future__ import annotations

import datetime as dt
import time

from .config import Config  # pyright: ignore[reportMissingImports]
from .flights_client import (  # pyright: ignore[reportMissingImports]
    BlockedError,
    GoogleFlightsClient,
)
from .models import FlightOption  # pyright: ignore[reportMissingImports]
from .notifier import resolve_ntfy  # pyright: ignore[reportMissingImports]
from .output import render_results  # pyright: ignore[reportMissingImports]


class BestDealTracker:
    """Tiene traccia del miglior prezzo trovato e notifica i miglioramenti."""

    def __init__(self, notifier, notify_new_best: bool):
        self.notifier = notifier
        self.notify_new_best = notify_new_best
        self.best: FlightOption | None = None

    def update(self, opt: FlightOption) -> None:
        if self.best is None or opt.price < self.best.price - 1e-9:
            prev = self.best.price if self.best else None
            self.best = opt
            if self.notify_new_best and self.notifier:
                self.notifier.notify_new_best(opt, prev)


def _build_tasks(cfg: Config, today: dt.date):
    """Lista di (rotta, direzione, data) per tutte le query one-way."""
    s = cfg.search
    end = today + dt.timedelta(days=s.window_days)

    dep_dates = []
    d = today + dt.timedelta(days=1)
    while d + dt.timedelta(days=s.min_nights) <= end:
        dep_dates.append(d)
        d += dt.timedelta(days=s.date_step_departure)

    ret_dates = []
    r = today + dt.timedelta(days=1 + s.min_nights)
    while r <= end:
        ret_dates.append(r)
        r += dt.timedelta(days=s.date_step_return)

    tasks = []
    for origin in cfg.airports.origins:
        for dest in cfg.airports.destinations:
            route = (origin, dest)
            for dd in dep_dates:
                tasks.append((route, "out", dd))
            for rd in ret_dates:
                tasks.append((route, "ret", rd))
    return tasks, end, dep_dates, ret_dates


def _segment_layover_ok(seg, max_minutes: int) -> bool:
    return seg.layover_minutes is None or seg.layover_minutes <= max_minutes


def run_search(cfg: Config) -> list[FlightOption]:
    s = cfg.search
    today = dt.date.today()  # noqa: DTZ011  # data locale dell'utente
    tasks, end, dep_dates, ret_dates = _build_tasks(cfg, today)
    if s.max_queries > 0:
        tasks = tasks[: s.max_queries]

    notifier = resolve_ntfy(cfg)
    tracker = BestDealTracker(notifier, cfg.ntfy.notify_new_best)
    max_layover_min = int(s.max_layover_hours * 60)

    print("Flight Scanner")
    print(f"  finestra: {today} → {end}")
    print(f"  origini: {', '.join(cfg.airports.origins)}")
    print(f"  destinazioni: {', '.join(cfg.airports.destinations)}")
    print(
        f"  soglia: ≤ €{s.max_price:.0f} · min {s.min_nights} notti · "
        f"scalo max {s.max_layover_hours:.0f}h"
    )
    print(f"  ricerche pianificate (one-way): {len(tasks)}")
    if len(tasks) > 1500:
        print(
            "  [nota] ricerca estesa: valuta di aumentare `date_step_*` "
            "o ridurre gli aeroporti per accelerare"
        )
    print()

    client = GoogleFlightsClient(cfg.scraper)
    client.start()
    results: list[FlightOption] = []
    out_by_route: dict[tuple, dict] = {}
    ret_by_route: dict[tuple, dict] = {}

    try:
        for i, (route, direction, date) in enumerate(tasks, 1):
            origin, dest = route
            if direction == "out":
                offers = client.search_one_way(origin, dest, date)
                store = out_by_route.setdefault(route, {})
            else:
                offers = client.search_one_way(dest, origin, date)
                store = ret_by_route.setdefault(route, {})
            ok = [o for o in offers if _segment_layover_ok(o.segment, max_layover_min)]
            if ok:
                store[date] = min(ok, key=lambda o: o.price)

            if i % 25 == 0 or i == len(tasks):
                best = tracker.best.price if tracker.best else None
                best_txt = f"€{best:.2f}" if best is not None else "—"
                print(
                    f"  [{i}/{len(tasks)}] best: {best_txt} · "
                    f"{origin}→{dest} {'andata' if direction == 'out' else 'ritorno'}"
                )
            if s.request_delay_seconds > 0:
                time.sleep(s.request_delay_seconds)
    except BlockedError as exc:
        print(f"\n[e] {exc}")
        print("    Google sta limitando/bloccando le richieste: interrompo "
              "per non peggiorare. Mostro i risultati parziali.")
    except KeyboardInterrupt:
        print("\nInterrotto dall'utente: combino i risultati parziali.")
    finally:
        client.close()

    # Combinazione andata + ritorno
    for route in out_by_route:
        origin, dest = route
        out = out_by_route.get(route, {})
        ret = ret_by_route.get(route, {})
        for dd in dep_dates:
            if dd not in out:
                continue
            for rd in ret_dates:
                if (rd - dd).days < s.min_nights:
                    continue
                if rd not in ret:
                    continue
                total = round(out[dd].price + ret[rd].price, 2)
                if total <= s.max_price:
                    f = FlightOption(
                        origin=origin,
                        destination=dest,
                        departure_date=dd,
                        return_date=rd,
                        outbound=out[dd].segment,
                        inbound=ret[rd].segment,
                        price=total,
                    )
                    results.append(f)
                    tracker.update(f)

    results.sort(key=lambda f: f.price)
    top = results[: s.top_n]
    render_results(top, s.max_price, s.top_n)

    if notifier:
        notifier.notify_summary(top, s.max_price)

    return top
