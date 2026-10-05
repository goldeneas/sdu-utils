"""Modelli dati per i risultati di ricerca voli."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


def _human_minutes(minutes: int | None) -> str:
    if minutes is None:
        return "n/d"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


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
    def duration_out_human(self) -> str:
        return _human_minutes(self.duration_out)

    @property
    def duration_back_human(self) -> str:
        return _human_minutes(self.duration_back)

    @staticmethod
    def stops_human(n: int) -> str:
        if n == 0:
            return "diretto"
        return f"{n} scalo" if n == 1 else f"{n} scali"

    @property
    def key(self) -> tuple:
        return (self.origin, self.destination, self.departure_at, self.return_at, self.airline)

    @property
    def summary(self) -> str:
        return (
            f"€{self.price:.2f} {self.origin}→{self.destination} "
            f"{self.departure_date.isoformat()} → {self.return_date.isoformat()} "
            f"({self.airline})"
        )
