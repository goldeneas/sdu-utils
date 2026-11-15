"""Public, anonymous Coop member selections, mapped by their actual chain logos."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from datetime import date, datetime, time, timedelta

from member_offers import COPENHAGEN, PageParser, fetch_public_html, validate_netto_capture

COOP_MEMBERS_URL = "https://medlem.coop.dk/medlemsfordele/medlemstilbud/medlemstilbud/"
CHAIN_LOGOS = {"365discount": "/assets/images/chain/logo-365-big.png",
               "superbrugsen": "/assets/images/chain/logo-superbrugsen.png"}
MONTHS = {name: i + 1 for i, name in enumerate(
    ("jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"))}


def has_class(node, name):
    return name in node.attrs.get("class", "").split()


def own_text(node):
    # Coop omits closing </p> tags. Direct text avoids accidentally including
    # the following image, prices or amount nested by HTMLParser in that p.
    return " ".join(" ".join(c for c in node.children if isinstance(c, str)).split())


def field(card, name, *, optional=False):
    nodes = [n for n in card.descendants() if has_class(n, name)]
    if optional and not nodes:
        return None
    if len(nodes) != 1:
        raise RuntimeError(f"Coop missing or ambiguous {name}")
    return nodes[0]


def coop_period(text, fetched_at):
    match = re.fullmatch(r"(\d{1,2})\.\s*(\w+)\.?\s*-\s*(\d{1,2})\.\s*(\w+)\.?", text)
    if not match or match[2].lower() not in MONTHS or match[4].lower() not in MONTHS:
        raise RuntimeError("Coop unreadable validity period")
    day = fetched_at.astimezone(COPENHAGEN).date()
    start_month, end_month = MONTHS[match[2].lower()], MONTHS[match[4].lower()]
    candidates = []
    for year in (day.year - 1, day.year, day.year + 1):
        try:
            start = date(year, start_month, int(match[1]))
            end = date(year + (end_month < start_month), end_month, int(match[3]))
        except ValueError:
            continue
        if (timedelta(0) <= end - start <= timedelta(days=62)
                and start <= day + timedelta(days=45) and end >= day - timedelta(days=45)):
            candidates.append((start, end))
    if len(candidates) != 1:
        raise RuntimeError("Coop validity year is ambiguous or too far from collection")
    start, end = candidates[0]
    return (datetime.combine(start, time.min, COPENHAGEN).isoformat(),
            datetime.combine(end, time(23, 59, 59), COPENHAGEN).isoformat())


def parse_coop_members(html: str, fetched_at: datetime, store: str) -> list[dict]:
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise RuntimeError("Coop collection time has no timezone")
    if store not in CHAIN_LOGOS:
        raise RuntimeError("Coop unsupported chain")
    parser = PageParser()
    parser.feed(html)
    chains = [n for n in parser.root.descendants() if has_class(n, "chain-wrapper")
              and any(c.tag == "img" and has_class(c, "chain-logo")
                      and urllib.parse.urlsplit(c.attrs.get("src", "")).path == CHAIN_LOGOS[store]
                      for c in n.descendants())]
    if len(chains) != 1:
        raise RuntimeError(f"Coop public selection for {store} not found or ambiguous")
    cards = [n for n in chains[0].descendants() if has_class(n, "personal-offer-wrapper")]
    if not cards:
        raise RuntimeError(f"Coop public selection for {store} contains no offer cards")
    offers, seen = [], set()
    for card in cards:
        anchors = [n for n in card.descendants() if "data-fancy-personal-offer" in n.attrs]
        if len(anchors) != 1 or anchors[0].attrs.get("data-offertype") != "2":
            raise RuntimeError("Coop card is not an explicitly public member offer")
        source_id = anchors[0].attrs["data-fancy-personal-offer"]
        if not re.fullmatch(r"[0-9]+", source_id) or source_id in seen:
            raise RuntimeError("Coop missing or duplicate offer ID")
        seen.add(source_id)
        heading = own_text(field(card, "offer-title"))
        if not heading or re.search(r"\b(?:personlig[et]?|kupon(?:er)?|personal|coupon)\b", heading, re.I):
            raise RuntimeError("Coop missing heading or personal coupon in public selection")
        start, till = coop_period(own_text(field(card, "valid-period")), fetched_at)
        price_node = field(card, "buy-price", optional=True)
        normal_node = field(card, "price-normal", optional=True)
        price, normal, upper = None, None, False
        if price_node is not None:
            whole = own_text(price_node)
            cents = [n.text() for n in price_node.descendants() if n.tag == "sup"]
            if not re.fullmatch(r"\d+", whole) or len(cents) != 1 or not re.fullmatch(r"\d{2}", cents[0]):
                raise RuntimeError("Coop missing or ambiguous fixed price")
            price = int(whole) + int(cents[0]) / 100
            if not 0 < price < 1_000_000:
                raise RuntimeError("Coop invalid fixed price")
            normal_text = own_text(normal_node) if normal_node is not None else ""
            comparison = re.fullmatch(r"Pris ikke-medlem( op til)? (\d+(?:,\d{2})?)", normal_text)
            if not comparison:
                raise RuntimeError("Coop missing or ambiguous non-member price")
            normal, upper = float(comparison[2].replace(",", ".")), bool(comparison[1])
            if normal <= 0:
                raise RuntimeError("Coop invalid non-member price")
        elif not re.fullmatch(r"Medlemsrabat [1-9]\d?\s*% på .+", heading, re.I) or normal_node is not None:
            raise RuntimeError("Coop card has neither a fixed price nor an explicit percentage promotion")
        amount_node = field(card, "item-amount", optional=True)
        amount = own_text(amount_node).removeprefix("-").strip() if amount_node else ""
        # Purchase quantities belong in the amount, not in the remembered
        # product name; otherwise "1 stk. Mou..." cannot match another store.
        purchase = re.fullmatch(r"(1 (?:pakke|stk\.)) (.+)", heading)
        if purchase:
            heading = purchase[2]
            amount = purchase[1] + (f" · {amount}" if amount else "")
        unit_node = field(card, "price-comparison", optional=True)
        unit = own_text(unit_node) if unit_node else ""
        images = [n.attrs.get("src", "") for n in card.descendants() if n.tag == "img"]
        image = next((u for u in images if u.startswith("https://")), None)
        key = f"coop-{store}"
        identity = json.dumps([source_id, heading, price, normal, upper, amount, unit, start, till], ensure_ascii=False)
        offers.append({
            "id": key + ":" + hashlib.sha256(identity.encode()).hexdigest()[:20],
            "store": store, "heading": heading, "description": heading if price is None else "",
            "price": price, "prePrice": None, "nonMemberPrice": normal,
            "nonMemberPriceIsUpperBound": upper, "quantity": amount, "unitPrice": unit,
            "from": start, "till": till, "image": image, "imageLarge": image,
            "membership": "Coop", "sourceKey": key, "sourceUrl": COOP_MEMBERS_URL,
            "sourceProductId": source_id,
        })
    return offers


def fetch_coop_members(store: str, fetched_at: datetime) -> list[dict]:
    try:
        html, headers, _ = fetch_public_html(COOP_MEMBERS_URL)
        # The year is omitted on these cards. Only a dated capture from the
        # collection day may anchor it; fallback retains the resolved dates.
        validate_netto_capture(headers, fetched_at)
        return parse_coop_members(html, fetched_at, store)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Coop {store}: {str(exc).replace('Netto+', 'Coop')}") from exc
