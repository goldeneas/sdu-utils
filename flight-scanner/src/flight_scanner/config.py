"""TOML configuration for the deal watcher.

See ``config.example.toml`` at the repository root for a fully commented
example. The file has four sections::

    [trip]     what to search for (date windows, airports, time value)
    [deals]    when a result counts as a deal worth alerting about
    [notify]   where to send the alert (ntfy, stdout)
    [rail]     live train/bus lookups (DSB/Rejseplanen, Transitous)
    [watch]    how often to run and where to keep state

Everything has a sensible default except the trip date windows and an ntfy
topic, which must be provided.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED_PRIORITIES = {"min", "low", "default", "high", "max", "1", "2", "3", "4", "5"}
ALLOWED_MODES = {"best", "threshold", "both"}
ALLOWED_RAIL = {"rejseplanen", "transitous", "trainline"}
DEFAULT_TAGS = ("airplane", "moneybag")


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or invalid."""


@dataclass(slots=True)
class TripConfig:
    """Which trips to search for (mirrors ``scan.py`` CLI options)."""

    days: int = 30  # rolling window: always the next N days
    trip_min: int = 5
    trip_max: int = 9
    origins: tuple[str, ...] = ("CPH", "AAR", "BLL")
    time_value: float = 8.0
    overhead: float = 2.5
    ground: str = "min"
    pickup_naples: bool = True


@dataclass(slots=True)
class DealConfig:
    """When a result is a deal worth a phone buzz."""

    mode: str = "both"  # "best" | "threshold" | "both"
    max_total: float = 200.0  # alert threshold in EUR; 0 disables threshold mode
    improve_by: float = 5.0  # only re-alert if cheaper by at least this many EUR
    max_alerts: int = 3
    notify_first_run: bool = True


@dataclass(slots=True)
class NotifyConfig:
    """Where alerts go."""

    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    ntfy_token: str = ""
    priority: str = "high"
    tags: tuple[str, ...] = DEFAULT_TAGS
    click: str = ""
    stdout: bool = False

    def has_any_channel(self) -> bool:
        return bool(self.ntfy_topic or self.stdout)

    def __post_init__(self) -> None:
        if str(self.priority).lower() not in ALLOWED_PRIORITIES:
            raise ConfigError(
                f"notify.priority must be one of {sorted(ALLOWED_PRIORITIES)}"
            )
        self.ntfy_server = self.ntfy_server.rstrip("/")


@dataclass(slots=True)
class RailConfig:
    """Live train/bus lookups added to alerts.

    ``danish`` handles Odense <-> airport via DSB/Rejseplanen (needs a free
    ``rejseplanen_access_id``); ``italian`` handles airport <-> Salerno via the
    open Transitous router (Trainline is captcha-blocked).
    """

    live: bool = False
    danish: str = "rejseplanen"
    italian: str = "transitous"
    rejseplanen_access_id: str = ""
    timezone: str = "Europe/Rome"

    def __post_init__(self) -> None:
        for name, value in (("danish", self.danish), ("italian", self.italian)):
            if value not in ALLOWED_RAIL:
                raise ConfigError(
                    f"rail.{name} must be one of {sorted(ALLOWED_RAIL)}, got {value!r}"
                )


@dataclass(slots=True)
class WatchConfig:
    """The fully-resolved watcher configuration."""

    trip: TripConfig
    deals: DealConfig
    notify: NotifyConfig
    state_file: Path
    interval_hours: float = 6.0
    rail: RailConfig = field(default_factory=RailConfig)
    path: Path | None = None


def default_config_path() -> Path:
    """``./config.toml`` if present, else ``~/.config/flight-scanner/config.toml``."""
    local = Path.cwd() / "config.toml"
    if local.exists():
        return local
    return Path.home() / ".config" / "flight-scanner" / "config.toml"


