"""Formattazione dell'output per il terminale e su file."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import FlightOption

_DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_MONTHS = [
    "gen", "feb", "mar", "apr", "mag", "giu",
    "lug", "ago", "set", "ott", "nov", "dic",
]


def format_date(d) -> str:
    return f"{_DAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} {d.year}"


def _leg_price(p) -> str:
    return f" · €{p:.2f}" if p is not None else ""


def render_results(options: list[FlightOption], max_price: float, top_n: int) -> None:
    print()
    if not options:
        print(f"Nessun volo trovato ≤ €{max_price:.0f} nella finestra di ricerca.")
        return
    print(f"Migliori {len(options)} offerte (soglia €{max_price:.0f}, top {top_n}):")
    print("=" * 80)
    for i, f in enumerate(options, 1):
        tag = "  [aeroporti diversi]" if f.open_jaw else ""
        print(
            f"{i}) €{f.price:7.2f}   {f.origin} → {f.destination}   "
            f"{f.airline}  [{f.source}]{tag}  ({f.nights} notti)"
        )
        print(
            f"   Andata:  {format_date(f.departure_date)}  "
            f"{f.departure_at:%H:%M}  · {f.duration_out_human} · "
            f"{f.stops_human(f.transfers)}{_leg_price(f.price_out)}"
        )
        print(
            f"   Ritorno: {format_date(f.return_date)}  "
            f"{f.return_at:%H:%M} {f.return_origin} → {f.return_destination}  · "
            f"{f.duration_back_human} · "
            f"{f.stops_human(f.return_transfers)}{_leg_price(f.price_back)}"
        )
        if f.link:
            print(f"   Link:    {f.link}")
        if f.return_link:
            print(f"   Link ritorno: {f.return_link}")
        print("-" * 80)


def _as_row(f: FlightOption) -> dict:
    return {
        "price": f.price,
        "currency": f.currency,
        "origin": f.origin,
        "destination": f.destination,
        "departure_at": f.departure_at.isoformat(timespec="minutes"),
        "return_at": f.return_at.isoformat(timespec="minutes"),
        "nights": f.nights,
        "return_origin": f.return_origin,
        "return_destination": f.return_destination,
        "open_jaw": f.open_jaw,
        "source": f.source,
        "price_out": f.price_out,
        "price_back": f.price_back,
        "airline": f.airline,
        "out_stops": f.transfers,
        "in_stops": f.return_transfers,
        "out_duration_min": f.duration_out,
        "in_duration_min": f.duration_back,
        "link": f.link,
        "return_link": f.return_link,
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
        lines = [f.summary for f in options]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
