"""Modelli dati per i risultati di ricerca voli."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Segment:
    """Una tratta (andata o ritorno) di un'offerta di volo."""

    origin: str
    destination: str
    departure_time: str          # "08:40" (formato 24h)
    arrival_time: str            # "10:20" (formato 24h)
    airline: str
    stops: int = 0
    layover_minutes: int | None = None   # None = non rilevato dal DOM
    duration_minutes: int | None = None

    @property
    def duration_human(self) -> str:
        if self.duration_minutes is None:
            return "n/d"
        h, m = divmod(self.duration_minutes, 60)
        return f"{h}h {m:02d}m" if h else f"{m}m"

    @property
    def stops_human(self) -> str:
        if self.stops == 0:
            return "nonstop"
        base = f"{self.stops} scalo" if self.stops == 1 else f"{self.stops} scali"
        if self.layover_minutes:
            h, m = divmod(self.layover_minutes, 60)
            base += f" ({h}h {m:02d}m)" if h else f" ({m}m)"
        return base


@dataclass
class OneWayOffer:
    """Un volo one-way con il relativo prezzo."""

    segment: Segment
    price: float
    currency: str = "EUR"


@dataclass
class FlightOption:
    """Un'offerta andata+ritorno completa."""

    origin: str
    destination: str
    departure_date: date
    return_date: date
    outbound: Segment
    inbound: Segment
    price: float
    currency: str = "EUR"

    @property
    def summary(self) -> str:
        return (
            f"€{self.price:.2f} {self.origin}→{self.destination} "
            f"{self.departure_date.isoformat()} → {self.return_date.isoformat()} "
            f"({self.outbound.airline})"
        )
