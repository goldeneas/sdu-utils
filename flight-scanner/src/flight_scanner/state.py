"""Persistent memory so the watcher alerts on *changes*, not every run.

The state is a tiny JSON document:

* ``best_total``  -- cheapest round-trip total ever seen (EUR)
* ``deals``       -- ``signature -> cheapest price seen`` for each trip shape
* ``last_run``    -- ISO timestamp of the previous check
* ``runs``        -- how many checks have completed

It is written atomically (temp file + ``os.replace``) so an interrupted run
cannot corrupt it, and a corrupt/missing file is treated as empty: the worst
case is one extra baseline notification rather than a crash.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_VERSION = 1


@dataclass(slots=True)
class WatchState:
    """Everything the watcher remembers between runs."""

    best_total: float | None = None
    deals: dict[str, float] = field(default_factory=dict)
    last_run: str = ""
    runs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "best_total": self.best_total,
            "deals": dict(sorted(self.deals.items())),
            "last_run": self.last_run,
            "runs": self.runs,
        }

    @classmethod
    def from_dict(cls, data: Any) -> WatchState:
        if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
            return cls()
        best = data.get("best_total")
        try:
            best_total = float(best) if best is not None else None
        except (TypeError, ValueError):
            best_total = None
        raw_deals = data.get("deals")
        deals: dict[str, float] = {}
        if isinstance(raw_deals, dict):
            for key, value in raw_deals.items():
                try:
                    deals[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
        raw_runs = data.get("runs", 0)
        try:
            runs = int(raw_runs or 0)
        except (TypeError, ValueError):
            runs = 0
        return cls(
            best_total=best_total,
            deals=deals,
            last_run=str(data.get("last_run", "")),
            runs=runs,
        )

    def note_run(self) -> None:
        """Record that a run just finished."""
        self.last_run = datetime.now(UTC).isoformat(timespec="seconds")
        self.runs += 1


def load_state(path: Path) -> WatchState:
    """Load state, tolerating a missing or corrupt file."""
    if not path.exists():
        return WatchState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return WatchState()
    return WatchState.from_dict(data)


def save_state(path: Path, state: WatchState) -> None:
    """Atomically write ``state`` to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
