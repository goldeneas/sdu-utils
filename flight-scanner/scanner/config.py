"""Caricamento e validazione della configurazione (config.yaml + .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Carica coppie KEY=VALUE da un file .env (senza dipendenze esterne)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass
class SearchConfig:
    currency: str = "EUR"
    max_price: float = 100.0
    top_n: int = 10
    window_days: int = 30
    min_nights: int = 3
    max_nights: int = 14
    max_transfers: int = 1        # scali massimi per tratta (0 = solo diretti)
    request_delay_seconds: float = 0.5


@dataclass
class AirportsConfig:
    origins: list[str] = field(default_factory=list)
    destinations: list[str] = field(default_factory=list)


@dataclass
class NtfyConfig:
    enabled: bool = True
    server: str = "ntfy.sh"
    topic: str = ""
    notify_new_best: bool = True


@dataclass
class SourcesConfig:
    travelpayouts: bool = True    # A/R da cache Aviasales (serve TRAVELPAYOUTS_TOKEN)
    ryanair: bool = True          # tariffe live Ryanair (tratte singole)
    open_jaw: bool = True         # combina andata/ritorno su aeroporti diversi (Ryanair)


@dataclass
class OutputConfig:
    file: str = ""       # vuoto = solo terminale
    format: str = "csv"  # csv | txt | json


@dataclass
class Config:
    search: SearchConfig = field(default_factory=SearchConfig)
    airports: AirportsConfig = field(default_factory=AirportsConfig)
    ntfy: NtfyConfig = field(default_factory=NtfyConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def _clean_codes(items) -> list[str]:
    return [str(x).strip().upper() for x in (items or []) if str(x).strip()]


def load_config(path: str | os.PathLike = "config.yaml") -> Config:
    _load_env_file(PROJECT_ROOT / ".env")

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File di configurazione non trovato: {p.resolve()}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    s = data.get("search") or {}
    a = data.get("airports") or {}
    n = data.get("ntfy") or {}
    src = data.get("sources") or {}
    o = data.get("output") or {}

    cfg = Config(
        search=SearchConfig(
            currency=str(s.get("currency", "EUR")).upper(),
            max_price=float(s.get("max_price", 100.0)),
            top_n=int(s.get("top_n", 10)),
            window_days=int(s.get("window_days", 30)),
            min_nights=int(s.get("min_nights", 3)),
            max_nights=int(s.get("max_nights", 14)),
            max_transfers=int(s.get("max_transfers", 1)),
            request_delay_seconds=float(s.get("request_delay_seconds", 0.5)),
        ),
        airports=AirportsConfig(
            origins=_clean_codes(a.get("origins")),
            destinations=_clean_codes(a.get("destinations")),
        ),
        ntfy=NtfyConfig(
            enabled=bool(n.get("enabled", True)),
            server=str(n.get("server", "ntfy.sh")),
            topic=str(n.get("topic", "") or ""),
            notify_new_best=bool(n.get("notify_new_best", True)),
        ),
        sources=SourcesConfig(
            travelpayouts=bool(src.get("travelpayouts", True)),
            ryanair=bool(src.get("ryanair", True)),
            open_jaw=bool(src.get("open_jaw", True)),
        ),
        output=OutputConfig(
            file=str(o.get("file", "") or ""),
            format=str(o.get("format", "csv")).lower(),
        ),
    )

    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if not cfg.airports.origins:
        raise ValueError("config: `airports.origins` non può essere vuota")
    if not cfg.airports.destinations:
        raise ValueError("config: `airports.destinations` non può essere vuota")

    s = cfg.search
    if s.max_price <= 0:
        raise ValueError("config: `search.max_price` deve essere > 0")
    if s.top_n <= 0:
        raise ValueError("config: `search.top_n` deve essere > 0")
    if s.window_days <= 0:
        raise ValueError("config: `search.window_days` deve essere > 0")
    if s.min_nights < 1:
        raise ValueError("config: `search.min_nights` deve essere >= 1")
    if s.max_nights < s.min_nights:
        raise ValueError("config: `search.max_nights` non può essere minore di `min_nights`")
    if s.min_nights > s.window_days:
        raise ValueError("config: `search.min_nights` non può superare `window_days`")
    if s.max_transfers < 0:
        raise ValueError("config: `search.max_transfers` non può essere negativo")
    if not (cfg.sources.travelpayouts or cfg.sources.ryanair):
        raise ValueError("config: abilita almeno una fonte in `sources`")
    if cfg.output.format not in ("csv", "txt", "json"):
        raise ValueError("config: `output.format` deve essere csv, txt o json")
