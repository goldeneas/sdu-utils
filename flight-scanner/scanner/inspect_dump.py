"""Diagnostica: `python -m scanner.inspect_dump [file.html]`

Stampa la struttura della pagina Google Flights salvata in caso di errore
(blocchi <script>, classi, dimensioni, anteprima), per capire dove sono i dati.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser


def fetch_to_file(origin: str, dest: str, day: str, airlines: list[str] | None = None) -> str:
    """Scarica la pagina di una tratta (come fa lo scanner) e la salva per l'analisi."""
    from fast_flights import FlightQuery, create_query

    from scanner.google_flights import fetch_html

    q = create_query(
        flights=[FlightQuery(date=day, from_airport=origin, to_airport=dest, airlines=airlines)],
        seat="economy", trip="one-way", language="en-US", currency="EUR",
    )
    out = Path("debug_dumps") / f"fetch_{origin}_{dest}_{day}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(fetch_html(q), encoding="utf-8")
    print(f"scaricato: {out}")
    return str(out)


def main(path: str = "debug_dumps/google_flights_error.html") -> int:
    html = Path(path).read_text(encoding="utf-8")
    p = LexborHTMLParser(html)
    t = p.css_first("title")
    print(f"file: {path} · {len(html)} byte · titolo: {t.text() if t else None!r}")
    scripts = p.css("script")
    print(f"script totali: {len(scripts)}")
    for i, s in enumerate(scripts):
        txt = s.text() or ""
        cls = s.attributes.get("class")
        if cls or "AF_initDataCallback" in txt or "data:" in txt[:3000]:
            head = re.sub(r"\s+", " ", txt[:160])
            print(f"  #{i} class={cls!r} len={len(txt)} head={head!r}")
    for word in ("Wizz", "easyJet", "Ryanair", "Norwegian", "€", "EUR", "No results", "nessun"):
        print(f"  '{word}': {html.count(word)} occorrenze")
    _inspect_ds1(p)
    return 0


def _entry_shapes(payload) -> None:
    for idx in (2, 3):
        try:
            entries = payload[idx][0] or []
        except (IndexError, TypeError):
            entries = []
        print(f"payload[{idx}][0]: {len(entries)} voci")
        for n, k in enumerate(entries[:3]):
            print(f"  voce {n}: {json.dumps(_shape(k, 0, 3), ensure_ascii=False)[:900]}")


def _shape(x, depth=0, max_depth=2):
    """Forma sintetica di una struttura JSON annidata (tipi e lunghezze)."""
    if isinstance(x, list):
        if depth >= max_depth:
            return f"list[{len(x)}]"
        return [_shape(v, depth + 1, max_depth) for v in x[:12]]
    if isinstance(x, str):
        return f"str({x[:25]!r})" if len(x) <= 25 else f"str[{len(x)}]"
    return repr(x) if x is None or isinstance(x, (int, float, bool)) else type(x).__name__


def _inspect_ds1(p) -> None:
    import json
    import traceback

    node = p.css_first("script.ds\\:1")
    if node is None:
        print("\nscript.ds:1 non trovato")
        return
    js = node.text()
    print("\n--- ds:1 ---")
    try:
        data = js.split("data:", 1)[1].rsplit(",", 1)[0]
        if data.endswith("errorHasStatus: true"):
            print("errorHasStatus: true (Google segnala nessun risultato)")
            return
        payload = json.loads(data)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return
    print("forma payload:", json.dumps(_shape(payload), ensure_ascii=False)[:1800])
    _entry_shapes(payload)
    try:
        from scanner.google_flights import parse_js_tolerant
        res = parse_js_tolerant(js)
        print(f"parser tollerante OK: {len(res)} voli con prezzo")
        for f in res[:5]:
            seg = f.flights[0]
            print(f"  €{f.price} {f.airlines} {seg.from_airport.code}→{f.flights[-1].to_airport.code} {seg.departure.time}")
    except Exception:  # noqa: BLE001
        print("parser tollerante fallisce:")
        traceback.print_exc()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--fetch":
        o, d, day = args[1:4]
        raise SystemExit(main(fetch_to_file(o, d, day, args[4].split(",") if len(args) > 4 else None)))
    raise SystemExit(main(*args[:1]))
