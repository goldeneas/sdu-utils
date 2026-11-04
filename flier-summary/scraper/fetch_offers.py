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
import re
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
    {"key": "lidl", "name": "Lidl", "id": "71c90", "match": ["lidl"]},
]

PAGE_LIMIT = 100  # the API rejects larger pages
MAX_OFFSET = 1000  # the API rejects offset + limit beyond this
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


def fetch_paged(params: dict) -> list[dict]:
    """Page through /offers. The API refuses offset+limit beyond 1000, so callers narrow the
    query (one catalog at a time) and whatever was fetched before an error is kept."""
    offers: list[dict] = []
    for page in range(MAX_OFFSET // PAGE_LIMIT):
        try:
            batch = get_json("offers", {**params, "limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT})
        except RuntimeError as exc:
            print(f"warning: {exc}", file=sys.stderr)
            break
        if not isinstance(batch, list) or not batch:
            break
        offers.extend(batch)
        if len(batch) < PAGE_LIMIT:
            break
    return offers


def fetch_dealer_offers(dealer_id: str) -> list[dict]:
    """All offers of a dealer's fliers valid near Odense, fetched catalog by catalog.

    Big chains like Bilka run ~10 fliers with ~3000 offers in total, more than one paged
    /offers query can return, so each catalog is fetched separately."""
    geo = {"r_lat": LAT, "r_lng": LNG, "r_radius": RADIUS_M}
    catalogs = get_json("catalogs", {"dealer_ids": dealer_id, **geo, "limit": 100})
    if not isinstance(catalogs, list) or not catalogs:
        return fetch_paged({"dealer_ids": dealer_id, **geo, "order_by": "page"})
    offers: list[dict] = []
    for cat in catalogs:
        batch = fetch_paged({"catalog_ids": cat["id"], **geo, "order_by": "page"})
        for o in batch:
            o["_catalog_label"] = cat.get("label") or ""
        offers.extend(batch)
    return offers


# ---------------------------------------------------------------- categories
# The API's category_ids are empty for every offer, so categories come from keywords in the
# offer heading. Danish glues words together ("grisekød", "proteinbar"), so a term matches
# anywhere inside a word; "=term" must be a whole word and "term$" must end a word.
# The first category that matches wins; "protein" is an extra tag on top of it.
CATEGORIES = [
    ("household", "Household & care", [
        "vaskemiddel", "skyllemiddel", "opvask", "toiletpapir", "køkkenrulle", "papir", "shampoo", "balsam",
        "tandpasta", "tandbørste", "deodorant", "deo", "bleer", "ble$", "sæbe", "showergel", "rengøring",
        "affaldspose", "skraldepose", "barberskrab", "hudpleje", "creme", "makeup", "mascara", "vatrondel",
        "plaster", "læbestift", "pleje", "kosmetik", "hårtørrer", "trimmer", "massage", "baume", "parfum", "=edp", "=edt", "eau de", "bodylotion", "serum", "neglelak", "hårkur", "barbermaskine", "tandtråd", "vaskeklude", "viskestykke", "opvaskemiddel", "kattegrus", "kattemad", "hundemad", "hunde", "katte", "foder"]),
    ("meat", "Meat & fish", [
        "kød", "kylling", "gris", "okse", "kalv", "=lam", "lammekød", "bacon", "pølse", "medister", "skinke", "hakket",
        "fars", "steak", "bøf", "kalkun", "andebryst", "andelår", "flæsk", "frikadelle", "leverpostej", "salami", "pålæg",
        "spegepølse", "mørbrad", "filet", "laks", "fisk", "rejer", "torsk", "=tun", "tunfisk", "sild",
        "makrel", "rødspætte", "kebab", "salsiccia", "schnitzel", "nuggets", "ribbe", "culotte", "entrecote", "roastbeef", "hamburger"]),
    ("dairy", "Dairy & eggs", [
        "mælk", "=ost", "ost$", "oste", "skyr", "yoghurt", "smør", "fløde", "hytteost", "kvark", "=æg",
        "æg$", "cheese", "mozzarella", "feta", "parmesan", "cheddar", "brie", "creme fraiche", "cremefraiche",
        "budding", "mousse", "kefir", "ymer", "a38", "koldskål", "margarine", "lurpak", "risalamande", "kærgården", "bregott", "riberhus", "castello", "arla"]),
    ("drinks", "Drinks", [
        "=øl", "øl$", "pilsner", "=vin", "vin$", "rødvin", "hvidvin", "rosé", "cava", "prosecco", "champagne",
        "sodavand", "juice", "cola", "kaffe", "=te", "vand$", "saft", "spiritus", "=gin", "vodka", "whisky",
        "rom$", "likør", "energidrik", "drik", "smoothie", "cider", "nektar", "kakao", "espresso", "kapsler",
        "pepsi", "gløgg", "brevte", "=brut", "chablis", "barolo", "rioja", "chianti", "bordeaux", "primitivo", "amarone", "ripasso", "latte", "chai", "kombucha", "mineralvand", "danskvand", "ribena", "rynkeby", "=0.0", "faxe", "tuborg", "carlsberg", "red bull", "monster", "booster", "fanta", "sprite", "drink"]),
    ("bakery", "Bread & bakery", [
        "brød", "boller", "bolle$", "rugbrød", "toast", "kage", "wienerbrød", "croissant", "baguette",
        "pitabrød", "tortilla", "wraps", "knækbrød", "kringle", "snegl", "muffin", "donut", "flûte",
        "pizzabund", "pastel de nata", "brioche", "rundstykke"]),
    ("produce", "Fruit & veg", [
        "æble", "banan", "kartof", "tomat", "agurk", "salat", "=løg", "løg$", "gulerød", "gulerødder",
        "frugt", "grønt", "grøntsag", "appelsin", "mandarin", "clementin", "pære", "druer", "avocado",
        "peberfrugt", "broccoli", "blomkål", "kål", "porre", "champignon", "svampe", "citron", "lime",
        "melon", "ananas", "jordbær", "blåbær", "hindbær", "bær$", "kiwi", "spinat", "majs",
        "hvidløg", "ingefær", "krydderurt", "persille", "rødbede", "selleri", "pastinak", "græskar"]),
    ("snacks", "Snacks & sweets", [
        "chips", "slik", "chokolade", "kiks", "nødder", "=is", "isvaffel", "flødeis", "isvaffel", "bar$", "popcorn",
        "vingummi", "lakrids", "marcipan", "småkager", "cookies", "snack", "mandler", "peanuts", "flødebolle",
        "pebernødder", "konfekt", "karamel", "bolsjer", "pringles", "haribo", "toms", "anthon berg",
        "ritter sport", "m&m", "kinder", "twist", "guldbarre"]),
    ("pantry", "Pantry & frozen", [
        "pasta", "spaghetti", "=ris", "ris$", "nudler", "mel$", "hvedemel", "sukker", "olie", "ketchup",
        "sauce", "dressing", "mayonnaise", "remoulade", "sennep", "konserves", "müsli", "musli", "granola",
        "cornflakes", "havregryn", "morgenmad", "krydderi", "bouillon", "suppe", "pesto", "pizza", "lasagne",
        "færdigret", "frost", "frossen", "fritter", "pommes", "bønner", "kikærter", "linser", "marmelade",
        "syltetøj", "nutella", "honning", "peanutbutter", "jordnøddesmør", "eddike", "salt$", "dåse", "taco"]),
]
CATEGORY_NAMES = {key: name for key, name, _ in CATEGORIES} | {"protein": "Protein", "nonfood": "Non-food"}
NONFOOD_CATALOG = ("nonfood", "non-food", "legetøj", "trend", "prosonic", "elektronik", "bolig", "have")


def _term_re(term: str) -> str:
    if term.startswith("="):
        return rf"(?<![a-z0-9æøå]){re.escape(term[1:])}(?![a-z0-9æøå])"
    if term.endswith("$"):
        return rf"{re.escape(term[:-1])}(?![a-z0-9æøå])"
    return re.escape(term)


def _build_category_res():
    return [(key, re.compile("|".join(_term_re(t) for t in terms))) for key, _, terms in CATEGORIES]


_CATEGORY_RES = _build_category_res()


def categorize(heading: str, catalog_label: str = "") -> list[str]:
    """Return e.g. ['dairy', 'protein']. Offers from non-food fliers are 'nonfood'."""
    text = " " + heading.lower().replace("-", " ") + " "
    cats: list[str] = []
    label = catalog_label.lower()
    if any(w in label for w in NONFOOD_CATALOG):
        cats.append("nonfood")
    else:
        for key, rx in _CATEGORY_RES:
            if rx.search(text):
                cats.append(key)
                break
    if "protein" in text:
        cats.append("protein")
    return cats


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
    if unit == "pcs":  # the size is itself a piece count ("1 pcs" on most non-weighed items)
        if lo and (lo > 1 or (hi and hi > 1)):
            parts.append(f"{lo:g} stk" if not hi or hi == lo else f"{lo:g}-{hi:g} stk")
        lo = None
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
        "imageLarge": images.get("zoom") or images.get("view"),
        "catalogId": offer.get("catalog_id"),
        "page": offer.get("catalog_page"),
        "cats": categorize(heading, offer.get("_catalog_label") or ""),
    }


# ---------------------------------------------------------------- English names
# Product names are translated once per night here, so the app can switch to English without
# any API key or network call on the phone. Google's free web endpoint takes a batch of lines
# joined by newlines and keeps the line breaks, so one request translates ~100 names.
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATE_BATCH_CHARS = 3500
# Store and own-brand names the translator would otherwise turn into words ("Netto" -> "Net",
# "Løgismose" -> "Onion mash"). They are swapped for placeholders like "BX0" while translating.
KEEP_WORDS = ["Netto", "Løgismose", "Princip", "Premieur", "Xtra!", "Xtra", "Änglamark", "Salling", "Coop",
              "Bilka", "SuperBrugsen", "Brugsen", "365discount", "Kærgården", "Gestus", "Harmonie", "Irma",
              "Galbani", "Graasten", "Thise", "Naturmælk", "Øllingegaard", "Rynkeby", "Tulip", "Steff Houlberg"]
_KEEP_RE = re.compile("|".join(rf"(?<![\wæøå]){re.escape(w)}(?![\wæøå])" for w in KEEP_WORDS), re.IGNORECASE)


def _protect(line: str) -> tuple[str, list[str]]:
    kept: list[str] = []

    def sub(m: re.Match) -> str:
        kept.append(m.group(0))
        return f"BX{len(kept) - 1}"
    return _KEEP_RE.sub(sub, line), kept


def _restore(line: str, kept: list[str]) -> str | None:
    for i in reversed(range(len(kept))):
        if f"BX{i}" not in line:
            return None
        line = line.replace(f"BX{i}", kept[i])
    return line


def _translate_batch(lines: list[str]) -> list[str] | None:
    protected = [_protect(line) for line in lines]
    body = urllib.parse.urlencode({"q": "\n".join(p for p, _ in protected)}).encode()
    params = urllib.parse.urlencode({"client": "gtx", "sl": "da", "tl": "en", "dt": "t"})
    req = urllib.request.Request(f"{TRANSLATE_URL}?{params}", data=body,
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.load(res)
            text = "".join(seg[0] for seg in data[0] if seg and isinstance(seg[0], str))
            out = [line.strip() for line in text.split("\n")]
            if len(out) != len(lines):
                return None
            return [_restore(en, kept) or "" for en, (_, kept) in zip(out, protected)]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, TypeError, IndexError) as exc:
            print(f"warning: translation request failed: {exc}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return None


def translate_names(names: list[str], known: dict[str, str]) -> dict[str, str]:
    """Return {danish name: english name} for every name that could be translated.

    `known` holds last night's translations, so only new names are sent. A batch whose line
    count comes back wrong is retried one name at a time; failures just keep the Danish name."""
    result = {n: known[n] for n in names if n in known}
    todo = [n for n in dict.fromkeys(names) if n not in result and "\n" not in n]
    batches, cur, size = [], [], 0
    for n in todo:
        if cur and size + len(n) > TRANSLATE_BATCH_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append(n)
        size += len(n) + 1
    if cur:
        batches.append(cur)
    failed = 0
    for batch in batches:
        out = _translate_batch(batch)
        if out is None:
            out = [(_translate_batch([n]) or [""])[0] for n in batch] if len(batch) > 1 else [""]
        for da, en in zip(batch, out):
            if en:
                result[da] = en
            else:
                failed += 1
        time.sleep(0.3)
    print(f"translated {len(todo) - failed} new names ({len(result)} total, {failed} failed)", file=sys.stderr)
    return result


def load_known_translations(path: str | None) -> dict[str, str]:
    """English names from a previous offers.json (the one currently published)."""
    if not path:
        return {}
    try:
        offers = json.loads(Path(path).read_text(encoding="utf-8")).get("offers", [])
    except (OSError, ValueError, AttributeError) as exc:
        print(f"note: no previous translations ({exc})", file=sys.stderr)
        return {}
    return {o["heading"]: o["headingEn"] for o in offers if isinstance(o, dict) and o.get("headingEn") and o.get("heading")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "offers.json"))
    ap.add_argument("--previous", help="earlier offers.json whose English names are reused instead of re-translated")
    ap.add_argument("--no-translate", action="store_true", help="skip the English names")
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

    if not args.no_translate:
        english = translate_names([o["heading"] for o in offers_out], load_known_translations(args.previous))
        for o in offers_out:
            en = english.get(o["heading"])
            if en and en != o["heading"]:
                o["headingEn"] = en

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": {"name": "Odense", "lat": LAT, "lng": LNG, "radius": RADIUS_M},
        "stores": stores_out,
        "categories": [{"key": k, "name": n} for k, n in CATEGORY_NAMES.items()],
        "offers": offers_out,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(offers_out)} offers to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
