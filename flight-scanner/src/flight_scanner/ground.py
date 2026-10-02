"""
Ground-transport model for the Odense (DK) <-> Salerno (IT) corridor.

Two independent problems:
  1. ODENSE -> DEPARTURE AIRPORT   (train / bus, DKK, converted to EUR)
  2. ARRIVAL AIRPORT -> SALERNO    (train / bus, EUR)

Everything here is a *planning estimate* (min = advance/online fare,
typ = walk-up / realistic), because train and bus prices are dynamic.
Each row carries the route + a source to verify. Flight prices come from
the live Ryanair feed in ryanair.py; these are the fixed-ish legs.

FX: 1 EUR ~= 7.46 DKK (fixed planning rate, see FX_DKK).
"""

from __future__ import annotations

from dataclasses import dataclass

FX_DKK = 7.46  # DKK per EUR, planning rate


@dataclass(frozen=True)
class Leg:
    """A ground transfer option: cost in EUR, duration in hours."""

    cost_min: float
    cost_typ: float
    hours: float
    mode: str
    detail: str


# ---------------------------------------------------------------------------
# 1. Odense -> departure airports (Denmark + nearby Germany/Sweden)
# ---------------------------------------------------------------------------
# Odense St is on the Copenhagen-Aarhus IC line and has direct IC services to
# Copenhagen Airport (Kastrup). Prices are single (one-way) adult fares.
ODENSE_TO_AIRPORT: dict[str, Leg] = {
    "CPH": Leg(
        cost_min=17.5,  # Rejsekort / DSB early single  (DKK ~130)
        cost_typ=26.0,  # standard DSB single          (DKK ~195)
        hours=1.9,  # direct IC Odense St -> CPH, ~1h50
        mode="train",
        detail="DSB IC/IR Odense St -> Koebenhavns Lufthavn, direct ~1h50. "
        "Rejsekort ~DKK130, standard ~DKK195. Check dsb.dk / rejseplanen.dk",
    ),
    "BLL": Leg(
        cost_min=16.0,
        cost_typ=22.0,
        hours=2.0,
        mode="train+bus",
        detail="Odense St -> Vejle (IC ~40min) + bus 43/143 Vejle -> Billund "
        "Lufthavn (~50min). Sydtrafik/DSB. Check rejseplanen.dk",
    ),
    "AAR": Leg(
        cost_min=30.0,
        cost_typ=42.0,
        hours=3.0,
        mode="train+bus",
        detail="Odense St -> Aarhus H (IC ~1h50) + bus 925X Aarhus H -> Aarhus "
        "Lufthavn (~45min). Check rejseplanen.dk / midttrafik.dk",
    ),
    "MMX": Leg(  # Malmo Airport (Sturup), Sweden
        cost_min=26.0,
        cost_typ=38.0,
        hours=3.2,
        mode="train+bus",
        detail="Odense -> Malmo C via Oresund (~2h30) + bus/flygbuss to MMX "
        "~40min. Check sj.se / skanetrafiken.se",
    ),
    "HAM": Leg(  # Hamburg, Germany
        cost_min=30.0,  # Europa-Spezial / sparpreis
        cost_typ=55.0,
        hours=4.8,
        mode="train",
        detail="Odense -> Hamburg Hbf (~4h15, 1-2 changes via Flensburg or CPH) "
        "+ S-Bahn S1 to HAM airport (~25min). Check bahn.de (Sparpreis)",
    ),
    "OSL": Leg(
        cost_min=60.0,
        cost_typ=90.0,
        hours=9.0,
        mode="train",
        detail="Very long (overnight options). Only worth it for a huge fare gap.",
    ),
}

