"""Enable ``python3 -m sdu_exam_watch`` as an alternative to the console script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover - trivial entry point
    raise SystemExit(main())
