"""Diagnostica: `python -m scanner.inspect_dump [file.html]`

Stampa la struttura della pagina Google Flights salvata in caso di errore
(blocchi <script>, classi, dimensioni, anteprima), per capire dove sono i dati.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser


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
    try:
        from fast_flights.parser import parse_js
        res = parse_js(js)
        print(f"parse_js OK: {len(res)} voli")
    except Exception:  # noqa: BLE001
        print("parse_js fallisce:")
        traceback.print_exc()


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:2]))
