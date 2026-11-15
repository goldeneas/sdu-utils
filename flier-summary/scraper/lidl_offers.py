"""Public weekly Lidl Plus cards embedded as JSON in the actual website HTML."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from member_offers import COPENHAGEN, PageParser, fetch_public_html

LIDL_HOME = "https://www.lidl.dk/"
LIDL_PLUS_URL = "https://www.lidl.dk/c/lidl-plus/s10013731"
CAMPAIGN_PATH = re.compile(r"/c/store/ugens-lidl-plus/a\d+")


def discover_lidl_campaign(html: str) -> str:
    parser = PageParser()
    parser.feed(html)
    urls = set()
    for node in parser.root.descendants():
        if node.tag != "a":
            continue
        url = urljoin(LIDL_HOME, node.attrs.get("href", ""))
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.netloc == "www.lidl.dk" and CAMPAIGN_PATH.fullmatch(parsed.path):
            urls.add("https://www.lidl.dk" + parsed.path)
    if len(urls) != 1:
        raise RuntimeError("Lidl Plus current public campaign link missing or ambiguous")
    return urls.pop()


def money(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1_000_000:
        raise RuntimeError("Lidl Plus invalid price")
    return value


def timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RuntimeError("Lidl Plus missing or invalid store validity")
    try:
        return datetime.fromtimestamp(value, COPENHAGEN)
    except (ValueError, OverflowError, OSError) as exc:
        raise RuntimeError("Lidl Plus invalid store validity") from exc


def parse_lidl_product(product: dict) -> dict | None:
    if not isinstance(product, dict):
        raise RuntimeError("Lidl Plus invalid product card")
    regions = product.get("regionsPrices")
    if not isinstance(regions, dict) or set(regions) != {"1"}:
        raise RuntimeError("Lidl Plus region prices missing or ambiguous")
    region = regions["1"]
    plus = region.get("currentLidlPlusPrice") if isinstance(region, dict) else None
    if not isinstance(plus, dict) or plus.get("lidlPlusText") != "Med Lidl Plus":
        raise RuntimeError("Lidl Plus product is not explicitly a public member price")
    price = plus.get("price")
    if not isinstance(price, dict) or price.get("currencyCode") != "DKK":
        raise RuntimeError("Lidl Plus missing DKK price")
    discount = price.get("discount") or {}
    if not isinstance(discount, dict):
        raise RuntimeError("Lidl Plus invalid price conditions")
    hints = [plus.get("highlightText") or "", discount.get("discountText") or ""]
    displayed = product.get("lidlPlus")
    if not isinstance(displayed, list) or len(displayed) != 1 or not isinstance(displayed[0], dict):
        raise RuntimeError("Lidl Plus displayed price missing or ambiguous")
    hints.append(displayed[0].get("highlightText") or "")
    if not all(isinstance(h, str) for h in hints):
        raise RuntimeError("Lidl Plus invalid price conditions")
    title = product.get("fullTitle")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("Lidl Plus missing product title")
    if re.search(r"\b(?:personlig[et]?|personal(?:ised|ized)?)\b", " ".join([title] + hints), re.I):
        raise RuntimeError("Lidl Plus personal offer found in public selection")
    # Coupon eligibility can depend on a person, a store or activation. A public
    # coupon advertisement does not establish a price available to every member.
    if re.search(r"kupon|coupon", " ".join(hints), re.I):
        return None
    value = money(price.get("price"))
    if (displayed[0].get("lidlPlusText") != "Med Lidl Plus"
            or not isinstance(displayed[0].get("price"), dict)
            or displayed[0]["price"].get("price") != value
            or price.get("variantsHaveDifferentPrices") is not False
            or discount.get("showFrom") or discount.get("showUpTo")):
        raise RuntimeError("Lidl Plus displayed price or variants are ambiguous")
    source_id = product.get("productId")
    if type(source_id) is not int or source_id <= 0 or product.get("timezoneId") != "Europe/Copenhagen":
        raise RuntimeError("Lidl Plus invalid product ID or timezone")
    start = timestamp(product.get("storeStartDate"))
    try:
        end = datetime.fromisoformat(price["endDate"].replace("Z", "+00:00"))
        if end.utcoffset() is None:
            raise ValueError("expiry has no timezone")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError("Lidl Plus missing or invalid member-price expiry") from exc
    end = end.astimezone(COPENHAGEN)
    if product.get("storeEndDate") is not None:
        end = min(end, timestamp(product["storeEndDate"]))
    if end < start:
        raise RuntimeError("Lidl Plus reversed validity dates")
    counts = {int(m[1]) for h in hints for m in re.finditer(r"Ta[´’']?\s*(\d+)\s*for", h, re.I)}
    if len(counts) > 1 or (counts and not 1 < next(iter(counts)) < 1000):
        raise RuntimeError("Lidl Plus ambiguous bundle quantity")
    if not counts and any(re.search(r"\bTa|\bfor\b", h, re.I) for h in hints):
        raise RuntimeError("Lidl Plus unreadable bundle conditions")
    count = next(iter(counts), 1)
    pack = (price.get("packaging") or {}).get("text", "")
    unit = (price.get("basePrice") or {}).get("text", "")
    if not isinstance(pack, str) or not isinstance(unit, str):
        raise RuntimeError("Lidl Plus invalid pack information")
    # Some cards already describe the whole bundle ("18 x 50 cl"); do not
    # multiply that amount again. Other cards describe one piece ("110 g").
    bundled_pack = re.match(rf"\s*{count}\s*[x×]\s*", pack, re.I) if count > 1 else False
    quantity = pack if count == 1 or bundled_pack else f"{count} stk." + (f" á {pack}" if pack else "")
    normal_price = region.get("currentPrice")
    normal = money(normal_price["price"]) if count == 1 and isinstance(normal_price, dict) and "price" in normal_price else None
    path = product.get("canonicalUrl")
    if not isinstance(path, str) or not re.fullmatch(r"/p/[^/?#]+/p\d+", path):
        raise RuntimeError("Lidl Plus invalid public product URL")
    image = product.get("image")
    if image is not None and (not isinstance(image, str) or not image.startswith("https://")):
        raise RuntimeError("Lidl Plus invalid product image")
    description = f"Lidl Plus: {count} stk. for {value:g} kr." if count > 1 else ""
    identity = json.dumps([source_id, value, normal, quantity, unit, description, start.isoformat(), end.isoformat()])
    return {
        "id": "lidl-plus:" + hashlib.sha256(identity.encode()).hexdigest()[:20],
        "store": "lidl", "heading": " ".join(title.split()).removeprefix("- "), "description": description,
        "price": value, "prePrice": None, "nonMemberPrice": normal, "nonMemberPriceIsUpperBound": False,
        "quantity": quantity, "unitPrice": unit, "from": start.isoformat(), "till": end.isoformat(),
        "image": image, "imageLarge": image, "membership": "Lidl Plus",
        "sourceKey": "lidl-plus", "sourceUrl": urljoin(LIDL_HOME, path), "sourceProductId": str(source_id),
    }


def parse_lidl_plus(html: str) -> list[dict]:
    parser = PageParser()
    parser.feed(html)
    nodes = list(parser.root.descendants())
    cards = [n for n in nodes if "ACampaignGrid__item" in n.attrs.get("class", "").split()]
    data_nodes = [n for n in nodes if "data-grid-data" in n.attrs]
    if not cards or len(cards) != len(data_nodes) or any("data-grid-data" not in n.attrs for n in cards):
        raise RuntimeError("Lidl Plus incomplete public product cards")
    offers, seen = [], set()
    for node in cards:
        try:
            product = json.loads(node.attrs["data-grid-data"])
            offer = parse_lidl_product(product)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError(f"Lidl Plus invalid product JSON: {exc}") from exc
        source_id = product.get("productId")
        if source_id in seen:
            raise RuntimeError("Lidl Plus duplicate product in public selection")
        seen.add(source_id)
        if offer is not None:
            offers.append(offer)
    if not offers:
        raise RuntimeError("Lidl Plus public selection contains no automatic member prices")
    return offers


def fetch_lidl_plus(fetched_at: datetime) -> list[dict]:
    try:
        home, _, _ = fetch_public_html(LIDL_HOME)
        url = discover_lidl_campaign(home)
        html, _, _ = fetch_public_html(url)
        return parse_lidl_plus(html)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"Lidl Plus collection failed: {exc}") from exc
