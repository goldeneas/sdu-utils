"""Client Google Flights tramite la libreria `fast-flights` (scraping non ufficiale).

Una richiesta = una tratta in un giorno: restituisce TUTTI i voli di quel giorno
(non solo il più economico), con prezzo, orari, scali e compagnia. Il prezzo è per
tratta, quindi andata e ritorno si sommano e si combinano come per Ryanair.

ATTENZIONE: Google può cambiare il formato; in tal caso va aggiornata `fast-flights`
(`pip install -U fast-flights`).
"""
from __future__ import annotations

import os
import re
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
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = " ".join(m.group(1).split()) if m else "(nessun titolo)"
    markers = {
        "consenso cookie di Google": ("consent.google", "before you continue", "prima di continuare"),
        "captcha / traffico insolito": ("unusual traffic", "traffico insolito", "g-recaptcha", "/sorry/"),
    }
    for label, keys in markers.items():
        hit = next((k for k in keys if k in low), None)
        if hit:
            return f"{label} [trovato «{hit}»] · titolo pagina: «{title}» · {len(html)} byte"
    return f"pagina senza dati voli · titolo: «{title}» · {len(html)} byte"


def fetch_html(query) -> str:
    """Scarica la pagina Google Flights con i cookie di consenso già impostati."""
    from primp import Client

    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True)
    with_cookies = getattr(client, "set_cookies", None)
    if with_cookies:
        with_cookies(URL, CONSENT_COOKIES)
    return client.get(URL, params=query.params()).text


def _parse_time(value) -> tuple[int, int]:
    """[8] = 08:00, [None, 31] = 00:31: Google omette le componenti a zero."""
    padded = [*(value or []), None, None]
    return (padded[0] or 0, padded[1] or 0)


class Parsed(list):
    """Lista di voli letti, con il conteggio delle voci trovate e di quelle scartate."""

    total = 0
    skipped = 0


def parse_js_tolerant(js: str):
    """Come `fast_flights.parser.parse_js`, ma salta i voli con dati mancanti.

    Google mostra anche voli senza prezzo (es. non prenotabili): la libreria va in
    errore su tutta la pagina, qui si scartano solo quelle voci.
    """
    import json

    from fast_flights.exceptions import FlightsNotFound
    from fast_flights.model import (
        Airport, CarbonEmission, Flights, SimpleDatetime, SingleFlight,
    )

    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        raise FlightsNotFound("no flights found; received error")
    payload = json.loads(data)
    # payload[2] = "migliori voli", payload[3] = "altri voli": Google li separa
    entries = []
    for idx in (2, 3):
        try:
            block = payload[idx][0]
        except (IndexError, TypeError):
            continue
        # solo elenchi di voci-lista: gli altri blocchi `ds:N` (paesi, valute, lingue) contengono stringhe
        if isinstance(block, list):
            entries += [k for k in block if isinstance(k, list)]
    results = Parsed()
    results.total = len(entries)
    for k in entries:
        try:
            flight = k[0]
            price = k[1][0][1]
            segs = []
            for sf in flight[2]:
                segs.append(SingleFlight(
                    from_airport=Airport(code=sf[3], name=sf[4]),
                    to_airport=Airport(code=sf[6], name=sf[5]),
                    departure=SimpleDatetime(date=tuple(sf[20]), time=_parse_time(sf[8])),
                    arrival=SimpleDatetime(date=tuple(sf[21]), time=_parse_time(sf[10])),
                    duration=sf[11],
                    plane_type=sf[17],
                ))
            try:
                extras = flight[22]
                carbon = CarbonEmission(typical_on_route=extras[8], emission=extras[7])
            except (IndexError, TypeError):
                carbon = CarbonEmission(typical_on_route=0, emission=0)
            results.append(Flights(type=flight[0], price=price, airlines=flight[1], flights=segs, carbon=carbon))
        except (IndexError, TypeError, KeyError):
            results.skipped += 1  # voce senza prezzo o con formato diverso
    return results


def parse_any_script(html: str):
    """Cerca i dati voli in tutti gli <script> `ds:N` (Google può spostarli).

    Solo il blocco con i risultati ha voci di volo: gli altri (paesi, valute, lingue)
    si leggono senza errori ma restano vuoti, quindi si sceglie il primo con almeno un volo con prezzo.
    Se nessuno ne ha ma almeno uno ha la struttura giusta, la pagina è "nessun volo".
    """
    from fast_flights.exceptions import FlightsNotFound
    from selectolax.lexbor import LexborHTMLParser

    scripts = LexborHTMLParser(html).css("script")
    candidates = [s for s in scripts if (s.attributes.get("class") or "").startswith("ds:")]
    candidates += [s for s in scripts if s not in candidates and "data:" in (s.text() or "")[:5000]]
    empty = None
    for s in candidates:
        try:
            parsed = parse_js_tolerant(s.text())
        except FlightsNotFound:
            raise
        except Exception:  # noqa: BLE001 - blocco con altra struttura: prova il prossimo
            continue
        if parsed:  # almeno un volo con prezzo: è il blocco dei risultati
            return parsed
        if _looks_like_results(s.text()):
            empty = parsed
    if empty is not None:
        return empty
    raise ValueError("nessun blocco dati con la struttura attesa")


def _looks_like_results(js: str) -> bool:
    """Riconosce il blocco dei risultati anche quando è vuoto ("nessun volo").

    Quello dei risultati ha in testa un'intestazione di 5 elementi che termina con un
    token lungo; gli altri blocchi `ds:N` (aeroporti, paesi, valute, lingue) no.
    """
    import json

    try:
        payload = json.loads(js.split("data:", 1)[1].rsplit(",", 1)[0])
        head = payload[0]
        return isinstance(head, list) and len(head) >= 5 and isinstance(head[4], str) and len(head[4]) > 20
    except Exception:  # noqa: BLE001
        return False


def get_flights_with_consent(query):
    html = fetch_html(query)
    try:
        return parse_any_script(html)
    except Exception as exc:
        from fast_flights.exceptions import FlightsNotFound
        if isinstance(exc, FlightsNotFound):
            raise
        return _fail(html, exc)


def _fail(html: str, exc: Exception):
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
        self.stats = {"pagine": 0, "voci": 0, "scartate": 0, "con_voli": 0}

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
        self.stats["pagine"] += 1
        self.stats["voci"] += getattr(results, "total", len(results))
        self.stats["scartate"] += getattr(results, "skipped", 0)
        fares = parse_flights(results, origin, destination, query.url(), self.currency)
        self.stats["con_voli"] += bool(fares)
        return fares