# ---------------------------------------------------------------------------
# 2. Italian arrival airport -> Salerno
# ---------------------------------------------------------------------------
# Salerno is served directly by Frecciarossa / Italo / Intercity high-speed
# trains (stop "Salerno"), and is ~35-55 min from Napoli Centrale.
# Train fares below assume booking ~1-2 weeks ahead; walk-up is far higher.
#
# For airports where the parents can collect you in Naples, use NAP as a
# 0-cost / ~0.6h transfer (PICKUP mode) -- see PICKUP_AIRPORTS.
ITALY_AIRPORT_TO_SALERNO: dict[str, Leg] = {
    "QSR": Leg(  # Salerno Costa d'Amalfi airport
        cost_min=4.0,
        cost_typ=15.0,
        hours=0.5,
        mode="bus/taxi",
        detail="Salerno Costa d'Amalfi (QSR) -> Salerno centre: local bus ~30min, "
        "or taxi ~15min. Closest airport to home.",
    ),
    "NAP": Leg(  # Naples Capodichino
        cost_min=5.0,
        cost_typ=9.0,
        hours=1.4,
        mode="bus/train",
        detail="Direct bus NAP -> Salerno (~1h20, ~EUR7, Buonajuto/SITA/FlixBus) "
        "OR Alibus to Napoli Centrale (EUR5, 20min) + Trenitalia "
        "Regionale Napoli->Salerno (EUR4-6, ~50min).",
    ),
    "FCO": Leg(  # Rome Fiumicino
        cost_min=29.0,
        cost_typ=45.0,
        hours=2.9,
        mode="train",
        detail="Leonardo Express FCO->Roma Termini (EUR14, 32min) + "
        "Frecciarossa/Italo Termini->Salerno (EUR15-30 early, ~1h15). "
        "Book high-speed early. Check trenitalia.com / italotreno.it",
    ),
    "CIA": Leg(  # Rome Ciampino
        cost_min=31.0,
        cost_typ=50.0,
        hours=3.2,
        mode="bus+train",
        detail="Bus CIA->Roma Termini (EUR6-7, 40min) + high-speed "
        "Termini->Salerno (EUR15-30, ~1h15).",
    ),
    "BLQ": Leg(  # Bologna
        cost_min=41.0,
        cost_typ=62.0,
        hours=4.4,
        mode="monorail+train",
        detail="Marconi Express BLQ->Bologna Centrale (EUR11, 7min) + "
        "Frecciarossa Bologna->Salerno (~3h20-3h50, EUR30-50 early).",
    ),
    "PSA": Leg(  # Pisa
        cost_min=35.0,
        cost_typ=58.0,
        hours=4.2,
        mode="peoplemover+train",
        detail="PisaMover PSA->Pisa Centrale (EUR5, 5min) + train Pisa->Salerno "
        "(via Firenze/Roma, ~4h, EUR30-50).",
    ),
    "VCE": Leg(  # Venice Marco Polo
        cost_min=42.0,
        cost_typ=68.0,
        hours=5.0,
        mode="bus+train",
        detail="ATVO bus VCE->Venezia Mestre (EUR10, 20min) + Frecciarossa "
        "Mestre->Salerno (~4h30, EUR35-60 early).",
    ),
    "TSF": Leg(  # Treviso
        cost_min=45.0,
        cost_typ=70.0,
        hours=5.4,
        mode="bus+train",
        detail="Bus TSF->Venezia Mestre (EUR12, 40min) + high-speed to Salerno.",
    ),
    "BGY": Leg(  # Milan Bergamo
        cost_min=40.0,
        cost_typ=70.0,
        hours=6.8,
        mode="bus+train",
        detail="Bus BGY->Milano Centrale (EUR8-10, 50min) + Frecciarossa/Italo "
        "Milano Centrale->Salerno (~5h15, EUR30-70 early).",
    ),
    "MXP": Leg(  # Milan Malpensa
        cost_min=44.0,
        cost_typ=75.0,
        hours=7.0,
        mode="train+train",
        detail="Malpensa Express MXP->Milano Centrale (EUR13, 52min) + "
        "high-speed Milano->Salerno (~5h15).",
    ),
    "LIN": Leg(  # Milan Linate
        cost_min=38.0,
        cost_typ=68.0,
        hours=6.6,
        mode="bus+train",
        detail="Bus 973/metro Linate->Milano Centrale (~30min, EUR2.50) + "
        "high-speed Milano->Salerno (~5h15).",
    ),
    "TRN": Leg(  # Turin
        cost_min=48.0,
        cost_typ=80.0,
        hours=6.4,
        mode="bus+train",
        detail="Bus/train TRN->Torino Porta Susa (~30min, EUR7) + "
        "Frecciarossa Torino->Salerno (~5h45, EUR40-70 early).",
    ),
    "BRI": Leg(  # Bari
        cost_min=28.0,
        cost_typ=50.0,
        hours=4.0,
        mode="train",
        detail="Train BRI->Bari Centrale (~20min, EUR5) + Intercity/Frecciarossa "
        "Bari->Salerno (~3h30-4h, EUR20-45).",
    ),
    "SUF": Leg(  # Lamezia Terme (Calabria)
        cost_min=22.0,
        cost_typ=40.0,
        hours=3.2,
        mode="bus+train",
        detail="Bus SUF->Lamezia Terme Centrale (~15min, EUR3) + train "
        "Lamezia->Salerno (~2h50-3h30, EUR18-35).",
    ),
    "OLB": Leg(  # Olbia, Sardinia -- ferry required
        cost_min=60.0,
        cost_typ=110.0,
        hours=14.0,
        mode="bus+ferry+train",
        detail="Sardinia: Olbia -> Civitavecchia/Genova ferry (~8-12h) + train. "
        "Only for extreme fare savings; usually not worth it.",
    ),
}

