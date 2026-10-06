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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:2]))
