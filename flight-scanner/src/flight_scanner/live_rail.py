"""Live rail/bus lookups for the ground legs (real services, real times).

The static model in :mod:`ground` is fine for *ranking* (it is fast and works
offline), but when we show or alert a specific trip we can replace its estimated
ground hops with actual dated services. This module provides that.

Providers
---------
``rejseplanen``
    DSB's journey planner (also covers Danish buses/metro). Official HAFAS API.
    **Requires a free ``accessId``** — register at
    https://labs.rejseplanen.dk/ and set ``rejseplanen_access_id`` in config.
``transitous``
    Open community MOTIS router (https://transitous.org), no key. Works for
    Italian legs and returns real train numbers (e.g. ``FR 9607``, ``IC 551``).
    This is the working stand-in for Trainline.
``trainline``
    Trainline's website API. It is protected by a DataDome captcha and returns
    HTTP 403 to non-browser clients, so it raises :class:`ProviderBlocked`.
    Kept only so a future first-party/partner key can slot in.

Everything is cached on disk for a few hours and degrades to the static model
when a provider is unavailable.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

CACHE_TTL_SECONDS = 3 * 3600
USER_AGENT = "flight-scanner/1.0 (personal travel planner)"


class ProviderUnavailable(RuntimeError):
    """The provider could not be reached or returned an unusable response."""


class ProviderBlocked(ProviderUnavailable):
    """The provider actively refused automated access (captcha / WAF)."""


@dataclass(frozen=True)
class RailLeg:
    """One dated transit leg, with the service number you book."""

    provider: str
    mode: str  # HIGHSPEED_RAIL, REGIONAL_RAIL, BUS, FERRY, ...
    line: str  # e.g. "FR 9607", "IC 551", "925X"
    operator: str
    depart_station: str
    arrive_station: str
    depart: str  # ISO 8601 with offset
    arrive: str
    duration_min: int

    def summary(self) -> str:
        kind = "bus" if "BUS" in self.mode else "train"
        when = f"{self.depart[11:16]}-{self.arrive[11:16]}"
        who = f"{self.operator} " if self.operator else ""
        return (
            f"{self.depart_station} -> {self.arrive_station} · "
            f"{who}{self.line} {kind} ({when}, {self.duration_min} min)"
        )


class RailProvider(Protocol):
    """Anything that can answer 'how do I get from A to B at time T'."""

    name: str

    def connections(
        self,
        origin: str,
        destination: str,
        when: datetime,
        *,
        arrive_by: bool = False,
        limit: int = 3,
    ) -> list[RailLeg]:
        """Return the transit legs of the best connection(s)."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# HTTP helpers (stdlib only)
# --------------------------------------------------------------------------- #
def _cache_dir() -> Path:
    override = os.environ.get("FLIGHT_SCANNER_CACHE")
    if override:
        return Path(override).expanduser() / "rail"
    here = Path(__file__).resolve()
    if here.parents[1].name == "src":
        return here.parents[2] / "cache" / "rail"
    return Path.home() / ".cache" / "flight-scanner" / "rail"


def _cache_key(url: str) -> Path:
    return _cache_dir() / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")


def _request_json(
    url: str,
    *,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    use_cache: bool = True,
) -> Any:
    if not url.startswith("https://"):
        raise ProviderUnavailable(f"refusing non-https URL: {url}")
    _cache_dir().mkdir(parents=True, exist_ok=True)
    cache_path = _cache_key(url)
    if (
        use_cache
        and payload is None
        and cache_path.exists()
        and time.time() - cache_path.stat().st_mtime < CACHE_TTL_SECONDS
    ):
        try:
            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            cache_path.unlink(missing_ok=True)

    body = json.dumps(payload).encode() if payload is not None else None
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if body is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)

    last_err: Exception | None = None
    for attempt in range(2):
        req = urllib.request.Request(
            url, data=body, headers=req_headers, method="POST" if body else "GET"
        )  # noqa: S310  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
            if payload is None:
                cache_path.write_text(json.dumps(data))
            return data
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                raise ProviderBlocked(
                    f"{url} rejected the request with HTTP {err.code}"
                ) from err
            last_err = err
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_err = err
        time.sleep(0.6 * (attempt + 1))
    raise ProviderUnavailable(f"request failed: {url} ({last_err})")


