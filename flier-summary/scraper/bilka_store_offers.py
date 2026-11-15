"""Confirmed BilkaToGo promotions outside fliers, without assuming Plus eligibility.

Browse uses the website's public read-only browse key and cursor protocol. The
ordinary search has a 1,000-result window and cannot enumerate this selection.
Undated prices are observations, never offers with an invented expiry.
The broad isInOffer selection and a lower catalog reference are not evidence
of a promotion: require an explicit store before-price or a saving mix deal.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, time

from bilka_offers import ALGOLIA_APP, ALGOLIA_INDEX, BILKA_STORE
from member_offers import COPENHAGEN, MAX_PAGE_BYTES, USER_AGENT

BILKA_STORE_URL = "https://www.bilkatogo.dk/s?offer=true"
BROWSE_URL = f"https://{ALGOLIA_APP}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/browse"
# Public, read-only key embedded in BilkaToGo's website client, not a user token.
BROWSE_KEY = "b03ff911ddd193e130b5a65631a3d604"
PAGE_SIZE = 500
MAX_PAGES = 128
PROMOTION_EVIDENCE = frozenset({"store-before-price", "mix-total", "buy-pay"})
FIELDS = ["objectID", "name", "brand", "subBrand", "description", "netcontent",
          f"storeData.{BILKA_STORE}", "images", "isInOffer", "nonsearchable"]


def is_confirmed_store_offer(offer: dict) -> bool:
    """Legacy snapshots used catalog-reference reductions; never reuse those."""
    return (offer.get("sourceKey") == "bilkatogo-offers" and offer.get("store") == "bilka"
            and offer.get("promotionEvidence") in PROMOTION_EVIDENCE)


def positive_integer(value, field):
    if type(value) is not int or not 0 < value <= 2**53 - 1:
        raise RuntimeError(f"BilkaToGo invalid {field}")
    return value


def fetch_store_page(cursor: str | None = None) -> dict:
    params = {"filters": f"isInOffer:{BILKA_STORE} AND nonsearchable:false AND isInAssortmentIn:{BILKA_STORE}",
              "hitsPerPage": PAGE_SIZE, "attributesToRetrieve": json.dumps(FIELDS)}
    if cursor is not None:
        params["cursor"] = cursor
    request = urllib.request.Request(BROWSE_URL + "?" + urllib.parse.urlencode(params), headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        "X-Algolia-Application-Id": ALGOLIA_APP, "X-Algolia-API-Key": BROWSE_KEY,
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise RuntimeError("BilkaToGo browse did not return JSON")
            body = response.read(MAX_PAGE_BYTES + 1)
            if not body or len(body) > MAX_PAGE_BYTES:
                raise RuntimeError("BilkaToGo browse returned empty or oversized JSON")
            data = json.loads(body)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"BilkaToGo browse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("BilkaToGo browse response is not an object")
    return data


def explicit_date(value, *, end=False):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RuntimeError("BilkaToGo invalid offer date")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.combine(date.fromisoformat(value), time(23, 59, 59) if end else time.min, COPENHAGEN)
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError("date has no timezone")
        return result.astimezone(COPENHAGEN)
    except ValueError as exc:
        raise RuntimeError("BilkaToGo unreadable offer date") from exc


def parse_store_product(product: dict, fetched_at: datetime) -> list[dict]:
    if not isinstance(product, dict) or product.get("nonsearchable") is not False:
        raise RuntimeError("BilkaToGo product is not publicly searchable")
    source_id = product.get("objectID")
    if not isinstance(source_id, str) or not re.fullmatch(r"\d+", source_id):
        raise RuntimeError("BilkaToGo invalid product ID")
    promoted_stores = product.get("isInOffer")
    if not isinstance(promoted_stores, list) or BILKA_STORE not in [str(s) for s in promoted_stores]:
        raise RuntimeError("BilkaToGo product is not in Odense's public promotion selection")
    stores = product.get("storeData")
    store = stores.get(BILKA_STORE) if isinstance(stores, dict) else None
    if not isinstance(store, dict):
        raise RuntimeError("BilkaToGo missing Odense price")
    current = positive_integer(store.get("price"), "ordinary store price")
    before = store.get("beforePrice", 0)
    if type(before) is not int or before < 0:
        raise RuntimeError("BilkaToGo invalid comparison price")
    if before:
        positive_integer(before, "comparison price")
    pack = product.get("netcontent", "")
    title = product.get("name")
    brand, sub_brand = product.get("brand", ""), product.get("subBrand", "")
    if not all(isinstance(t, str) for t in (title, brand, sub_brand, pack)) or not title.strip():
        raise RuntimeError("BilkaToGo missing product text")
    title = " ".join(title.split())
    if sub_brand.strip() and sub_brand.casefold() not in title.casefold():
        title = f"{sub_brand.strip()} {title}"
    if brand.strip() and not title.casefold().startswith(brand.strip().casefold()):
        title = f"{brand.strip()} {title}"
    start = explicit_date(store.get("offerFrom"))
    end = explicit_date(store.get("offerUntil"), end=True)
    if start and end and end < start:
        raise RuntimeError("BilkaToGo reversed offer dates")
    images = product.get("images", [])
    if not isinstance(images, list) or any(not isinstance(u, str) for u in images):
        raise RuntimeError("BilkaToGo invalid product images")
    image = next((u for u in images if u.startswith("https://")), None)
    conditions = store.get("offerMaxDescription") or ""
    if not isinstance(conditions, str):
        raise RuntimeError("BilkaToGo invalid purchase conditions")
    variants = []
    # Root product.price is a catalog reference, not a historical before-price.
    # Neither "Skarp pris", "Se Her", dates nor isInOffer alone prove a saving.
    if before > current:
        variants.append((current, pack, conditions, "store-before-price", before / 100))
    group = store.get("multipromo")
    if group not in (None, "", 0, "0"):
        count = positive_integer(store.get("offerCount"), "mix quantity")
        value = store.get("multiPromoPrice")
        buy_pay = re.fullmatch(r"(\d+) for (\d+)", store.get("offerDescription", ""))
        if value in (None, "") and buy_pay and int(buy_pay[1]) == count and 0 < int(buy_pay[2]) < count:
            # Mixed-price "3 for 2" groups do not expose a fixed bundle total.
            variants.append((None, f"{count} stk." + (f" á {pack}" if pack else ""),
                             f"{buy_pay[0]}. " + conditions, "buy-pay", None))
            value = None
        elif isinstance(value, str) and re.fullmatch(r"\d+", value):
            value = int(value)
        elif value is None:
            raise RuntimeError("BilkaToGo missing mix total or readable promotion conditions")
        if count <= 1:
            raise RuntimeError("BilkaToGo invalid mix conditions")
        if value is not None:
            total = positive_integer(value, "mix total")
            if total < current * count:
                variants.append((total, f"{count} stk." + (f" á {pack}" if pack else ""),
                                 f"Mix {count} for {total / 100:g} kr. " + conditions, "mix-total", None))
    unit = store.get("unitsOfMeasurePriceUnit", "")
    per_unit = store.get("unitsOfMeasureShowPrice")
    unit_price = f"{per_unit / 100:g} kr/{unit.rstrip('.').lower()}" if type(per_unit) is int and per_unit > 0 and isinstance(unit, str) and unit else ""
    result = []
    for minor, quantity, condition, evidence, pre_price in variants:
        description = " ".join([condition, "BilkaToGo · Bilka Odense, Niels Bohrs Alle 150."]).strip()
        identity = json.dumps([source_id, minor, quantity, description, start.isoformat() if start else None, end.isoformat() if end else None])
        result.append({
            "id": "bilkatogo-offers:" + hashlib.sha256(identity.encode()).hexdigest()[:20],
            "store": "bilka", "heading": title, "description": description,
            "price": minor / 100 if minor is not None else None, "prePrice": pre_price, "quantity": quantity,
            "unitPrice": unit_price if evidence == "store-before-price" else "",
            "from": start.isoformat() if start else None, "till": end.isoformat() if end else None,
            "priceObservedAt": fetched_at.isoformat(timespec="seconds"),
            "image": image, "imageLarge": image, "sourceKey": "bilkatogo-offers",
            "sourceUrl": BILKA_STORE_URL, "sourceProductId": source_id,
            "promotionEvidence": evidence,
        })
    return result


def fetch_bilka_store_offers(fetched_at: datetime, *, page_fetcher=None) -> list[dict]:
    if fetched_at.utcoffset() is None:
        raise RuntimeError("BilkaToGo collection time has no timezone")
    fetch = page_fetcher or fetch_store_page
    cursor, cursors, ids, offers = None, set(), set(), []
    for _ in range(MAX_PAGES):
        data = fetch(cursor)
        hits = data.get("hits")
        if not isinstance(hits, list) or len(hits) > PAGE_SIZE:
            raise RuntimeError("BilkaToGo invalid browse page")
        for product in hits:
            try:
                parsed = parse_store_product(product, fetched_at)
            except (ValueError, TypeError, OverflowError) as exc:
                raise RuntimeError(f"BilkaToGo invalid promotion fields: {exc}") from exc
            source_id = product["objectID"]
            if source_id in ids:
                raise RuntimeError("BilkaToGo duplicate product during pagination")
            ids.add(source_id)
            offers.extend(parsed)
        cursor = data.get("cursor")
        if cursor is None:
            if not ids:
                raise RuntimeError("BilkaToGo public promotion selection unexpectedly empty")
            return offers
        if not isinstance(cursor, str) or not cursor or cursor in cursors or not hits:
            raise RuntimeError("BilkaToGo invalid or repeated browse cursor")
        cursors.add(cursor)
    raise RuntimeError("BilkaToGo browse limit reached; refusing partial promotion feed")
