"""Modelli dati per i risultati di ricerca voli."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class OneWayFare:
    """Una singola tratta con il suo prezzo."""

    origin: str
    destination: str
    departure_at: datetime
    price: float
    airline: str = "n/d"
    link: str = ""
    currency: str = "EUR"
    arrival_at: datetime | None = None   # ora locale di arrivo
    source: str = "ryanair"
    transfers: int = 0
    duration: int | None = None          # minuti


@dataclass
class FlightOption:
    """Un'offerta andata+ritorno (prezzo totale per 1 persona)."""

    origin: str
    destination: str
    departure_at: datetime
    return_at: datetime
    price: float
    airline: str = "n/d"
    transfers: int = 0           # scali all'andata
    return_transfers: int = 0    # scali al ritorno
    duration_out: int | None = None   # minuti
    duration_back: int | None = None  # minuti
    link: str = ""
    currency: str = "EUR"
    source: str = "travelpayouts"
    return_origin: str = ""        # aeroporto di partenza del ritorno (default: destinazione)
    return_destination: str = ""   # aeroporto di arrivo del ritorno (default: origine)
    return_link: str = ""
    price_out: float | None = None    # prezzo della sola andata (se noto)
    price_back: float | None = None   # prezzo del solo ritorno (se noto)
    arrival_out: datetime | None = None    # ora locale di arrivo dell'andata
    arrival_back: datetime | None = None   # ora locale di arrivo del ritorno

    def __post_init__(self):
        self.return_origin = self.return_origin or self.destination
        self.return_destination = self.return_destination or self.origin

    @property
    def open_jaw(self) -> bool:
        return (self.return_origin, self.return_destination) != (self.destination, self.origin)

    @property
    def departure_date(self) -> date:
        return self.departure_at.date()

    @property
    def return_date(self) -> date:
        return self.return_at.date()

    @property
    def nights(self) -> int:
        return (self.return_date - self.departure_date).days

    @property
    def key(self) -> tuple:
        return (
            self.origin, self.destination, self.return_origin, self.return_destination,
            self.departure_at, self.return_at,
        )
