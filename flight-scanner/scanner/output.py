"""Formattazione dell'output per il terminale e su file."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import FlightOption  # pyright: ignore[reportMissingImports]

_DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_MONTHS = [
    "gen", "feb", "mar", "apr", "mag", "giu",
    "lug", "ago", "set", "ott", "nov", "dic",
]


def format_date(d) -> str:
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} {d.year}"


def _fmt_arrival(dep: str, arr: str) -> str:
    """Aggiunge '(+1)' se l'arrivo è il giorno successivo (volo notturno)."""
    if dep and arr and arr < dep:  # confronto stringa valido per HH:MM a 24h
        return f"{arr} (+1)"
    return arr


def render_results(options: list[FlightOption], max_price: float, top_n: int) -> None:
    print()
    if not options:
        print(f"Nessun volo trovato ≤ €{max_price:.0f} nella finestra di ricerca.")
        return
    print(f"Migliori {len(options)} offerte (soglia €{max_price:.0f}, top {top_n}):")
    print("=" * 80)
    for i, f in enumerate(options, 1):
        print(f"{i}) €{f.price:7.2f}   {f.origin} → {f.destination}   {f.outbound.airline}")
        print(
            f"   Andata:  {format_date(f.departure_date)}  "
            f"{f.outbound.departure_time} {f.origin} → "
            f"{_fmt_arrival(f.outbound.departure_time, f.outbound.arrival_time)} "
            f"{f.destination}  · {f.outbound.duration_human} · "
            f"{f.outbound.stops_human}"
        )
        print(
            f"   Ritorno: {format_date(f.return_date)}  "
            f"{f.inbound.departure_time} {f.destination} → "
            f"{_fmt_arrival(f.inbound.departure_time, f.inbound.arrival_time)} "
            f"{f.origin}  · {f.inbound.duration_human} · {f.inbound.stops_human}"
        )
        print("-" * 80)


def _as_row(f: FlightOption) -> dict:
    return {
        "price": f.price,
        "currency": f.currency,
        "origin": f.origin,
        "destination": f.destination,
        "departure_date": f.departure_date.isoformat(),
        "return_date": f.return_date.isoformat(),
        "out_airline": f.outbound.airline,
        "out_departure": f.outbound.departure_time,
        "out_arrival": f.outbound.arrival_time,
        "out_duration_min": f.outbound.duration_minutes,
        "out_stops": f.outbound.stops,
        "out_layover_min": f.outbound.layover_minutes,
        "in_airline": f.inbound.airline,
        "in_departure": f.inbound.departure_time,
        "in_arrival": f.inbound.arrival_time,
        "in_duration_min": f.inbound.duration_minutes,
        "in_stops": f.inbound.stops,
        "in_layover_min": f.inbound.layover_minutes,
    }


def write_results_file(options: list[FlightOption], path: str, fmt: str = "csv") -> None:
    """Salva i risultati su file in formato CSV, TXT o JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        if not options:
            p.write_text("", encoding="utf-8")
            return
        fields = list(_as_row(options[0]).keys())
        with p.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for f in options:
                writer.writerow(_as_row(f))
    elif fmt == "json":
        p.write_text(
            json.dumps([_as_row(f) for f in options], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:  # txt
        lines = [
            f"€{f.price:.2f}  {f.origin}→{f.destination}  "
            f"{f.departure_date} → {f.return_date}  {f.outbound.airline}"
            for f in options
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
