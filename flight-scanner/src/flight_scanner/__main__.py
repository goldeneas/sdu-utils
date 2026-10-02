"""``python -m flight_scanner [scan|watch] ...`` dispatcher.

``python -m flight_scanner watch ...`` runs the periodic deal watcher;
anything else is forwarded to the one-off scanner, so both
``python -m flight_scanner --out-start ...`` and
``python -m flight_scanner scan --out-start ...`` work.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "watch":
        from .watch import main as watch_main

        return watch_main(args[1:])
    if args and args[0] == "scan":
        args = args[1:]
    from .scan import main as scan_main

    scan_main(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
