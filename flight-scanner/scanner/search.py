"""Orchestrazione: Travelpayouts (A/R) + tariffe per tratta (Ryanair, Google Flights), filtro e unione."""
from __future__ import annotations

import datetime as dt
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .config import Config
from .models import FlightOption, OneWayFare
from .report import SearchReport, SourceReport
from .google_flights import GoogleFlightsClient
from .ryanair import RyanairClient
from .travelpayouts import ApiError, TravelpayoutsClient


def months_in_window(start: dt.date, end: dt.date) -> list[str]:
    months, d = [], start.replace(day=1)
    while d <= end:
        months.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return months


def filter_offers(
    offers, cfg: Config, start: dt.date, end: dt.date, ignore_price: bool = False,
    rejected: Counter | None = None,
) -> list[FlightOption]:
    """Applica finestra di date, notti minime, scali e soglia di prezzo; deduplica."""
    s = cfg.search
    rejected = rejected if rejected is not None else Counter()
    seen, out = set(), []
    for o in sorted(offers, key=lambda o: o.price):  # a parità di voli resta il più economico
        if not (start <= o.departure_date <= end):  # solo la partenza è vincolata alla finestra
            rejected["fuori finestra"] += 1
            continue
        if not (s.min_nights <= o.nights <= s.max_nights):
            rejected["notti fuori range"] += 1
            continue
        if max(o.transfers, o.return_transfers) > s.max_transfers:
            rejected["troppi scali"] += 1
            continue
        if o.price > s.max_price and not ignore_price:
            rejected["prezzo"] += 1
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
                    airline=a.airline if a.airline == b.airline else f"{a.airline} + {b.airline}",
                    link=a.link,
                    return_link=b.link,
                    source=a.source if a.source == b.source else "misto",
                    transfers=a.transfers,
                    return_transfers=b.transfers,
                    duration_out=a.duration,
                    duration_back=b.duration,
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


def google_tasks(cfg: Config, routes, start: dt.date, end: dt.date):
    """(origine, destinazione, giorno) da interrogare: partenze nella finestra, ritorni dopo."""
    s, g = cfg.search, cfg.google
    out_days = [start + dt.timedelta(days=i) for i in range(0, (end - start).days + 1, g.date_step)]
    ret_first = start + dt.timedelta(days=s.min_nights)
    ret_last = end + dt.timedelta(days=s.max_nights)
    ret_days = [ret_first + dt.timedelta(days=i) for i in range(0, (ret_last - ret_first).days + 1, g.date_step)]
    tasks = [(o, d, day) for o, d in routes for day in out_days]
    tasks += [(d, o, day) for o, d in routes for day in ret_days]
    return tasks[: g.max_queries] if g.max_queries > 0 else tasks


def _collect_google(
    cfg: Config, client, routes, start: dt.date, end: dt.date,
    status: SourceReport | None = None,
) -> list[OneWayFare]:
    status = status if status is not None else SourceReport()
    g = cfg.google
    tasks = google_tasks(cfg, routes, start, end)
    print(
        f"\nGoogle Flights (tratte singole, prezzi live): {len(tasks)} richieste, "
        f"{g.workers} in parallelo (ogni richiesta richiede qualche secondo)",
        flush=True,
    )
    fares: list[OneWayFare] = []
    errors, done, aborted = [], 0, False
    t0 = time.monotonic()

    def work(task):
        if aborted:
            return None
        try:
            return client.search_day(*task)
        except ApiError as exc:
            return exc
        finally:
            if g.delay_seconds > 0:
                time.sleep(g.delay_seconds)

    try:
        with ThreadPoolExecutor(max_workers=g.workers) as pool:
            for res in pool.map(work, tasks):
                done += 1
                if isinstance(res, ApiError):
                    status.failed += 1
                    errors.append(str(res))
                    if len(errors) >= 10 and len(errors) > done // 2:  # quasi tutto fallisce: blocco
                        aborted = True
                        status.aborted = True
                elif res is not None:
                    status.succeeded += 1
                    fares += res
                if not aborted and (done in (1, 5) or done % 25 == 0 or done == len(tasks)):
                    elapsed = time.monotonic() - t0
                    eta = elapsed / done * (len(tasks) - done)
                    print(
                        f"  [{done}/{len(tasks)}] {len(fares)} tariffe, {len(errors)} errori"
                        f" · {elapsed / 60:.1f} min trascorsi, ~{eta / 60:.0f} min rimanenti",
                        flush=True,
                    )
    except KeyboardInterrupt:
        aborted = True
        status.aborted = True
        print("  interrotto dall'utente: uso le tariffe raccolte finora")
    stats = getattr(client, "stats", None)
    if stats:
        print(
            f"  pagine ricevute: {stats['pagine']} · con almeno una tariffa: {stats['con_voli']} · "
            f"voci nelle pagine: {stats['voci']} (scartate senza prezzo/formato: {stats['scartate']})"
        )
    if aborted and errors:
        print("  [e] troppi errori, interrompo Google Flights. Primo errore:")
        print(f"      {errors[0]}")
    elif errors:
        print(f"  [warn] {len(errors)} richieste fallite, esempio: {errors[0]}")
    return fares


