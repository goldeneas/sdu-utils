"""Client Google Flights tramite la libreria `fast-flights` (scraping non ufficiale).

Una richiesta = una tratta in un giorno: restituisce TUTTI i voli di quel giorno
(non solo il più economico), con prezzo, orari, scali e compagnia. Il prezzo è per
tratta, quindi andata e ritorno si sommano e si combinano come per Ryanair.

ATTENZIONE: Google può cambiare il formato; in tal caso va aggiornata `fast-flights`
(`pip install -U fast-flights`).
"""
from __future__ import annotations

from datetime import date, datetime

from .models import OneWayFare
from .travelpayouts import ApiError


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
        try:
            from fast_flights import get_flights
        except ImportError as exc:
            raise ApiError("manca la libreria: pip install fast-flights") from exc
        return get_flights(query)

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
