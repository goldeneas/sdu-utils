"""State persisted between checks.

State is a plain JSON document keyed by target name. It records the last
fingerprint of every schedule artifact we have seen so the next run can tell
*new* files from *changed* ones. The file is written atomically so an
interrupted run (or a power cut on the Mac) can never leave a corrupt state.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STATE_VERSION = 1


def empty_state() -> dict[str, Any]:
    """Return a fresh, empty state document."""
    return {"version": STATE_VERSION, "targets": {}}


def load_state(path: Path) -> dict[str, Any]:
    """Load state, tolerating a missing or corrupt file.

    A corrupt state is treated as "empty" rather than fatal: the worst case is
    that the next run re-establishes a baseline instead of notifying.
    """
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read state file %s (%s); starting fresh", path, exc)
        return empty_state()
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        log.warning("state file %s has an unexpected format; starting fresh", path)
        return empty_state()
    data.setdefault("targets", {})
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically write state to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
