#!/usr/bin/env python3
"""Fetch the current supermarket flier offers near Odense and write them as one JSON file.

Data comes from the public (unofficial, undocumented) API behind etilbudsavis.dk (Tjek / ShopGun).
Only the Python standard library is used, so the GitHub Action needs no install step.

    python3 flier-summary/scraper/fetch_offers.py                # writes flier-summary/data/offers.json
    python3 flier-summary/scraper/fetch_offers.py --out x.json   # somewhere else

The script exits non-zero when no store returned any offers, so a broken API never replaces good data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://squid-api.tjek.com/v2"

# Odense centre. The radius limits the offers to fliers valid for stores around the city.
LAT, LNG, RADIUS_M = 55.3959, 10.3883, 15000

# Stores to aggregate. "id" is the known eTilbudsavis dealer id; "match" is used to look the
# dealer up by name if that id ever stops resolving.
STORES = [
    {"key": "netto", "name": "Netto", "id": "9ba51", "match": ["netto"]},
    {"key": "365discount", "name": "365discount", "id": "DWZE1w", "match": ["365discount", "coop 365", "365"]},
    {"key": "bilka", "name": "Bilka", "id": "93f13", "match": ["bilka"]},
    {"key": "superbrugsen", "name": "SuperBrugsen", "id": "0b1e8", "match": ["superbrugsen"]},
]

PAGE_LIMIT = 100  # the API rejects larger pages
MAX_PAGES = 30
USER_AGENT = "sdu-utils-flier-summary/1.0 (+https://github.com/goldeneas/sdu-utils)"


def get_json(path: str, params: dict) -> object:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.load(res)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 and exc.code != 429:
                break
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed: {last}")


def norm(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def resolve_dealers(stores: list[dict]) -> dict[str, dict]:
    """Return {store key: dealer json}. Uses the known id, falls back to a name search."""
    found: dict[str, dict] = {}
    try:
        dealers = get_json("dealers", {"dealer_ids": ",".join(s["id"] for s in stores), "limit": 100})
    except RuntimeError as exc:
        print(f"warning: dealer lookup failed: {exc}", file=sys.stderr)
        dealers = []
    by_id = {d.get("id"): d for d in dealers if isinstance(d, dict)}
    for store in stores:
        dealer = by_id.get(store["id"])
        if dealer and any(m in norm(dealer.get("name", "")) for m in store["match"]):
            found[store["key"]] = dealer
            continue
        # id missing or now names a different chain: search by name
        try:
            hits = get_json("dealers", {"query": store["name"], "country_id": "DK", "limit": 20})
        except RuntimeError as exc:
            print(f"warning: dealer search for {store['name']} failed: {exc}", file=sys.stderr)
            hits = []
        for hit in hits if isinstance(hits, list) else []:
            if any(norm(hit.get("name", "")) == m for m in store["match"]):
                print(f"note: {store['name']} resolved by name to dealer id {hit.get('id')}", file=sys.stderr)
                found[store["key"]] = hit
                break
        else:
            print(f"warning: could not resolve dealer for {store['name']}", file=sys.stderr)
    return found


def fetch_dealer_offers(dealer_id: str) -> list[dict]:
    offers: list[dict] = []
    for page in range(MAX_PAGES):
        batch = get_json("offers", {
            "dealer_ids": dealer_id,
            "r_lat": LAT, "r_lng": LNG, "r_radius": RADIUS_M,
            "order_by": "page",
            "limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT,
        })
        if not isinstance(batch, list) or not batch:
            break
        offers.extend(batch)
        if len(batch) < PAGE_LIMIT:
            break
    return offers


def _num(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def quantity_text(q: dict | None) -> str:
    """Turn the API's quantity block into something like '500 g', '2-3 stk' or '1 l'."""
    if not isinstance(q, dict):
        return ""
    parts = []
    size, unit = q.get("size") or {}, (q.get("unit") or {}).get("symbol") or ""
    lo, hi = _num(size.get("from")), _num(size.get("to"))
    if lo:
        fmt = lambda x: f"{x:g}".replace(".", ",")
        parts.append((fmt(lo) if not hi or hi == lo else f"{fmt(lo)}-{fmt(hi)}") + (f" {unit}" if unit else ""))
    pieces = q.get("pieces") or {}
    plo, phi = _num(pieces.get("from")), _num(pieces.get("to"))
    if plo and (plo > 1 or (phi and phi > 1)):
        parts.append(f"{plo:g} stk" if not phi or phi == plo else f"{plo:g}-{phi:g} stk")
    return " · ".join(parts)


def unit_price(price: float | None, q: dict | None) -> str:
    """Price per kg / l when the API gives a size in SI units, e.g. '49,80 kr/kg'."""
    if price is None or not isinstance(q, dict):
        return ""
    unit = q.get("unit") or {}
    si = unit.get("si") or {}
    size = _num((q.get("size") or {}).get("from"))
    factor = _num(si.get("factor"))
    pieces = _num((q.get("pieces") or {}).get("from")) or 1
    if not size or not factor or si.get("symbol") not in ("kg", "l"):
        return ""
    amount = size * factor * pieces
    if amount <= 0:
        return ""
    return f"{price / amount:.2f}".replace(".", ",") + f" kr/{si['symbol']}"


def slim(offer: dict, store_key: str) -> dict | None:
    heading = (offer.get("heading") or "").strip()
    if not heading:
        return None
    pricing = offer.get("pricing") or {}
    price, pre = _num(pricing.get("price")), _num(pricing.get("pre_price"))
    images = offer.get("images") or {}
    q = offer.get("quantity")
    return {
        "id": offer.get("id"),
        "store": store_key,
        "heading": heading,
        "description": " ".join((offer.get("description") or "").split())[:300],
        "price": price,
        "prePrice": pre if pre and price and pre > price else None,
        "quantity": quantity_text(q),
        "unitPrice": unit_price(price, q),
        "from": offer.get("run_from"),
        "till": offer.get("run_till"),
        "image": images.get("thumb") or images.get("view") or images.get("zoom"),
        "catalogId": offer.get("catalog_id"),
        "page": offer.get("catalog_page"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "offers.json"))
    args = ap.parse_args(argv)

    dealers = resolve_dealers(STORES)
    stores_out, offers_out = [], []
    for store in STORES:
        dealer = dealers.get(store["key"])
        entry = {"key": store["key"], "name": store["name"], "count": 0}
        if dealer:
            branding = dealer.get("branding") or {}
            entry["color"] = "#" + (branding.get("color") or dealer.get("color") or "666666").lstrip("#")
            entry["logo"] = branding.get("logo") or dealer.get("logo")
            try:
                raw = fetch_dealer_offers(dealer["id"])
            except RuntimeError as exc:
                print(f"warning: {store['name']}: {exc}", file=sys.stderr)
                raw = []
            seen = set()
            for o in raw:
                s = slim(o, store["key"])
                if s and s["id"] not in seen:
                    seen.add(s["id"])
                    offers_out.append(s)
            entry["count"] = len(seen)
        print(f"{store['name']}: {entry['count']} offers", file=sys.stderr)
        stores_out.append(entry)

    if not offers_out:
        print("error: no offers fetched from any store; not writing output", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": {"name": "Odense", "lat": LAT, "lng": LNG, "radius": RADIUS_M},
        "stores": stores_out,
        "offers": offers_out,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(offers_out)} offers to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
