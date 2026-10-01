"""Configuration loading and validation.

Configuration lives in a TOML file (``config.toml``). See
``config.example.toml`` for a fully commented example.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_LINK_PATTERN = r"\.(xlsx|xls|pdf)([?#]|$)"
ALLOWED_PRIORITIES = {"min", "low", "default", "high", "max", "1", "2", "3", "4", "5"}

# The OWASP-recommended default: only HTTPS targets, so a mis-set URL cannot
# send the schedule/notification credentials over plaintext.
DEFAULT_USER_AGENT = "sdu-exam-watch/1.0 (polite exam-schedule watcher)"

# The exact programme name as published in the XLSX ``Udd`` column for the
# MSc in Software Engineering, Odense.
MSC_SOFTWARE_ENGINEERING = "Kandidat i Software Engineering (MSc)"
MSC_SWE_EXAM_PAGE = (
    "https://mitsdu.dk/da/mit_studie/kandidat/"
    "civilingenioer_i_softwareengineering/eksamen/eksamensplan"
)


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid."""


@dataclass(slots=True)
class Target:
    """One page (or file) to watch."""

    name: str
    url: str
    link_pattern: str = DEFAULT_LINK_PATTERN
    programmes: tuple[str, ...] = ()
    summary: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ConfigError("every [[target]] needs a non-empty 'name'")
        if not self.url.lower().startswith(("http://", "https://")):
            raise ConfigError(
                f"target {self.name!r}: 'url' must start with http:// or https://"
            )


@dataclass(slots=True)
class NotifyConfig:
    """How to tell the user something changed."""

    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    ntfy_token: str = ""
    priority: str = "high"
    tags: tuple[str, ...] = ("calendar", "tada")
    webhook_url: str = ""
    macos_notification: bool = False
    stdout: bool = False
    # Attach the published PDF/Excel itself to the notification.
    attach_files: bool = True

    def has_any_channel(self) -> bool:
        return bool(
            self.ntfy_topic or self.webhook_url or self.macos_notification or self.stdout
        )

    def __post_init__(self) -> None:
        if str(self.priority).lower() not in ALLOWED_PRIORITIES:
            raise ConfigError(
                f"notify.priority must be one of {sorted(ALLOWED_PRIORITIES)}"
            )


@dataclass(slots=True)
class Settings:
    """Tuning knobs for the watcher itself."""

    state_file: Path
    timeout: float = 30.0
    retries: int = 3
    hash_files: bool = False
    summary_limit: int = 12
    notify_on_first_run: bool = False
    interval_hours: float = 6.0
    user_agent: str = DEFAULT_USER_AGENT


@dataclass(slots=True)
class Config:
    """The fully-resolved configuration."""

    settings: Settings
    notify: NotifyConfig
    targets: list[Target] = field(default_factory=list)
    path: Path | None = None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def default_config_path() -> Path:
    """Return the first sensible config path that exists.

    Search order: ``./config.toml`` then
    ``~/.config/sdu-exam-watch/config.toml``.
    """
    candidates = [
        Path.cwd() / "config.toml",
        Path.home() / ".config" / "sdu-exam-watch" / "config.toml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_config(path: Path) -> Config:
    """Read and validate a TOML configuration file."""
    path = Path(path).expanduser()
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    base_dir = path.parent
    settings = _build_settings(raw.get("settings", {}) or {}, base_dir)
    notify = _build_notify(raw.get("notify", {}) or {})
    targets = _build_targets(raw.get("target", raw.get("targets", [])) or [])

    if not targets:
        raise ConfigError(f"{path} defines no [[target]] entries")
    if not notify.has_any_channel():
        raise ConfigError(
            f"{path}: no notification channel configured. Set notify.ntfy_topic "
            "(recommended), or notify.webhook_url / notify.macos_notification / "
            "notify.stdout."
        )
    for name, target in [(t.name, t) for t in targets]:
        if target.link_pattern == "":
            raise ConfigError(f"target {name!r}: link_pattern must not be empty")

    return Config(settings=settings, notify=notify, targets=targets, path=path)


def _build_settings(raw: dict[str, Any], base_dir: Path) -> Settings:
    state_file = Path(str(raw.get("state_file", "state.json"))).expanduser()
    if not state_file.is_absolute():
        state_file = (base_dir / state_file).resolve()
    return Settings(
        state_file=state_file,
        timeout=_to_float(raw.get("timeout_seconds", 30), "settings.timeout_seconds"),
        retries=_to_int(raw.get("retries", 3), "settings.retries"),
        hash_files=bool(raw.get("hash_files", False)),
        summary_limit=max(
            1, _to_int(raw.get("summary_limit", 12), "settings.summary_limit")
        ),
        notify_on_first_run=bool(raw.get("notify_on_first_run", False)),
        interval_hours=max(
            0.1, _to_float(raw.get("interval_hours", 6), "settings.interval_hours")
        ),
        user_agent=str(raw.get("user_agent", DEFAULT_USER_AGENT)),
    )


def _to_float(value: Any, field_name: str) -> float:
    """Coerce a config value to float, raising a clear ConfigError if not."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must be a number, got {value!r}") from exc


def _to_int(value: Any, field_name: str) -> int:
    """Coerce a config value to int, raising a clear ConfigError if not."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must be an integer, got {value!r}") from exc


