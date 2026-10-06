"""Client Google Flights tramite la libreria `fast-flights` (scraping non ufficiale).

Una richiesta = una tratta in un giorno: restituisce TUTTI i voli di quel giorno
(non solo il più economico), con prezzo, orari, scali e compagnia. Il prezzo è per
tratta, quindi andata e ritorno si sommano e si combinano come per Ryanair.

ATTENZIONE: Google può cambiare il formato; in tal caso va aggiornata `fast-flights`
(`pip install -U fast-flights`).
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from .models import OneWayFare
from .travelpayouts import ApiError


URL = "https://www.google.com/travel/flights"
# Cookie di consenso: senza, dall'UE Google risponde con la pagina "Before you continue"
# invece dei risultati (fast-flights non trova i dati e fallisce).
CONSENT_COOKIES = {
    "SOCS": os.getenv("GOOGLE_SOCS", "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmRlIAEaBgiAo_CmBg"),
    "CONSENT": "YES+cb",
}
DEBUG_FILE = Path("debug_dumps") / "google_flights_error.html"


def _explain_bad_page(html: str) -> str:
    low = html.lower()
    if "consent.google" in low or "before you continue" in low or "prima di continuare" in low:
        return "pagina di consenso cookie di Google (nessun risultato)"
    if "unusual traffic" in low or "captcha" in low or "recaptcha" in low:
        return "Google chiede un captcha / traffico insolito"
    return "pagina senza dati voli (formato cambiato o richiesta rifiutata)"


def fetch_html(query) -> str:
    """Scarica la pagina Google Flights con i cookie di consenso già impostati."""
    from primp import Client

    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True)
    with_cookies = getattr(client, "set_cookies", None)
    if with_cookies:
        with_cookies(URL, CONSENT_COOKIES)
    return client.get(URL, params=query.params()).text


def get_flights_with_consent(query):
    from fast_flights.parser import parse

    html = fetch_html(query)
    try:
        return parse(html)
    except Exception as exc:
        # FlightsNotFound è un esito normale: lo lasciamo passare
        from fast_flights.exceptions import FlightsNotFound
        if isinstance(exc, FlightsNotFound):
            raise
        DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_FILE.write_text(html, encoding="utf-8")
        raise ApiError(f"{_explain_bad_page(html)} · HTML salvato in {DEBUG_FILE}") from exc


def _to_dt(sd) -> datetime:
    y, m, d = sd.date
    hh, mm = sd.time
    return datetime(y, m, d, hh, mm)


def parse_flights(results, origin: str, destination: str, link: str, currency: str) -> list[OneWayFare]:
    """Converte i risultati di fast-flights in OneWayFare."""
    fares = []
    for fl in results:
        if not fl.flights or not fl.price:
            continue
        first, last = fl.flights[0], fl.flights[-1]
        if first.from_airport.code != origin or last.to_airport.code != destination:
            continue  # Google può proporre aeroporti vicini: ignora
        fares.append(
            OneWayFare(
                origin=origin,
                destination=destination,
                departure_at=_to_dt(first.departure),
                arrival_at=_to_dt(last.arrival),
                price=float(fl.price),
                airline=" + ".join(dict.fromkeys(fl.airlines)) or "n/d",
                link=link,
                currency=currency.upper(),
                source="google",
                transfers=len(fl.flights) - 1,
                duration=sum(f.duration for f in fl.flights) or None,
            )
        )
    return fares


class GoogleFlightsClient:
    def __init__(self, currency: str = "EUR", airlines: list[str] | None = None,
                 max_stops: int | None = None, getter=None):
        self.currency = currency.upper()
        self.airlines = airlines or None
        self.max_stops = max_stops
        self._getter = getter

    def _fetch(self, query):
        if self._getter is not None:
            return self._getter(query)
        return get_flights_with_consent(query)

    def search_day(self, origin: str, destination: str, day: date) -> list[OneWayFare]:
        """Tutti i voli diretti/con scali di una tratta in un giorno."""
        try:
            from fast_flights import FlightQuery, create_query
            from fast_flights.exceptions import FlightsNotFound
        except ImportError as exc:
            raise ApiError("manca la libreria: pip install fast-flights") from exc

        query = create_query(
            flights=[FlightQuery(
                date=day.isoformat(), from_airport=origin, to_airport=destination,
                airlines=self.airlines,
            )],
            seat="economy", trip="one-way", language="en-US", currency=self.currency,
            max_stops=self.max_stops,
        )
        try:
            results = self._fetch(query)
        except FlightsNotFound:
            return []
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001 - rete, blocco, formato cambiato
            raise ApiError(f"Google Flights {origin}→{destination} {day}: {exc}") from exc
        return parse_flights(results, origin, destination, query.url(), self.currency)