# Where a family car pickup in Naples replaces the airport->Salerno leg.
# key = arrival airport that lets you reach Naples pickup point cheaply,
# value = (cost to reach the pickup point, hours to reach it, detail)
PICKUP_NAPLES: dict[str, Leg] = {
    # If parents collect you at Naples (city or NAP airport):
    "NAP": Leg(0.0, 0.0, 0.0, "family pickup", "Parents collect at NAP / Naples."),
    # You can also take a cheap bus/train from these to Naples, but that is
    # already captured by the normal transfer above; pickup only helps at NAP.
}


def odense_to_airport(code: str) -> Leg | None:
    return ODENSE_TO_AIRPORT.get(code)


def airport_to_salerno(code: str, pickup: bool = False) -> Leg | None:
    """Ground leg arrival-airport -> Salerno.

    If pickup=True and the airport is NAP, the family collects you (0 cost).
    """
    if pickup and code in PICKUP_NAPLES:
        return PICKUP_NAPLES[code]
    return ITALY_AIRPORT_TO_SALERNO.get(code)


def total_hours(*legs: Leg) -> float:
    return sum(leg.hours for leg in legs)


# ---------------------------------------------------------------------------
# 3. Bookable ground segments (the train/bus/ferry to search when buying)
# ---------------------------------------------------------------------------
# Each ground leg is broken into the actual hops you book: operator, service
# (category/line), the stations, how often it runs, and where to book. These
# are the identifiers to feed into the operator's site for the flight's date.
# They are curated references, not a live timetable -- see README/INSTALL.


@dataclass(frozen=True)
class Segment:
    """One bookable hop: a specific train, bus or ferry service to search."""

    operator: str
    service: str
    depart: str
    arrive: str
    frequency: str
    duration: str
    book_at: str = ""

    def label(self) -> str:
        return f"{self.operator} {self.service}".strip()


def segments_label(segments: tuple[Segment, ...]) -> str:
    """Short one-line summary used in compact output."""
    return " + ".join(seg.label() for seg in segments)


