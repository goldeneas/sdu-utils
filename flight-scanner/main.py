#!/usr/bin/env python3
"""Entry point dello script Flight Scanner."""
from __future__ import annotations

import argparse

from scanner.config import load_config
from scanner.search import run_search
from scanner.travelpayouts import ApiError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Flight Scanner — trova voli A/R convenienti (Travelpayouts)."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="percorso del file di configurazione (default: config.yaml)",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    try:
        run_search(cfg)
    except ApiError as exc:
        print(f"Errore: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
