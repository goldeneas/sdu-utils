"""Client Google Flights via Playwright (scraping diretto).

Ricerca ONE-WAY: Google Flights, per una ricerca andata/ritorno, mostra prima le
opzioni di ANDATA e solo dopo la scelta mostra il ritorno. Per questo lo script
interroga una tratta alla volta (`search_one_way`) e combina andata+ritorno in
Python (vedi search.py).

ATTENZIONE (manutenzione): Google può cambiare classi CSS / struttura del DOM.
I selettori sono centralizzati in EXTRACT_JS; in caso di rottura esegui
`python main.py --debug` e aggiorna i selettori usando l'HTML salvato in
debug_dumps/.
"""
from __future__ import annotations

import re
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote

import playwright.sync_api as pw  # pyright: ignore[reportMissingImports]

from .models import OneWayOffer, Segment  # pyright: ignore[reportMissingImports]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

TIME_12H_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*$", re.IGNORECASE)
TIME_24H_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
DURATION_RE = re.compile(r"(\d+)\s*hr(?:\s*(\d+)\s*min)?|(\d+)\s*min", re.IGNORECASE)
STOPS_RE = re.compile(r"(\d+)\s*stop", re.IGNORECASE)
SUMMARY_WITH_RE = re.compile(r"flight with (.+?)[.]", re.IGNORECASE)
SUMMARY_OPERATED_RE = re.compile(r"Operated by (.+?)[.]", re.IGNORECASE)
SUMMARY_LAYOVER_RE = re.compile(r"Layover \(1 of 1\) is a (.+?) layover", re.IGNORECASE)


class BlockedError(RuntimeError):
    """Google ha bloccato la richiesta (captcha / traffico insolito)."""


class RateLimitedError(RuntimeError):
    """Google non risponde (probabile throttling / rate-limit)."""

# Estrazione dal DOM. Usa aria-label con match "inizia con" (^=) per prendere
# solo le "foglie" (orari, durata, scali) evitando i contenitori con
# aria-label riassuntivi lunghi. Compagnia e scalo si ricavano dal riassunto.
EXTRACT_JS = r"""
() => {
  const cleanTime = (s) => s
    .replace(/^Departure time:\s*/i, '')
    .replace(/^Arrival time:\s*/i, '')
    .replace(/\s*on\s+.*$/i, '')
    .replace(/\.\s*$/, '')
    .trim();

  const cards = document.querySelectorAll('li[class*="pIav2d"]');
  const out = [];
  for (const el of cards) {
    const priceEls = Array.from(el.querySelectorAll('[aria-label*=" euros"]'))
      .filter(n => /^\d[\d,]*\s*euros/i.test(n.getAttribute('aria-label') || ''));
    if (!priceEls.length) continue;
    const price = parseFloat((priceEls[0].getAttribute('aria-label') || '').replace(/,/g, '').match(/\d+/)[0]);
    if (!price) continue;

    const depTimes = Array.from(el.querySelectorAll('[aria-label^="Departure time:"]'))
      .map(n => cleanTime(n.getAttribute('aria-label') || '')).filter(Boolean);
    const arrTimes = Array.from(el.querySelectorAll('[aria-label^="Arrival time:"]'))
      .map(n => cleanTime(n.getAttribute('aria-label') || '')).filter(Boolean);
    const durations = Array.from(el.querySelectorAll('[aria-label^="Total duration"]'))
      .map(n => (n.getAttribute('aria-label') || '').replace(/^Total duration\s*/i, '').replace(/\.\s*$/, '').trim()).filter(Boolean);
    const stopTexts = Array.from(el.querySelectorAll('[aria-label^="Nonstop flight"], [aria-label^="1 stop flight"], [aria-label^="2 stop flight"], [aria-label^="3 stop flight"]'))
      .map(n => (n.getAttribute('aria-label') || '').trim()).filter(Boolean);

    const summaries = Array.from(el.querySelectorAll('[aria-label]'))
      .map(n => n.getAttribute('aria-label'))
      .filter(a => a && a.includes('Leaves') && a.includes('arrives'));
    const summary = summaries[0] || '';

    out.push({ price, depTimes, arrTimes, durations, stopTexts, summary });
  }
  return out;
}
"""


def parse_time_24h(text: str) -> str:
    t = (text or "").strip()
    m = TIME_12H_RE.match(t)
    if m:
        h, mm, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{mm:02d}"
    m = TIME_24H_RE.match(t)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return t


def parse_duration_minutes(text: str) -> int | None:
    m = DURATION_RE.search(text or "")
    if not m:
        return None
    if m.group(1):
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    if m.group(3):
        return int(m.group(3))
    return None


def parse_stops(text: str) -> int:
    t = (text or "").lower()
    if "nonstop" in t or "direct" in t:
        return 0
    m = STOPS_RE.search(t)
    return int(m.group(1)) if m else 0


def parse_summary(text: str) -> tuple[str, int | None]:
    """Dal riassunto accessibile ricava compagnia e durata dello scalo."""
    airline = "n/d"
    layover = None
    if text:
        m = SUMMARY_WITH_RE.search(text)
        if m:
            airline = m.group(1).strip().rstrip(".")
        op = SUMMARY_OPERATED_RE.search(text)
        if op:
            airline += f" (op. {op.group(1).strip().rstrip('.')})"
        lm = SUMMARY_LAYOVER_RE.search(text)
        if lm:
            layover = parse_duration_minutes(lm.group(1))
    return airline, layover