ODENSE_SEGMENTS: dict[str, tuple[Segment, ...]] = {
    "CPH": (
        Segment(
            "DSB",
            "IC/IR",
            "Odense St",
            "Koebenhavns Lufthavn",
            "every ~30 min",
            "1h50",
            "dsb.dk",
        ),
    ),
    "BLL": (
        Segment("DSB", "IC", "Odense St", "Vejle", "every ~30 min", "40 min", "dsb.dk"),
        Segment(
            "Sydtrafik",
            "bus 43/143",
            "Vejle",
            "Billund Lufthavn",
            "every ~30 min",
            "50 min",
            "sydtrafik.dk",
        ),
    ),
    "AAR": (
        Segment(
            "DSB", "IC", "Odense St", "Aarhus H", "every ~30 min", "1h50", "dsb.dk"
        ),
        Segment(
            "Midttrafik",
            "bus 925X",
            "Aarhus H",
            "Aarhus Lufthavn",
            "hourly",
            "45 min",
            "midttrafik.dk",
        ),
    ),
    "MMX": (
        Segment(
            "Oeresundstag",
            "Oeresund",
            "Odense St",
            "Malmo C",
            "hourly",
            "2h30",
            "oresundstag.se",
        ),
        Segment(
            "Skanetrafiken",
            "flygbuss",
            "Malmo C",
            "Malmo Airport",
            "hourly",
            "40 min",
            "skanetrafiken.se",
        ),
    ),
    "HAM": (
        Segment(
            "DSB/DB",
            "IC/EC",
            "Odense St",
            "Hamburg Hbf",
            "few direct + changes",
            "4h15",
            "bahn.de",
        ),
        Segment(
            "HVV",
            "S-Bahn S1",
            "Hamburg Hbf",
            "Hamburg Airport",
            "every 10 min",
            "25 min",
            "hvv.de",
        ),
    ),
    "OSL": (
        Segment(
            "DSB/Vy", "night train", "Odense St", "Oslo S", "1/night", "~12h", "vy.no"
        ),
        Segment(
            "Flytoget",
            "airport train",
            "Oslo S",
            "Oslo Lufthavn",
            "every 10 min",
            "20 min",
            "flytoget.no",
        ),
    ),
}