def _build_notify(raw: dict[str, Any]) -> NotifyConfig:
    tags = raw.get("tags", ["calendar", "tada"])
    return NotifyConfig(
        ntfy_topic=str(raw.get("ntfy_topic", "")).strip(),
        ntfy_server=str(raw.get("ntfy_server", "https://ntfy.sh")).rstrip("/"),
        ntfy_token=str(raw.get("ntfy_token", "")).strip(),
        priority=str(raw.get("priority", "high")).lower(),
        tags=tuple(str(tag) for tag in tags),
        webhook_url=str(raw.get("webhook_url", "")).strip(),
        macos_notification=bool(raw.get("macos_notification", False)),
        stdout=bool(raw.get("stdout", False)),
        attach_files=bool(raw.get("attach_files", True)),
    )


def _build_targets(raw_targets: list[Any]) -> list[Target]:
    targets: list[Target] = []
    for index, item in enumerate(raw_targets, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"[[target]] #{index} must be a table")
        if "url" not in item:
            raise ConfigError(f"[[target]] #{index} is missing 'url'")
        # Accept both spellings so the config is forgiving.
        programmes = item.get("programmes", item.get("programs", [])) or []
        targets.append(
            Target(
                name=str(item.get("name") or item["url"]),
                url=str(item["url"]),
                link_pattern=str(item.get("link_pattern", DEFAULT_LINK_PATTERN)),
                programmes=tuple(str(p) for p in programmes),
                summary=bool(item.get("summary", True)),
            )
        )
    return targets


# ---------------------------------------------------------------------------
# Template used by ``sdu-exam-watch init``
# ---------------------------------------------------------------------------


def render_default_config(ntfy_topic: str, include_targets: bool = True) -> str:
    """Return a commented starter configuration."""
    targets = ""
    if include_targets:
        targets = f'''
# ── What to watch ──────────────────────────────────────────────────────────
# Each [[target]] is a page whose links are checked for new/changed files.
# The MSc Software Engineering page publishes the Faculty of Engineering
# schedule (PDF + XLSX) once per semester.

[[target]]
name = "MSc Software Engineering (Odense)"
url  = "{MSC_SWE_EXAM_PAGE}"
# Only links matching this regex count as schedule artifacts.
# (Single-quoted TOML literal string, so the backslash is passed through.)
link_pattern = '\\.(xlsx|xls|pdf)([?#]|$)'
# Show *your* exams in the notification, from the XLSX "Udd" column.
programmes = ["{MSC_SOFTWARE_ENGINEERING}"]
summary    = true
'''
    return f'''# sdu-exam-watch configuration
# Docs: see README.md

[settings]
# Where the "have I seen this before?" state is kept (relative to this file).
state_file          = "state.json"
timeout_seconds     = 30
retries             = 3
# Download and hash each file on every check (slower, maximally reliable).
# Leave false to rely on the server's ETag/Last-Modified headers.
hash_files          = false
# How many exams to list in a notification.
summary_limit       = 12
# Send a notification the first time a target is seen (normally silent).
notify_on_first_run = false
# Suggested polling interval for the LaunchAgent/cron.
interval_hours      = 6

[notify]
# ntfy.sh: install the free "ntfy" app from the App Store, then subscribe to
# this exact topic. No account or developer certificate required.
ntfy_topic  = "{ntfy_topic}"
ntfy_server = "https://ntfy.sh"
# Optional: only for a protected or self-hosted ntfy topic.
# ntfy_token = ""
priority    = "high"
tags        = ["calendar", "tada"]
# Attach the actual schedule file (PDF/Excel) to the notification, so the full
# plan is on your phone — not just the summary of your exams below.
attach_files = true
# Optional extra channels (leave empty/false to disable):
# webhook_url        = ""            # Discord/Slack/custom JSON POST
# macos_notification = false         # local macOS banner via osascript
# stdout             = false         # print to the log (handy for testing)
{targets}'''
