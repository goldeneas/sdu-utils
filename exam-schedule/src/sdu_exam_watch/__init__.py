"""sdu-exam-watch — monitor SDU exam schedules and get notified when they change.

The package is intentionally dependency-free (Python standard library only)
so it can run from a plain ``python3 -m sdu_exam_watch`` invocation, a cron
job or a macOS LaunchAgent without any setup beyond a Python interpreter.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
