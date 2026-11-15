"""Anonymous BilkaToGo Plus search, scoped to the verified Bilka Odense store.

The public search client and fields were inspected on 2026-11-15. This is an
undocumented website API, not the personalized coupon or authenticated cart API.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, time

from member_offers import COPENHAGEN, MAX_PAGE_BYTES, PERSONAL_OFFER, USER_AGENT

BILKA_PLUS_URL = "https://www.bilkatogo.dk/s?query=plus"
# Public, search-only website credentials; no user token or cookie is needed.
ALGOLIA_APP = "F9VBJLR1BK"
ALGOLIA_SEARCH_KEY = "1deaf41c87e729779f7695c00f190cc9"
ALGOLIA_INDEX = "prod_BILKATOGO_PRODUCTS"
BILKA_SEARCH_URL = f"https://{ALGOLIA_APP}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}"
BILKA_STORE = "1654"  # AvailableDeliveryAddresses: Bilka Odense, Niels Bohrs Alle 150
PAGE_SIZE = 100
MAX_RESULTS = 1000
PRODUCT_FIELDS = [
    "objectID", "name", "brand", "subBrand", "description", "netcontent", "units", "unitsOfMeasure",
    "storeData", "images", "nonsearchable", "cpOffer", "cpOfferPrice", "cpOfferAmount",
    "cpOfferId", "cpOfferFromDate", "cpOfferToDate",
]


def fetch_bilka_page(page: int) -> dict:
    params = {
        "query": "", "filters": f"cpOffer:true AND nonsearchable:false AND isInAssortmentIn:{BILKA_STORE}",
        "page": page, "hitsPerPage": PAGE_SIZE,
        "attributesToRetrieve": json.dumps(PRODUCT_FIELDS), "attributesToHighlight": "[]",
        "analytics": "false", "clickAnalytics": "false",
    }
    url = BILKA_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        "X-Algolia-Application-Id": ALGOLIA_APP, "X-Algolia-API-Key": ALGOLIA_SEARCH_KEY,
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise RuntimeError("Bilka Plus search did not return JSON")
            body = response.read(MAX_PAGE_BYTES + 1)
            if not body or len(body) > MAX_PAGE_BYTES:
                raise RuntimeError("Bilka Plus search returned empty or oversized JSON")
            data = json.loads(body)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"Bilka Plus search failed: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Bilka Plus search response is not an object")
    return data


def positive_integer(value, field: str) -> int:
    # The public JavaScript client uses Number; reject values outside its exact
    # integer range instead of letting malformed prices overflow normalization.
    if type(value) is not int or not 0 < value <= 2**53 - 1:
        raise RuntimeError(f"Bilka Plus invalid {field}")
    return value


def parse_bilka_product(product: dict) -> dict:
    """Convert the site's public cpOffer fields; monetary values are in øre."""
    if not isinstance(product, dict) or product.get("cpOffer") is not True or product.get("nonsearchable") is not False:
        raise RuntimeError("Bilka Plus result is not an explicitly public Plus product")
    product_id = product.get("objectID")
    if not isinstance(product_id, str) or not re.fullmatch(r"[0-9]+", product_id):
        raise RuntimeError("Bilka Plus invalid product ID")
    name = product.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError("Bilka Plus missing product name")
    price_minor = positive_integer(product.get("cpOfferPrice"), "price")
    amount = positive_integer(product.get("cpOfferAmount"), "quantity")
    promotion = positive_integer(product.get("cpOfferId"), "promotion ID")
    dates = []
    for field in ("cpOfferFromDate", "cpOfferToDate"):
        value = product.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise RuntimeError(f"Bilka Plus missing or invalid {field}")
        try:
            dates.append(date.fromisoformat(value))
        except ValueError as exc:
            raise RuntimeError(f"Bilka Plus invalid {field}") from exc
    if dates[0] > dates[1]:
        raise RuntimeError("Bilka Plus reversed validity dates")
    stores = product.get("storeData")
    store = stores.get(BILKA_STORE) if isinstance(stores, dict) else None
    if not isinstance(store, dict):
        raise RuntimeError("Bilka Plus product has no Odense store data")
    regular_minor = positive_integer(store.get("price"), "non-member price")
    brand = product.get("brand", "")
    sub_brand = product.get("subBrand", "")
    description = product.get("description", "")
    pack = product.get("netcontent", "")
    if not all(isinstance(v, str) for v in (brand, sub_brand, description, pack)):
        raise RuntimeError("Bilka Plus invalid product text")
    if PERSONAL_OFFER.search(f"{name} {description}"):
        raise RuntimeError("Bilka Plus personal coupon found in public results")
    heading = " ".join(name.split())
    if sub_brand.strip() and sub_brand.casefold() not in heading.casefold():
        heading = f"{sub_brand.strip()} {heading}"
    if brand and not heading.casefold().startswith(brand.casefold()):
        heading = f"{brand} {heading}"
    conditions = [description.strip()] if description.strip() != name.strip() else []
    if amount > 1:
        conditions.append(f"Plus Mix {amount} for {price_minor / 100:g} kr.")
    conditions.append("BilkaToGo · Bilka Odense, Niels Bohrs Alle 150.")
    # Do not confuse a pack's ordinary price with the price of a mix bundle.
    non_member = regular_minor / 100 if amount == 1 else None
    quantity = pack.strip() if amount == 1 else f"{amount} stk." + (f" á {pack.strip()}" if pack.strip() else "")
    images = product.get("images", [])
    if not isinstance(images, list) or any(not isinstance(i, str) for i in images):
        raise RuntimeError("Bilka Plus invalid product images")
    image = next((i for i in images if i.startswith("https://")), None)
    start = datetime.combine(dates[0], time.min, COPENHAGEN).isoformat()
    till = datetime.combine(dates[1], time(23, 59, 59), COPENHAGEN).isoformat()
    description = " ".join(conditions)
    identity = json.dumps([product_id, promotion, price_minor, amount, quantity, description, start, till, regular_minor], ensure_ascii=False)
    return {
        "id": "bilka-plus:" + hashlib.sha256(identity.encode()).hexdigest()[:20],
        "store": "bilka", "heading": heading, "description": description,
        "price": price_minor / 100, "prePrice": None, "nonMemberPrice": non_member,
        "quantity": quantity, "unitPrice": "", "from": start, "till": till,
        "image": image, "imageLarge": image, "membership": "Bilka Plus",
        "sourceKey": "bilka-plus", "sourceUrl": BILKA_PLUS_URL,
        "sourceProductId": product_id,
    }


def fetch_bilka_plus(fetched_at: datetime, *, page_fetcher=None) -> list[dict]:
    """Reject partial, truncated, duplicated or changing search windows as a whole."""
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise RuntimeError("Bilka Plus collection time has no timezone")
    products, seen = [], set()
    fetch_page = page_fetcher or fetch_bilka_page
    expected = None
    page = 0
    while True:
        data = fetch_page(page)
        total, pages = data.get("nbHits"), data.get("nbPages")
        if (type(total) is not int or type(pages) is not int or not 0 <= total < MAX_RESULTS
                or pages != (total + PAGE_SIZE - 1) // PAGE_SIZE
                or type(data.get("page")) is not int or data["page"] != page
                or type(data.get("hitsPerPage")) is not int or data["hitsPerPage"] != PAGE_SIZE
                or data.get("exhaustiveNbHits") is not True):
            raise RuntimeError("Bilka Plus incomplete or invalid search pagination")
        if expected is None:
            expected = (total, pages)
        if expected != (total, pages):
            raise RuntimeError("Bilka Plus search changed during pagination")
        hits = data.get("hits")
        if not isinstance(hits, list) or len(hits) != min(PAGE_SIZE, total - page * PAGE_SIZE):
            raise RuntimeError("Bilka Plus missing search results")
        for product in hits:
            offer = parse_bilka_product(product)
            product_id = product["objectID"]
            if product_id in seen:
                raise RuntimeError("Bilka Plus duplicate product across search pages")
            seen.add(product_id)
            products.append(offer)
        page += 1
        if page >= pages:
            return products