def run_search(
    cfg: Config, client=None, ryanair=None, google=None, today: dt.date | None = None,
    *, report: SearchReport | None = None,
) -> list[FlightOption]:
    report = report if report is not None else SearchReport()
    report.per_airport = {}
    report.sources = {
        name: SourceReport() for name in ("travelpayouts", "ryanair", "google_flights")
        if getattr(cfg.sources, name)
    }
    s = cfg.search
    src = cfg.sources
    today = today or dt.date.today()  # noqa: DTZ011
    start = today + dt.timedelta(days=1 + s.exclude_next_days)
    end = today + dt.timedelta(days=s.window_days)
    months = months_in_window(start, end)  # mesi di partenza
    return_months = months_in_window(start, end + dt.timedelta(days=s.max_nights))
    origins, dests = cfg.airports.origins, cfg.airports.destinations
    routes = [(o, d) for o in origins for d in dests if o != d]

    if src.travelpayouts and client is None:
        client = TravelpayoutsClient(os.getenv("TRAVELPAYOUTS_TOKEN", "").strip(), s.currency)
    if src.ryanair and ryanair is None:
        ryanair = RyanairClient(s.currency)
    if src.google_flights and google is None:
        google = GoogleFlightsClient(s.currency, cfg.google.airlines, s.max_transfers)

    names = [
        n for n, on in (
            ("Travelpayouts", src.travelpayouts), ("Ryanair", src.ryanair),
            ("Google Flights", src.google_flights),
        ) if on
    ]
    print(f"Flight Scanner ({' + '.join(names)})")
    print(f"  partenze: {start} → {end} (il ritorno può cadere fino a {s.max_nights} notti dopo)")
    print(f"  origini: {', '.join(origins)}")
    print(f"  destinazioni: {', '.join(dests)}")
    print(
        f"  soglia: ≤ €{s.max_price:.0f} A/R · {s.min_nights}-{s.max_nights} notti · "
        f"max {s.max_transfers} scali"
        + (" · open-jaw" if (src.ryanair or src.google_flights) and src.open_jaw else "")
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
                    report.sources["travelpayouts"].failed += 1
                    print(f"  [warn] {origin}→{dest} {month}: {exc}")
                else:
                    report.sources["travelpayouts"].succeeded += 1
                _pause(cfg)
            rejected: Counter = Counter()
            valid = filter_offers(raw, cfg, start, end, ignore_price=True, rejected=rejected)
            hits = [o for o in valid if o.price <= s.max_price]
            if raw:
                line = f"  {origin}→{dest}: {len(hits)} ≤ soglia"
                if valid:
                    line += f" · più economico valido: €{valid[0].price:.0f}"
                line += f" · più economico in cache (qualsiasi data): €{min(o.price for o in raw):.0f}"
                if rejected:
                    line += " · scartati: " + ", ".join(f"{n} {r}" for r, n in rejected.items())
                print(line)
            else:
                print(f"  {origin}→{dest}: nessun dato in cache")
            candidates += valid

    fares: list[OneWayFare] = []   # tariffe per singola tratta, da tutte le fonti

    if src.ryanair:
        print("\nRyanair (tratte singole, prezzi live):")
        legs = [(o, d) for o, d in routes] + [(d, o) for o, d in routes]
        for a, b in legs:
            n = 0
            for month in return_months:
                try:
                    got = ryanair.search_month(a, b, month)
                except ApiError as exc:
                    report.sources["ryanair"].failed += 1
                    print(f"  [warn] {a}→{b} {month}: {exc}")
                    got = []
                else:
                    report.sources["ryanair"].succeeded += 1
                fares += [
                    f for f in got
                    if start <= f.departure_at.date() <= end + dt.timedelta(days=s.max_nights)
                ]
                n += len(got)
                _pause(cfg)
            if n:
                print(f"  {a}→{b}: {n} giorni con tariffa")

    if src.google_flights:
        fares += _collect_google(cfg, google, routes, start, end, report.sources["google_flights"])

    if src.ryanair or src.google_flights:
        combos = combine_one_way(
            fares, origins, dests, None, s.min_nights, src.open_jaw, s.max_nights
        )
        valid = filter_offers(combos, cfg, start, end, ignore_price=True)
        hits = [o for o in valid if o.price <= s.max_price]
        print(
            f"\nCombinazioni da tariffe per tratta ≤ soglia: {len(hits)} "
            f"(di cui aeroporti diversi: {sum(1 for h in hits if h.open_jaw)})"
        )
        candidates += valid

    candidates = filter_offers(candidates, cfg, start, end, ignore_price=True)
    found = [o for o in candidates if o.price <= s.max_price]
    top = pick_top(found, s.top_n, s.unique_flights)
    report.per_airport = top_per_airport(candidates, dests, s.top_per_airport, s.unique_flights)
    counts = Counter(o.source for o in found)
    print(
        f"\nTotale ≤ soglia: {len(found)} ("
        + ", ".join(f"{n}: {c}" for n, c in sorted(counts.items()))
        + f") · mostrati i {len(top)} più economici"
        + (" (senza voli ripetuti)" if s.unique_flights else "")
    )

    return top
