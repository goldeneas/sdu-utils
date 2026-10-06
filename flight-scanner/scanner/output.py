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


def _times(dep, arr, origin: str, dest: str) -> str:
    """'05:50 CPH → 08:10 TRN' (con '(+1)' se l'arrivo è il giorno dopo)."""
    if arr is None:
        return f"{dep:%H:%M} {origin} → {dest}"
    plus = (arr.date() - dep.date()).days
    return f"{dep:%H:%M} {origin} → {arr:%H:%M}{f' (+{plus})' if plus > 0 else ''} {dest}"


def _leg_extra(duration: str, stops: str, price) -> str:
    parts = [stops] + ([] if duration == "n/d" else [duration])
    if price is not None:
        parts.append(f"€{price:.2f}")
    return "  · " + " · ".join(parts)


def format_options(options: list[FlightOption]) -> list[str]:
    """Blocchi di testo (uno per offerta) usati sia nel terminale sia nel file .txt."""
    lines: list[str] = []
    for i, f in enumerate(options, 1):
        tag = "  [aeroporti diversi]" if f.open_jaw else ""
        lines.append(
            f"{i}) €{f.price:7.2f}   "
            f"{f.airline}{'' if f.source == 'ryanair' else '  [' + f.source + ']'}"
            f"{tag}  ({f.nights} notti)"
        )
        out_extra = _leg_extra(f.duration_out_human, f.stops_human(f.transfers), f.price_out)
        back_extra = _leg_extra(f.duration_back_human, f.stops_human(f.return_transfers), f.price_back)
        lines.append(
            f"   Andata:  {format_date(f.departure_date)}  "
            f"{_times(f.departure_at, f.arrival_out, f.origin, f.destination)}{out_extra}"
        )
        if f.return_link:  # biglietti separati: un link per tratta
            lines.append(f"            {f.link}")
        lines.append(
            f"   Ritorno: {format_date(f.return_date)}  "
            f"{_times(f.return_at, f.arrival_back, f.return_origin, f.return_destination)}{back_extra}"
        )
        if f.return_link:
            lines.append(f"            {f.return_link}")
        elif f.link:
            lines.append(f"   Link A/R: {f.link}")
        lines.append("-" * 80)
    return lines


def _top_text(options: list[FlightOption], max_price: float, top_n: int) -> list[str]:
    if not options:
        return [f"Nessun volo trovato ≤ €{max_price:.0f} nella finestra di ricerca."]
    return [
        f"Migliori {len(options)} offerte (soglia €{max_price:.0f}, top {top_n}):",
        "=" * 80,
        *format_options(options),
    ]


def render_results(options: list[FlightOption], max_price: float, top_n: int) -> None:
    print()
    print("\n".join(_top_text(options, max_price, top_n)))


def _airport_text(by_airport: dict[str, list[FlightOption]]) -> list[str]:
    lines = ["", "=" * 80, "RIEPILOGO PER AEROPORTO (senza soglia di prezzo)", "=" * 80]
    for airport, opts in by_airport.items():
        lines += ["", f"### {airport} — migliori {len(opts)}" if opts else f"### {airport} — nessun volo trovato"]
        if opts:
            lines.append("-" * 80)
            lines += format_options(opts)
    return lines


def _as_row(f: FlightOption) -> dict:
    return {
        "price": f.price,
        "currency": f.currency,
        "origin": f.origin,
        "destination": f.destination,
        "departure_at": f.departure_at.isoformat(timespec="minutes"),
        "arrival_out": f.arrival_out.isoformat(timespec="minutes") if f.arrival_out else "",
        "return_at": f.return_at.isoformat(timespec="minutes"),
        "arrival_back": f.arrival_back.isoformat(timespec="minutes") if f.arrival_back else "",
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


def write_results_file(
    options: list[FlightOption],
    path: str,
    fmt: str = "csv",
    by_airport: dict[str, list[FlightOption]] | None = None,
    max_price: float = 0.0,
    top_n: int = 10,
) -> None:
    """Salva la top e, se presente, il riepilogo per aeroporto (CSV, TXT o JSON)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        rows = [
            {"section": "top", "airport": "", "rank": i, **_as_row(f)}
            for i, f in enumerate(options, 1)
        ]
        for airport, opts in (by_airport or {}).items():
            rows += [
                {"section": "aeroporto", "airport": airport, "rank": i, **_as_row(f)}
                for i, f in enumerate(opts, 1)
            ]
        if not rows:
            p.write_text("", encoding="utf-8")
            return
        with p.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "json":
        data = {"top": [_as_row(f) for f in options]}
        if by_airport is not None:
            data["per_airport"] = {a: [_as_row(f) for f in o] for a, o in by_airport.items()}
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:  # txt
        lines = _top_text(options, max_price, top_n)
        if by_airport is not None:
            lines += _airport_text(by_airport)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