ITALY_SEGMENTS: dict[str, tuple[Segment, ...]] = {
    "QSR": (
        Segment(
            "Busitalia Campania",
            "bus",
            "Salerno Costa d'Amalfi",
            "Salerno",
            "frequent",
            "30 min",
            "busitalia.it",
        ),
    ),
    "NAP": (
        Segment(
            "SITA Sud / Buonajuto",
            "direct bus",
            "Napoli Capodichino",
            "Salerno",
            "~hourly",
            "1h20",
            "sitasudtrasporti.it",
        ),
    ),
    "FCO": (
        Segment(
            "Trenitalia",
            "Leonardo Express",
            "Fiumicino Aeroporto",
            "Roma Termini",
            "every 15 min",
            "32 min",
            "trenitalia.com",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa/Italo",
            "Roma Termini",
            "Salerno",
            "2-3/hour",
            "1h15",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "CIA": (
        Segment(
            "Schiaffini/SIT",
            "bus",
            "Ciampino",
            "Roma Termini",
            "frequent",
            "40 min",
            "sitbus-shuttle.it",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa/Italo",
            "Roma Termini",
            "Salerno",
            "2-3/hour",
            "1h15",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "BLQ": (
        Segment(
            "Marconi Express",
            "monorail",
            "Bologna Aeroporto",
            "Bologna Centrale",
            "every 7 min",
            "7 min",
            "marconiexpress.it",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa/Italo",
            "Bologna Centrale",
            "Salerno",
            "hourly+",
            "3h20",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "PSA": (
        Segment(
            "PisaMover",
            "people mover",
            "Pisa Aeroporto",
            "Pisa Centrale",
            "every 5-8 min",
            "5 min",
            "pisamover.it",
        ),
        Segment(
            "Trenitalia",
            "Intercity/Regionale",
            "Pisa Centrale",
            "Salerno",
            "via Firenze/Roma",
            "4h",
            "trenitalia.com",
        ),
    ),
    "VCE": (
        Segment(
            "ATVO",
            "bus 5/35",
            "Venezia Aeroporto",
            "Venezia Mestre",
            "every 15-30 min",
            "20 min",
            "atvo.it",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa",
            "Venezia Mestre",
            "Salerno",
            "hourly",
            "4h30",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "TSF": (
        Segment(
            "ATVO",
            "bus",
            "Treviso Aeroporto",
            "Venezia Mestre",
            "frequent",
            "40 min",
            "atvo.it",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa",
            "Venezia Mestre",
            "Salerno",
            "hourly",
            "4h30",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "BGY": (
        Segment(
            "Terravision/ATB",
            "bus",
            "Bergamo Aeroporto",
            "Milano Centrale",
            "every 20-30 min",
            "50 min",
            "terravision.eu",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa/Italo",
            "Milano Centrale",
            "Salerno",
            "2/hour",
            "5h15",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "MXP": (
        Segment(
            "Trenord",
            "Malpensa Express",
            "Malpensa Aeroporto",
            "Milano Centrale",
            "every 30 min",
            "52 min",
            "trenord.it",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa/Italo",
            "Milano Centrale",
            "Salerno",
            "2/hour",
            "5h15",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "LIN": (
        Segment(
            "ATM",
            "bus 973 / metro M4",
            "Linate",
            "Milano Centrale",
            "frequent",
            "30 min",
            "atm.it",
        ),
        Segment(
            "Trenitalia/Italo",
            "Frecciarossa/Italo",
            "Milano Centrale",
            "Salerno",
            "2/hour",
            "5h15",
            "trenitalia.com / italotreno.it",
        ),
    ),
    "TRN": (
        Segment(
            "SADEM/Trenitalia",
            "bus/train",
            "Torino Aeroporto",
            "Torino Porta Susa",
            "every 30 min",
            "30 min",
            "sadem.it",
        ),
        Segment(
            "Trenitalia",
            "Frecciarossa",
            "Torino Porta Susa",
            "Salerno",
            "1-2/hour",
            "5h45",
            "trenitalia.com",
        ),
    ),
    "BRI": (
        Segment(
            "Ferrotramviaria",
            "FM2",
            "Bari Aeroporto",
            "Bari Centrale",
            "every 20-30 min",
            "20 min",
            "ferrovienordbarese.it",
        ),
        Segment(
            "Trenitalia",
            "Intercity/Frecciarossa",
            "Bari Centrale",
            "Salerno",
            "~hourly",
            "3h30",
            "trenitalia.com",
        ),
    ),
    "SUF": (
        Segment(
            "SACAL",
            "bus",
            "Lamezia Aeroporto",
            "Lamezia Terme Centrale",
            "~hourly",
            "15 min",
            "sacal.it",
        ),
        Segment(
            "Trenitalia",
            "Intercity/Regionale",
            "Lamezia Terme Centrale",
            "Salerno",
            "hourly+",
            "3h",
            "trenitalia.com",
        ),
    ),
    "OLB": (
        Segment(
            "Ferry",
            "Olbia -> Civitavecchia/Genova",
            "Olbia",
            "Civitavecchia/Genova",
            "1-2/day",
            "8-12h",
            "directferries.com",
        ),
        Segment(
            "Trenitalia",
            "Intercity/Frecciarossa",
            "Civitavecchia/Genova",
            "Salerno",
            "frequent",
            "~4h",
            "trenitalia.com",
        ),
    ),
}

PICKUP_SEGMENTS: dict[str, tuple[Segment, ...]] = {
    "NAP": (
        Segment(
            "Family", "car pickup", "Napoli Capodichino", "Salerno", "on request", "~1h"
        ),
    ),
}


def odense_segments(code: str) -> tuple[Segment, ...]:
    """Bookable hops for Odense -> departure airport."""
    return ODENSE_SEGMENTS.get(code, ())


def airport_segments(code: str, pickup: bool = False) -> tuple[Segment, ...]:
    """Bookable hops for arrival airport -> Salerno."""
    if pickup and code in PICKUP_SEGMENTS:
        return PICKUP_SEGMENTS[code]
    return ITALY_SEGMENTS.get(code, ())


def odense_service(code: str) -> str:
    """Compact label for the Odense -> departure-airport leg."""
    return segments_label(odense_segments(code))


def airport_service(code: str, pickup: bool = False) -> str:
    """Compact label for the arrival-airport -> Salerno leg."""
    return segments_label(airport_segments(code, pickup))


__all__ = [
    "FX_DKK",
    "ITALY_AIRPORT_TO_SALERNO",
    "ITALY_SEGMENTS",
    "ODENSE_SEGMENTS",
    "ODENSE_TO_AIRPORT",
    "PICKUP_NAPLES",
    "PICKUP_SEGMENTS",
    "Leg",
    "Segment",
    "airport_segments",
    "airport_service",
    "airport_to_salerno",
    "odense_segments",
    "odense_service",
    "odense_to_airport",
    "segments_label",
    "total_hours",
]
