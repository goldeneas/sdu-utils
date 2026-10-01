"""Install/uninstall a macOS LaunchAgent that runs the watcher periodically.

A LaunchAgent is the right tool on macOS: it survives reboots, runs without a
terminal, and ``StartInterval`` is respected even if the machine was asleep.
"""

from __future__ import annotations

import logging
import plistlib
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LABEL = "dk.sdu.examwatch"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = Path.home() / "Library" / "Logs" / "sdu-exam-watch"


def plist_path() -> Path:
    """Where the LaunchAgent property list lives."""
    return LAUNCH_AGENTS_DIR / f"{LABEL}.plist"


def build_plist(
    config_path: Path,
    interval_hours: float,
    python: str | None = None,
) -> dict[str, object]:
    """Build the LaunchAgent property list as a dictionary."""
    interpreter = python or sys.executable
    package_root = Path(__file__).resolve().parents[1]  # the ``src`` directory
    return {
        "Label": LABEL,
        "ProgramArguments": [
            interpreter,
            "-m",
            "sdu_exam_watch",
            "check",
            "--config",
            str(config_path),
        ],
        # Make ``sdu_exam_watch`` importable when running from a git checkout.
        "EnvironmentVariables": {"PYTHONPATH": str(package_root)},
        "WorkingDirectory": str(config_path.parent),
        "RunAtLoad": True,
        "StartInterval": _interval_seconds(interval_hours),
        "StandardOutPath": str(LOG_DIR / "stdout.log"),
        "StandardErrorPath": str(LOG_DIR / "stderr.log"),
    }


def install(config_path: Path, interval_hours: float) -> Path:
    """Write and load the LaunchAgent. Returns the plist path."""
    config_path = config_path.expanduser().resolve()
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    target = plist_path()
    # Unload any previous version first so changes take effect cleanly.
    _bootout(quiet=True)
    with target.open("wb") as handle:
        plistlib.dump(build_plist(config_path, interval_hours), handle)

    _bootstrap(target)
    log.info("installed LaunchAgent at %s", target)
    return target


def uninstall() -> bool:
    """Unload and delete the LaunchAgent. Returns True if a file was removed."""
    _bootout(quiet=True)
    target = plist_path()
    if target.exists():
        target.unlink()
        log.info("removed %s", target)
        return True
    return False


def _interval_seconds(interval_hours: float) -> int:
    """Convert hours to a LaunchAgent ``StartInterval`` in seconds (min 60)."""
    try:
        seconds = int(float(interval_hours) * 3600)
    except (TypeError, ValueError):
        seconds = 6 * 3600
    return max(60, seconds)


def _domain() -> str:
    return f"gui/{_uid()}"


def _uid() -> int:
    import os

    return os.getuid()


def _bootstrap(plist: Path) -> None:
    commands = [
        ["launchctl", "bootstrap", _domain(), str(plist)],
        ["launchctl", "load", "-w", str(plist)],  # older macOS fallback
    ]
    _run_first_success(commands, "load")


def _bootout(*, quiet: bool) -> None:
    commands = [
        ["launchctl", "bootout", f"{_domain()}/{LABEL}"],
        ["launchctl", "unload", "-w", str(plist_path())],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return
    if not quiet:
        log.warning("could not unload LaunchAgent %s", LABEL)


def _run_first_success(commands: list[list[str]], action: str) -> None:
    errors: list[str] = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return
        errors.append(result.stderr.strip() or " ".join(command))
    raise RuntimeError(f"failed to {action} LaunchAgent: {'; '.join(errors)}")
