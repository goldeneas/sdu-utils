"""Formattazione dell'output per il terminale."""
from __future__ import annotations

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
