"""Run the scanner for GitHub Pages; preserve previous results after a failed scan."""
from __future__ import annotations

import copy
import gzip
import json
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import Config, load_config
from .models import FlightOption
from .report import SearchReport
from .search import run_search


def flight_data(f: FlightOption) -> dict:
    return {
        "price": f.price,
        "currency": f.currency,
        "origin": f.origin,
        "destination": f.destination,
        "departure_at": f.departure_at.isoformat(timespec="minutes"),
        "arrival_out": f.arrival_out.isoformat(timespec="minutes") if f.arrival_out else "",
        "return_at": f.return_at.isoformat(timespec="minutes"),
        "arrival_back": f.arrival_back.isoformat(timespec="minutes") if f.arrival_back else "",
        "nights": f.nights,
        "return_origin": f.return_origin,
        "return_destination": f.return_destination,
        "open_jaw": f.open_jaw,
        "source": f.source,
        "price_out": f.price_out,
        "price_back": f.price_back,
        "airline": f.airline,
        "out_stops": f.transfers,
        "in_stops": f.return_transfers,
        "out_duration_min": f.duration_out,
        "in_duration_min": f.duration_back,
        "link": f.link,
        "return_link": f.return_link,
    }


def load_previous(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        source = Path(path)
        data = json.loads(gzip.decompress(source.read_bytes()) if source.suffix == ".gz" else source.read_text(encoding="utf-8"))
        if (data.get("schema_version") == 1 and data.get("generated_at")
                and isinstance(data.get("top"), list)
                and isinstance(data.get("per_airport"), dict)
                and isinstance(data.get("search"), dict)):
            datetime.fromisoformat(data["generated_at"])
            return data
    except (OSError, ValueError, TypeError, AttributeError, EOFError):
        pass
    return None


def search_metadata(cfg: Config, today: date) -> dict:
    s = cfg.search
    return {
        "currency": s.currency, "max_price": s.max_price, "top_n": s.top_n,
        "min_nights": s.min_nights, "max_nights": s.max_nights,
        "max_transfers": s.max_transfers, "open_jaw": cfg.sources.open_jaw,
        "departure_from": (today + timedelta(days=1 + s.exclude_next_days)).isoformat(),
        "departure_to": (today + timedelta(days=s.window_days)).isoformat(),
        "origins": cfg.airports.origins, "destinations": cfg.airports.destinations,
    }


def publish(
    cfg: Config, out: Path, previous: dict | None = None, *,
    runner=run_search, now: datetime | None = None,
) -> dict:
    """Publish flight results and health metadata without provider credentials."""
    cfg = copy.deepcopy(cfg)
    skipped = []
    if cfg.sources.travelpayouts and not os.getenv("TRAVELPAYOUTS_TOKEN", "").strip():
        cfg.sources.travelpayouts = False
        skipped.append("travelpayouts")
        print("Travelpayouts skipped: no TRAVELPAYOUTS_TOKEN; using the other sources.")

    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    report = SearchReport()
    error = False
    partial = False
    try:
        if not any((cfg.sources.travelpayouts, cfg.sources.ryanair, cfg.sources.google_flights)):
            raise RuntimeError("No available sources")
        top = runner(cfg, today=now.date(), report=report)
        succeeded = sum(s.succeeded for s in report.sources.values())
        request_failures = any(s.failed or s.aborted for s in report.sources.values())
        partial = bool(skipped) or request_failures
        # Empty responses are valid, but cannot erase good data when some requests failed.
        has_results = bool(report.flights) or bool(top) or any(report.per_airport.values())
        error = not succeeded or (not has_results and request_failures)
    except Exception:
        # Provider exceptions may embed request details: never put them in public JSON.
        print("::warning::Flight scan failed; preserving the last successful snapshot if available.")
        top, error = [], True

    if error and previous:
        data = copy.deepcopy(previous)
        data.update(status="stale", attempted_at=stamp)
    else:
        data = {
            "schema_version": 1,
            "generated_at": None if error else stamp,
            "attempted_at": stamp,
            "status": "unavailable" if error else ("partial" if partial else "ok"),
            "search": search_metadata(cfg, now.date()),
            "sources": {name: asdict(s) for name, s in report.sources.items()},
            "skipped_sources": skipped,
            "flights": [] if error else [flight_data(f) for f in report.flights],
            # Retain these small highlights for already-installed versions of the PWA.
            "top": [] if error else [flight_data(f) for f in top],
            "per_airport": {} if error else {
                a: [flight_data(f) for f in options] for a, options in report.per_airport.items()
            },
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(out)
    if error:
        print(f"::warning::Flight data status: {data['status']}")
    return data


if __name__ == "__main__":
    # Internal entry point for the scheduled Pages job; no interactive CLI.
    publish(
        load_config(),
        Path("data/flights.json"),
        load_previous(os.getenv("PREVIOUS_FLIGHTS_PATH")),
    )