# --------------------------------------------------------------------------- #
# transitous (open, no key) -- the working Italian source
# --------------------------------------------------------------------------- #
class TransitousProvider:
    """MOTIS router run by the Transitous community project."""

    name = "transitous"
    BASE = "https://api.transitous.org/api/v1"

    def __init__(self, tz: str = "Europe/Rome") -> None:
        self.tz = ZoneInfo(tz)

    def _geocode(self, text: str) -> tuple[float, float] | None:
        url = f"{self.BASE}/geocode?" + urllib.parse.urlencode(
            {"text": text, "type": "STOP"}
        )
        results = _request_json(url)
        if isinstance(results, list) and results:
            first = results[0]
            try:
                return float(first["lat"]), float(first["lon"])
            except (KeyError, TypeError, ValueError):
                return None
        return None

    def connections(
        self,
        origin: str,
        destination: str,
        when: datetime,
        *,
        arrive_by: bool = False,
        limit: int = 3,
    ) -> list[RailLeg]:
        start = self._geocode(origin)
        end = self._geocode(destination)
        if start is None or end is None:
            raise ProviderUnavailable(f"could not geocode {origin!r} / {destination!r}")
        params = {
            "fromPlace": f"{start[0]},{start[1]}",
            "toPlace": f"{end[0]},{end[1]}",
            "time": when.astimezone(self.tz).isoformat(),
            "numItineraries": str(limit),
            "searchWindow": "3600",
        }
        if arrive_by:
            params["arriveBy"] = "true"
        data = _request_json(f"{self.BASE}/plan?" + urllib.parse.urlencode(params))
        itineraries = data.get("itineraries") if isinstance(data, dict) else None
        if not itineraries:
            return []
        return [leg for leg in _transitous_legs(itineraries[0], self.name) if leg]


def _transitous_legs(itinerary: dict, provider: str) -> list[RailLeg]:
    out: list[RailLeg] = []
    for leg in itinerary.get("legs", []):
        mode = str(leg.get("mode") or "")
        if mode.upper() == "WALK":
            continue
        start = leg.get("startTime") or ""
        end = leg.get("endTime") or ""
        duration = _minutes_between(start, end)
        out.append(
            RailLeg(
                provider=provider,
                mode=mode,
                line=str(
                    leg.get("routeShortName")
                    or leg.get("routeLongName")
                    or leg.get("tripShortName")
                    or ""
                ),
                operator=str(leg.get("agencyName") or ""),
                depart_station=str(leg.get("from", {}).get("name") or ""),
                arrive_station=str(leg.get("to", {}).get("name") or ""),
                depart=start,
                arrive=end,
                duration_min=duration,
            )
        )
    return out