def load_config(path: Path | str) -> WatchConfig:
    """Read and validate a TOML configuration file."""
    path = Path(path).expanduser()
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    trip = _build_trip(raw.get("trip", {}) or {})
    deals = _build_deals(raw.get("deals", {}) or {})
    notify = _build_notify(raw.get("notify", {}) or {})
    rail = _build_rail(raw.get("rail", {}) or {})
    watch_raw = raw.get("watch", {}) or {}

    state_file = Path(str(watch_raw.get("state_file", "watch-state.json"))).expanduser()
    if not state_file.is_absolute():
        state_file = (path.parent / state_file).resolve()

    if not notify.has_any_channel():
        raise ConfigError(
            f"{path}: no notification channel configured. Set notify.ntfy_topic "
            "(recommended) or notify.stdout = true."
        )

    return WatchConfig(
        trip=trip,
        deals=deals,
        notify=notify,
        state_file=state_file,
        rail=rail,
        interval_hours=max(
            0.1, _to_float(watch_raw.get("interval_hours", 6), "watch.interval_hours")
        ),
        path=path,
    )


def _build_trip(raw: dict[str, Any]) -> TripConfig:
    days = _to_int(raw.get("days", 30), "trip.days")
    if days < 1:
        raise ConfigError("trip.days must be >= 1")

    origins_raw = raw.get("origins", ["CPH", "AAR", "BLL"])
    if isinstance(origins_raw, str):
        origins = tuple(o.strip().upper() for o in origins_raw.split(",") if o.strip())
    else:
        origins = tuple(str(o).strip().upper() for o in origins_raw if str(o).strip())
    if not origins:
        raise ConfigError("trip.origins must list at least one airport")

    ground = str(raw.get("ground", "min")).lower()
    if ground not in {"min", "typ"}:
        raise ConfigError("trip.ground must be 'min' or 'typ'")

    trip_min = _to_int(raw.get("trip_min", 5), "trip.trip_min")
    trip_max = _to_int(raw.get("trip_max", 9), "trip.trip_max")
    if trip_max < trip_min:
        raise ConfigError("trip.trip_max must be >= trip.trip_min")

    return TripConfig(
        days=days,
        trip_min=trip_min,
        trip_max=trip_max,
        origins=origins,
        time_value=_to_float(raw.get("time_value", 8), "trip.time_value"),
        overhead=_to_float(raw.get("overhead", 2.5), "trip.overhead"),
        ground=ground,
        pickup_naples=bool(raw.get("pickup_naples", True)),
    )


def _build_deals(raw: dict[str, Any]) -> DealConfig:
    mode = str(raw.get("mode", "both")).lower()
    if mode not in ALLOWED_MODES:
        raise ConfigError(f"deals.mode must be one of {sorted(ALLOWED_MODES)}")
    max_total = _to_float(raw.get("max_total", 200), "deals.max_total")
    if max_total < 0:
        raise ConfigError("deals.max_total must be >= 0 (0 disables threshold mode)")
    return DealConfig(
        mode=mode,
        max_total=max_total,
        improve_by=max(0.0, _to_float(raw.get("improve_by", 5), "deals.improve_by")),
        max_alerts=max(1, _to_int(raw.get("max_alerts", 3), "deals.max_alerts")),
        notify_first_run=bool(raw.get("notify_first_run", True)),
    )


def _build_rail(raw: dict[str, Any]) -> RailConfig:
    return RailConfig(
        live=bool(raw.get("live", False)),
        danish=str(raw.get("danish", "rejseplanen")).lower(),
        italian=str(raw.get("italian", "transitous")).lower(),
        rejseplanen_access_id=str(raw.get("rejseplanen_access_id", "")).strip(),
        timezone=str(raw.get("timezone", "Europe/Rome")),
    )


def _build_notify(raw: dict[str, Any]) -> NotifyConfig:
    tags_raw = raw.get("tags", list(DEFAULT_TAGS))
    if isinstance(tags_raw, str):
        tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
    else:
        tags = tuple(str(t).strip() for t in tags_raw if str(t).strip())
    return NotifyConfig(
        ntfy_topic=str(raw.get("ntfy_topic", "")).strip(),
        ntfy_server=str(raw.get("ntfy_server", "https://ntfy.sh")),
        ntfy_token=str(raw.get("ntfy_token", "")).strip(),
        priority=str(raw.get("priority", "high")),
        tags=tags or DEFAULT_TAGS,
        click=str(raw.get("click", "")).strip(),
        stdout=bool(raw.get("stdout", False)),
    )


def _to_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number, got {value!r}") from exc


def _to_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc
