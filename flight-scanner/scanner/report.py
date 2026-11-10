"""Public scan results and request health, without credentials or provider errors."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import FlightOption


@dataclass
class SourceReport:
    succeeded: int = 0
    failed: int = 0
    aborted: bool = False


@dataclass
class SearchReport:
    sources: dict[str, SourceReport] = field(default_factory=dict)
    per_airport: dict[str, list[FlightOption]] = field(default_factory=dict)
    flights: list[FlightOption] = field(default_factory=list)