def _minutes_between(start: str, end: str) -> int:
    try:
        a = datetime.fromisoformat(start)
        b = datetime.fromisoformat(end)
    except ValueError:
        return 0
    return max(0, round((b - a).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# rejseplanen (DSB + Danish buses) -- needs a free accessId
# --------------------------------------------------------------------------- #
class RejseplanenProvider:
    """DSB's Rejseplanen journey planner (HAFAS).

    Register for a free ``accessId`` at https://labs.rejseplanen.dk/ and put it
    in the config as ``rejseplanen_access_id``.
    """

    name = "rejseplanen"
    BASE = "https://www.rejseplanen.dk/api"

    def __init__(self, access_id: str) -> None:
        if not access_id:
            raise ProviderUnavailable(
                "rejseplanen needs access_id (free: https://labs.rejseplanen.dk/)"
            )
        self.access_id = access_id
        self.tz = ZoneInfo("Europe/Copenhagen")

    def _stop_id(self, name: str) -> str | None:
        url = f"{self.BASE}/location.name?" + urllib.parse.urlencode(
            {"input": name, "format": "json", "accessId": self.access_id}
        )
        data = _request_json(url)
        stops = (data or {}).get("LocationList", {}).get("StopLocation") or []
        if isinstance(stops, dict):
            stops = [stops]
        return stops[0].get("id") if stops else None

    def connections(
        self,
        origin: str,
        destination: str,
        when: datetime,
        *,
        arrive_by: bool = False,
        limit: int = 3,
    ) -> list[RailLeg]:
        origin_id = self._stop_id(origin)
        dest_id = self._stop_id(destination)
        if not origin_id or not dest_id:
            raise ProviderUnavailable(f"could not resolve {origin!r} / {destination!r}")
        local = when.astimezone(self.tz)
        params = {
            "originId": origin_id,
            "destId": dest_id,
            "date": local.strftime("%d.%m.%y"),
            "time": local.strftime("%H:%M"),
            "format": "json",
            "accessId": self.access_id,
        }
        if arrive_by:
            params["searchForArrival"] = "1"
        data = _request_json(f"{self.BASE}/trip?" + urllib.parse.urlencode(params))
        trips = (data or {}).get("TripList", {}).get("Trip") or []
        if isinstance(trips, dict):
            trips = [trips]
        if not trips:
            return []
        return _hafas_legs(trips[0], self.name)[:limit]


def _hafas_legs(trip: dict, provider: str) -> list[RailLeg]:
    out: list[RailLeg] = []
    for leg in trip.get("LegList", {}).get("Leg", []):
        product = leg.get("Product") or {}
        line = " ".join(
            p
            for p in (product.get("catOut") or product.get("name"), product.get("num"))
            if p
        )
        out.append(
            RailLeg(
                provider=provider,
                mode=str(product.get("catOut") or product.get("name") or "TRAIN"),
                line=line,
                operator=str(product.get("operator") or "DSB"),
                depart_station=str(leg.get("Origin", {}).get("name") or ""),
                arrive_station=str(leg.get("Destination", {}).get("name") or ""),
                depart=f"{leg.get('depDate', '')}T{leg.get('depTime', '')}",
                arrive=f"{leg.get('arrDate', '')}T{leg.get('arrTime', '')}",
                duration_min=_minutes_between(
                    f"{leg.get('depDate', '')}T{leg.get('depTime', '')}",
                    f"{leg.get('arrDate', '')}T{leg.get('arrTime', '')}",
                ),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# trainline -- blocked by DataDome captcha
# --------------------------------------------------------------------------- #
class TrainlineProvider:
    """Trainline's website API. Blocked by a DataDome captcha for bots."""

    name = "trainline"
    URL = "https://www.thetrainline.com/api/journey-search/"

    def connections(
        self,
        origin: str,
        destination: str,
        when: datetime,
        *,
        arrive_by: bool = False,
        limit: int = 3,
    ) -> list[RailLeg]:
        raise ProviderBlocked(
            "Trainline returned a DataDome captcha (HTTP 403) for non-browser "
            "clients. Use provider 'transitous' for Italian trains instead."
        )


# --------------------------------------------------------------------------- #
# factory
# --------------------------------------------------------------------------- #
def build_provider(name: str, *, rejseplanen_access_id: str = "") -> RailProvider:
    """Instantiate a provider by name (``auto`` picks a working one)."""
    key = (name or "auto").strip().lower()
    if key == "auto":
        key = "rejseplanen" if rejseplanen_access_id else "transitous"
    if key == "transitous":
        return TransitousProvider()
    if key == "rejseplanen":
        return RejseplanenProvider(rejseplanen_access_id)
    if key == "trainline":
        return TrainlineProvider()
    raise ProviderUnavailable(f"unknown rail provider: {name!r}")


# --------------------------------------------------------------------------- #
# map a flight leg to its two ground hops
# --------------------------------------------------------------------------- #
ODENSE = "Odense St"
SALERNO = "Salerno"
DK_STATION: dict[str, str] = {
    "CPH": "Koebenhavns Lufthavn",
    "BLL": "Billund Lufthavn",
    "AAR": "Aarhus Lufthavn",
    "MMX": "Malmo Airport",
    "HAM": "Hamburg Airport",
    "OSL": "Oslo Lufthavn",
}
IT_STATION: dict[str, str] = {
    "QSR": "Salerno Costa d'Amalfi Airport",
    "NAP": "Napoli Capodichino",
    "FCO": "Fiumicino Aeroporto",
    "CIA": "Ciampino",
    "BLQ": "Bologna Aeroporto",
    "PSA": "Pisa Aeroporto",
    "VCE": "Venezia Aeroporto",
    "TSF": "Treviso Aeroporto",
    "BGY": "Bergamo Aeroporto",
    "MXP": "Malpensa Aeroporto",
    "LIN": "Linate",
    "TRN": "Torino Aeroporto",
    "BRI": "Bari Aeroporto",
    "SUF": "Lamezia Aeroporto",
    "OLB": "Olbia",
}


def live_ground_for_leg(
    leg: Any,
    danish: RailProvider | None,
    italian: RailProvider | None,
    *,
    tz: str = "Europe/Rome",
    buffer_min: int = 45,
    pickup: bool = False,
) -> dict[str, list[RailLeg]]:
    """Fetch real connections for a displayed trip leg's two ground hops.

    ``danish`` handles Odense <-> Danish airport (DSB/Rejseplanen); ``italian``
    handles Italian airport <-> Salerno (Transitous). ``before_flight`` is the
    hop to the airport, ``after_flight`` the hop after landing; which country
    each refers to depends on the leg direction. Missing data or provider
    errors yield empty lists (the caller falls back to the static model).
    """
    zone = ZoneInfo(tz)
    dk = DK_STATION.get(leg.fly_from) or DK_STATION.get(leg.fly_to)
    it_code = leg.fly_to if leg.fly_to in IT_STATION else leg.fly_from
    it = IT_STATION.get(it_code)
    result: dict[str, list[RailLeg]] = {"before_flight": [], "after_flight": []}
    if dk is None or it is None:
        return result

    day = str(leg.day)
    try:
        dep = datetime.fromisoformat(f"{day}T{leg.depart or '00:00'}:00").replace(
            tzinfo=zone
        )
        arr = datetime.fromisoformat(f"{day}T{leg.arrive or '00:00'}:00").replace(
            tzinfo=zone
        )
    except ValueError:
        return result
    if arr < dep:  # crosses midnight
        arr = arr + timedelta(days=1)

    use_italian = None if (pickup and it_code == "NAP") else italian
    if leg.kind == "back":
        before = (SALERNO, it, use_italian)
        after = (dk, ODENSE, danish)
    else:
        before = (ODENSE, dk, danish)
        after = (it, SALERNO, use_italian)

    before_origin, before_dest, before_provider = before
    after_origin, after_dest, after_provider = after
    if before_provider is not None:
        with contextlib.suppress(ProviderUnavailable):
            result["before_flight"] = before_provider.connections(
                before_origin,
                before_dest,
                dep - timedelta(minutes=buffer_min),
                arrive_by=True,
            )
    if after_provider is not None:
        with contextlib.suppress(ProviderUnavailable):
            result["after_flight"] = after_provider.connections(
                after_origin, after_dest, arr + timedelta(minutes=buffer_min)
            )
    return result


def live_ground_lines(
    leg: Any,
    danish: RailProvider | None,
    italian: RailProvider | None,
    *,
    tz: str = "Europe/Rome",
    indent: str = "       ",
    pickup: bool = False,
) -> list[str]:
    """Human lines for a leg's live ground hops (empty if none found)."""
    groups = live_ground_for_leg(leg, danish, italian, tz=tz, pickup=pickup)
    lines: list[str] = []
    for rleg in groups["before_flight"]:
        lines.append(f"{indent}{rleg.summary()}")
    for rleg in groups["after_flight"]:
        lines.append(f"{indent}{rleg.summary()}")
    return lines


__all__ = [
    "DK_STATION",
    "IT_STATION",
    "ODENSE",
    "SALERNO",
    "ProviderBlocked",
    "ProviderUnavailable",
    "RailLeg",
    "RailProvider",
    "RejseplanenProvider",
    "TrainlineProvider",
    "TransitousProvider",
    "build_provider",
    "live_ground_for_leg",
    "live_ground_lines",
]
