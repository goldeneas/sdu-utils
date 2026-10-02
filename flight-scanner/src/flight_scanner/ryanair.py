"""
Ryanair public price feed (no API key required).

Endpoints used:
  * Route discovery (cheapest fare per reachable destination):
      https://services-api.ryanair.com/farfnd/v4/oneWayFares
        ?departureAirportIataCode=CPH
        &outboundDepartureDateFrom=YYYY-MM-DD
        &outboundDepartureDateTo=YYYY-MM-DD
        &currency=EUR&limit=2000
  * Cheapest fare per calendar day for one route:
      https://services-api.ryanair.com/farfnd/v4/oneWayFares/{ORIG}/{DEST}/cheapestPerDay
        ?outboundMonthOfDate=YYYY-MM-01&currency=EUR

These are the public "Fare Finder" endpoints the Ryanair website itself calls.
Prices are per adult, one-way, taxes included, no bags/seat.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

BASE = "https://services-api.ryanair.com/farfnd/v4"
_IATA_RE = re.compile(r"^[A-Z]{3}$")


def _check_iata(*codes: str) -> None:
    """Reject anything that is not a bare 3-letter IATA code.

    This keeps user input from injecting path/query segments into the
    hard-coded https endpoints (defence against SSRF / path traversal).
    """
    for code in codes:
        if not _IATA_RE.match(code):
            raise ValueError(f"invalid IATA code: {code!r}")


def _default_cache_dir() -> Path:
    """Repo-root ``cache/`` when run from a source checkout, else ``~/.cache``."""
    override = os.environ.get("FLIGHT_SCANNER_CACHE")
    if override:
        return Path(override).expanduser()
    here = Path(__file__).resolve()
    # src/flight_scanner/ryanair.py -> parents[2] is the repository root
    if here.parents[1].name == "src":
        return here.parents[2] / "cache"
    return Path.home() / ".cache" / "flight-scanner"


CACHE_DIR = _default_cache_dir()
CACHE_TTL_SECONDS = 6 * 3600  # 6h
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class Fare:
    origin: str
    dest: str
    day: str  # YYYY-MM-DD
    price: float  # EUR, per adult one-way
    depart_time: str  # HH:MM or ""
    arrive_time: str  # HH:MM or ""
    flight_no: str = ""


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    return CACHE_DIR / f"{digest}.json"


def _get(url: str, use_cache: bool = True, timeout: int = 25) -> Any:
    CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path(url)
    if use_cache and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                path.unlink(missing_ok=True)

    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https URL: {url}")

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )  # noqa: S310  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
            path.write_text(json.dumps(data))
            return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_err = err
            time.sleep(0.6 * (attempt + 1))
    # Fall back to a stale cache entry if the network is unavailable.
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    raise RuntimeError(f"request failed: {url} ({last_err})")


def months_between(start: date, end: date) -> list[str]:
    """List of YYYY-MM-01 strings covering [start, end]."""
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def discover_destinations(
    origin: str, start: date, end: date, use_cache: bool = True
) -> dict[str, str]:
    """Return {dest_iata: country_code} reachable from origin in the window."""
    _check_iata(origin)
    url = (
        f"{BASE}/oneWayFares?departureAirportIataCode={origin}"
        f"&outboundDepartureDateFrom={start.isoformat()}"
        f"&outboundDepartureDateTo={end.isoformat()}"
        f"&currency=EUR&limit=2000"
    )
    data = _get(url, use_cache)
    out: dict[str, str] = {}
    for fare in data.get("fares", []) or []:
        arr = fare.get("outbound", {}).get("arrivalAirport", {})
        code = arr.get("iataCode")
        if code:
            out[code] = (arr.get("countryCode") or "").lower()
    return out


def cheapest_per_day(
    origin: str, dest: str, month: str, use_cache: bool = True
) -> list[Fare]:
    """Cheapest one-way fare per day for a route in one month (YYYY-MM-01)."""
    _check_iata(origin, dest)
    url = (
        f"{BASE}/oneWayFares/{origin}/{dest}/cheapestPerDay"
        f"?outboundMonthOfDate={month}&currency=EUR"
    )
    data = _get(url, use_cache)
    fares: list[Fare] = []
    for row in data.get("outbound", {}).get("fares", []) or []:
        price = row.get("price")
        if not price or row.get("soldOut") or row.get("unavailable"):
            continue
        dep = row.get("departureDate") or ""
        arr = row.get("arrivalDate") or ""
        try:
            value = float(price["value"])
        except (KeyError, TypeError, ValueError):
            continue
        fares.append(
            Fare(
                origin=origin,
                dest=dest,
                day=row.get("day", ""),
                price=value,
                depart_time=dep[11:16],
                arrive_time=arr[11:16],
            )
        )
    return fares


def cheapest_over_window(
    origin: str,
    dest: str,
    start: date,
    end: date,
    use_cache: bool = True,
) -> list[Fare]:
    """All per-day fares for a route within [start, end] (inclusive)."""
    out: list[Fare] = []
    for month in months_between(start, end):
        for fare in cheapest_per_day(origin, dest, month, use_cache):
            d = date.fromisoformat(fare.day)
            if start <= d <= end:
                out.append(fare)
    out.sort(key=lambda f: f.price)
    return out


def fare_for_day(
    origin: str, dest: str, day: str, use_cache: bool = True
) -> Fare | None:
    """Cheapest fare for one exact day, including the flight number.

    ``cheapestPerDay`` (used for the wide scan) omits the flight number, so we
    make a targeted single-day ``oneWayFares`` call — only for the handful of
    legs we actually display — to recover e.g. ``FR406``.
    """
    _check_iata(origin, dest)
    date.fromisoformat(day)  # validate YYYY-MM-DD before it hits the URL
    url = (
        f"{BASE}/oneWayFares?departureAirportIataCode={origin}"
        f"&arrivalAirportIataCode={dest}"
        f"&outboundDepartureDateFrom={day}&outboundDepartureDateTo={day}"
        f"&currency=EUR"
    )
    data = _get(url, use_cache)
    fares = data.get("fares") or []
    if not fares:
        return None
    outbound = fares[0].get("outbound", {})
    price = (outbound.get("price") or {}).get("value")
    if price is None:
        return None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    dep = outbound.get("departureDate") or ""
    arr = outbound.get("arrivalDate") or ""
    return Fare(
        origin=origin,
        dest=dest,
        day=dep[:10] or day,
        price=value,
        depart_time=dep[11:16],
        arrive_time=arr[11:16],
        flight_no=str(outbound.get("flightNumber") or ""),
    )


if __name__ == "__main__":  # tiny manual smoke test
    from datetime import date as d

    print(discover_destinations("CPH", d(2026, 10, 2), d(2027, 3, 31)))
    for f in cheapest_per_day("CPH", "FCO", "2026-12-01")[:5]:
        print(f)