def build_url(origin, destination, date, currency="EUR", lang="en"):
    d = date.strftime("%Y-%m-%d")
    q = f"Flights from {origin} to {destination} on {d}"
    return (
        "https://www.google.com/travel/flights"
        f"?hl={lang}&curr={currency}&q={quote(q)}"
    )


class GoogleFlightsClient:
    def __init__(self, scraper_cfg):
        self.cfg = scraper_cfg
        self.timeout_ms = int(scraper_cfg.timeout_seconds * 1000)
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    def start(self):
        self._pw = pw.sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.cfg.headless)
        self._context = self._browser.new_context(
            user_agent=UA,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        self._page = self._context.new_page()

    def close(self):
        for obj in (self._context, self._browser):
            with suppress(Exception, KeyboardInterrupt):
                if obj:
                    obj.close()
        with suppress(Exception, KeyboardInterrupt):
            if self._pw:
                self._pw.stop()

    def search_one_way(self, origin, destination, date):
        """Restituisce le offerte one-way (ordinate per prezzo) per una tratta."""
        url = build_url(origin, destination, date, currency="EUR")
        for attempt in range(2):
            try:
                state, offers = self._try_search(url, origin, destination, date)
            except BlockedError:
                raise
            except pw.TimeoutError:
                # Google non risponde: quasi certamente rate-limit
                if attempt == 0:
                    time.sleep(5)
                    continue
                raise RateLimitedError(
                    f"Google non risponde ({origin}-{destination} {date})"
                ) from None
            except Exception as exc:  # noqa: BLE001  # retry su qualsiasi errore transitorio
                if attempt == 1:
                    print(
                        f"  [warn] ricerca fallita {origin}-{destination} "
                        f"{date}: {exc}"
                    )
                time.sleep(3 * (attempt + 1))
                continue
            if state == "blocked":
                raise BlockedError(
                    f"Google sta bloccando le richieste ({origin}-{destination} {date})"
                )
            if state == "no_results":
                return []
            if state == "results":
                return offers
            # "unknown": pagina lenta (possibile rate-limit), riprova una volta
            time.sleep(3 * (attempt + 1))
        return []

    def _try_search(self, url, origin, destination, date):
        self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._handle_consent()
        state = self._wait_for_state()
        if self.cfg.debug_dump_dir:
            self._dump(origin, destination, date)
        if state in ("no_results", "blocked"):
            return state, []
        raw = []
        with suppress(Exception):
            raw = self._page.evaluate(EXTRACT_JS)
        return state, self._parse(raw, origin, destination, date)

    def _wait_for_state(self):
        """Attende i risultati, il messaggio 'nessun volo' o rileva un blocco."""
        sel = (
            'li[class*="pIav2d"], '
            ':text("No results returned"), '
            ':text("No options matching")'
        )
        with suppress(Exception):
            self._page.wait_for_selector(sel, timeout=self.timeout_ms)
            if self._page.locator('li[class*="pIav2d"]').count() > 0:
                return "results"
            return "no_results"
        with suppress(Exception):
            body = self._page.locator("body").inner_text(timeout=3000)
            low = body.lower()
            if "unusual traffic" in low or "are you a robot" in low or "captcha" in low:
                return "blocked"
        return "unknown"

    def _handle_consent(self):
        """Gestisce l'interstiziale di consenso 'Before you continue' di Google."""
        with suppress(Exception):
            self._page.wait_for_timeout(1200)
        title = ""
        with suppress(Exception):
            title = self._page.title() or ""
        url = ""
        with suppress(Exception):
            url = self._page.url or ""
        if "before you continue" not in title.lower() and "consent" not in url.lower():
            return
        for label in ("Accept all", "I agree", "Accept", "Accetta tutto"):
            with suppress(Exception):
                btn = self._page.locator(f'button:has-text("{label}")').first
                if btn.count() > 0:
                    btn.click(timeout=4000)
                    self._page.wait_for_load_state("domcontentloaded", timeout=8000)
                    return

    def _dump(self, origin, destination, date):
        d = Path(self.cfg.debug_dump_dir)
        d.mkdir(parents=True, exist_ok=True)
        stem = f"{origin}_{destination}_{date}"
        with suppress(Exception):
            (d / f"{stem}.html").write_text(self._page.content(), encoding="utf-8")
            self._page.screenshot(path=str(d / f"{stem}.png"), full_page=True)

    def _parse(self, raw, origin, destination, date):
        offers = []
        seen = set()
        for r in raw:
            if not r["depTimes"] or not r["arrTimes"]:
                continue
            dep = parse_time_24h(r["depTimes"][0])
            arr = parse_time_24h(r["arrTimes"][-1])
            if not dep or not arr:
                continue
            duration = parse_duration_minutes(r["durations"][0]) if r["durations"] else None
            stops = parse_stops(r["stopTexts"][0]) if r["stopTexts"] else 0
            airline, layover = parse_summary(r["summary"])

            # dedup: lo stesso volo può comparire sia nella griglia "best"
            # sia nella lista "other flights"
            sig = (round(r["price"], 2), dep, arr, airline)
            if sig in seen:
                continue
            seen.add(sig)

            offers.append(
                OneWayOffer(
                    segment=Segment(
                        origin=origin,
                        destination=destination,
                        departure_time=dep,
                        arrival_time=arr,
                        airline=airline,
                        stops=stops,
                        layover_minutes=layover,
                        duration_minutes=duration,
                    ),
                    price=round(r["price"], 2),
                    currency="EUR",
                )
            )
        offers.sort(key=lambda o: o.price)
        return offers
