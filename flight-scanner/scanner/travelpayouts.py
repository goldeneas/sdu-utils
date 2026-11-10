"""Client per la Travelpayouts / Aviasales Data API (prices_for_dates).

Un'unica chiamata per rotta e mese restituisce molte combinazioni
andata/ritorno già con prezzo totale: nessuno scraping, poche richieste.
I prezzi provengono dalla cache di Aviasales (ricerche recenti degli utenti),
quindi sono indicativi: vanno verificati al momento della prenotazione.

Docs: https://support.travelpayouts.com/hc/en-us/articles/203956163
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import requests

from .models import FlightOption

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
BOOKING_BASE = "https://www.aviasales.com"


class ApiError(RuntimeError):
    """Errore non recuperabile dell'API (token errato, quota, ecc.)."""


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # data/ora locali dell'aeroporto: scarta l'offset
    return dt.replace(tzinfo=None)


def parse_offer(item: dict, origin: str, destination: str, currency: str) -> FlightOption | None:
    """Converte un elemento della risposta in FlightOption (None se incompleto)."""
    dep = _parse_dt(item.get("departure_at", ""))
    ret = _parse_dt(item.get("return_at", ""))
    price = item.get("price")
    if dep is None or ret is None or price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    # L'API non dà l'ora di arrivo: partenza + durata, nel fuso dell'aeroporto di
    # partenza (corretto per rotte tra paesi con lo stesso fuso, es. Danimarca-Italia).
    def _arrival(start, minutes):
        return start + timedelta(minutes=minutes) if isinstance(minutes, (int, float)) else None

    link = item.get("link") or ""
    if link.startswith("/"):
        link = BOOKING_BASE + link
    return FlightOption(
        origin=item.get("origin_airport") or item.get("origin") or origin,
        destination=item.get("destination_airport") or item.get("destination") or destination,
        departure_at=dep,
        return_at=ret,
        price=round(price, 2),
        airline=item.get("airline") or "n/d",
        transfers=int(item.get("transfers") or 0),
        return_transfers=int(item.get("return_transfers") or 0),
        duration_out=item.get("duration_to"),
        duration_back=item.get("duration_back"),
        link=link,
        currency=currency.upper(),
        arrival_out=_arrival(dep, item.get("duration_to")),
        arrival_back=_arrival(ret, item.get("duration_back")),
    )


class TravelpayoutsClient:
    def __init__(self, token: str, currency: str = "EUR", session=None, retries: int = 3):
        if not token:
            raise ApiError("Token Travelpayouts mancante (TRAVELPAYOUTS_TOKEN)")
        self.token = token
        self.currency = currency
        self.retries = retries
        self.session = session or requests.Session()

    def search_month(self, origin: str, destination: str, month: str) -> list[FlightOption]:
        """Tutte le offerte A/R con partenza nel mese `month` (formato YYYY-MM)."""
        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": month,
            "one_way": "false",
            "unique": "false",
            "sorting": "price",
            "direct": "false",
            "currency": self.currency.lower(),
            "limit": 1000,
            "page": 1,
        }
        headers = {"X-Access-Token": self.token, "Accept-Encoding": "gzip, deflate"}
        payload = self._get(params, headers)
        offers = []
        for item in payload.get("data") or []:
            o = parse_offer(item, origin, destination, self.currency)
            if o:
                offers.append(o)
        return offers

    def _get(self, params: dict, headers: dict) -> dict:
        delay = 2.0
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.session.get(API_URL, params=params, headers=headers, timeout=30)
            except requests.RequestException as exc:
                last = exc
            else:
                if r.status_code in (401, 403):
                    raise ApiError("Token Travelpayouts non valido o non autorizzato")
                if r.status_code == 429 or r.status_code >= 500:
                    last = ApiError(f"HTTP {r.status_code}")
                elif r.status_code != 200:
                    raise ApiError(f"HTTP {r.status_code}: {r.text[:200]}")
                else:
                    data = r.json()
                    if data.get("success") is False:
                        raise ApiError(f"API: {data.get('error') or data}")
                    return data
            if attempt < self.retries - 1:
                time.sleep(delay)
                delay *= 2
        raise ApiError(f"Richiesta fallita dopo {self.retries} tentativi: {last}")
