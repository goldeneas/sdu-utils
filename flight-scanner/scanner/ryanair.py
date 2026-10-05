"""Client per l'API tariffe di Ryanair (endpoint "farfnd", non documentato).

Per ogni tratta e mese restituisce il prezzo più basso di ogni giorno, in tempo
reale (non da cache). Ryanair prezza per tratta, quindi andata e ritorno si
sommano e si possono combinare anche su aeroporti diversi (open-jaw).

ATTENZIONE: l'API è non ufficiale e può cambiare senza preavviso.
"""
from __future__ import annotations

import time
from datetime import datetime

import requests

from .models import OneWayFare
from .travelpayouts import ApiError

API_URL = "https://services-api.ryanair.com/farfnd/v4/oneWayFares/{o}/{d}/cheapestPerDay"
BOOKING_URL = (
    "https://www.ryanair.com/it/it/trip/flights/select?adults=1&teens=0&children=0&infants=0"
    "&dateOut={date}&isReturn=false&originIata={o}&destinationIata={d}"
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def parse_fares(payload: dict, origin: str, destination: str, currency: str) -> list[OneWayFare]:
    fares = []
    for f in ((payload.get("outbound") or {}).get("fares")) or []:
        if f.get("soldOut") or f.get("unavailable"):
            continue
        price = (f.get("price") or {}).get("value")
        dep = f.get("departureDate")
        if price is None or not dep:
            continue
        try:
            dep_dt = datetime.fromisoformat(dep)
            price = float(price)
        except ValueError:
            continue
        fares.append(
            OneWayFare(
                origin=origin,
                destination=destination,
                departure_at=dep_dt,
                price=round(price, 2),
                airline="FR",
                link=BOOKING_URL.format(date=dep_dt.date().isoformat(), o=origin, d=destination),
                currency=currency.upper(),
            )
        )
    return fares


class RyanairClient:
    def __init__(self, currency: str = "EUR", session=None, retries: int = 3):
        self.currency = currency.upper()
        self.retries = retries
        self.session = session or requests.Session()

    def search_month(self, origin: str, destination: str, month: str) -> list[OneWayFare]:
        """Tariffe più basse per ogni giorno del mese `month` (YYYY-MM) su una tratta."""
        params = {"outboundMonthOfDate": f"{month}-01", "currency": self.currency}
        url = API_URL.format(o=origin, d=destination)
        delay = 2.0
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.session.get(url, params=params, headers={"User-Agent": UA}, timeout=30)
            except requests.RequestException as exc:
                last = exc
            else:
                if r.status_code in (400, 404):
                    return []  # tratta non operata da Ryanair
                if r.status_code == 429 or r.status_code >= 500:
                    last = ApiError(f"HTTP {r.status_code}")
                elif r.status_code != 200:
                    raise ApiError(f"Ryanair HTTP {r.status_code}: {r.text[:200]}")
                else:
                    return parse_fares(r.json(), origin, destination, self.currency)
            if attempt < self.retries - 1:
                time.sleep(delay)
                delay *= 2
        raise ApiError(f"Ryanair {origin}→{destination}: richiesta fallita ({last})")
