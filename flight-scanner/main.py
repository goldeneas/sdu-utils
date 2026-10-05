#!/usr/bin/env python3
"""Entry point dello script Flight Scanner."""
from __future__ import annotations

import argparse

from scanner.config import load_config  # pyright: ignore[reportMissingImports]
from scanner.search import run_search  # pyright: ignore[reportMissingImports]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Flight Scanner — trova voli convenienti via Google Flights."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="percorso del file di configurazione (default: config.yaml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="salva HTML e screenshot di ogni ricerca per la manutenzione",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.debug:
        cfg.scraper.debug_dump_dir = cfg.scraper.debug_dump_dir or "debug_dumps"

    run_search(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
