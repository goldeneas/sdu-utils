"""Experimental public Netto+ page importer (standard library only).

Opt-in until the HTML parser has been checked against a live page capture.
The public page is a selection, not a promise of complete app coverage.
"""
from __future__ import annotations

import hashlib
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

NETTO_PLUS_URL = "https://netto.dk/netto-plus/"
MEMBER_MARKER = "Kun med Netto+ appen"
COPENHAGEN = ZoneInfo("Europe/Copenhagen")


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def descendants(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()


class PageParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not any(n.tag in {"script", "style", "template", "noscript"} for n in self.stack):
            self.stack[-1].children.append(data)


# Only accept an explicitly labelled comparison price, an unambiguous offer price,
# and an expiry. A markup change must fail the source rather than guess a price.
PRICE = re.compile(r"Ikke-medlemspris op til\s+(\d+(?:[,.]\d{1,2})?)\s+(\d+(?:\s*[,]\s*\d{1,2})?)\s*\.?\s*[-–](?=\s|$)")
EXPIRY = re.compile(r"Udløber\s+(?:om\s+(\d+)\s+dag(?:e)?|(?:i\s*)?dag)\b", re.I)


def parse_netto_plus(html: str, fetched_at: datetime) -> list[dict]:
    parser = PageParser()
    parser.feed(html)
    badge_count = parser.root.text().count(MEMBER_MARKER)
    if not badge_count:
        raise RuntimeError("Netto+ offer badges not found; page format or availability changed")

    cards = []

    def visit(node):
        found = False
        for child in node.children:
            if isinstance(child, Node):
                found = visit(child) or found
        if found:
            return True
        text = node.text()
        headings = [n.text() for n in node.descendants() if re.fullmatch(r"h[1-6]", n.tag) and n.text()]
        if MEMBER_MARKER in text and len(headings) == 1 and len(EXPIRY.findall(text)) == 1:
            cards.append((node, headings[0], text))
            return True
        return False

    visit(parser.root)
    if len(cards) != badge_count:
        raise RuntimeError("Netto+ incomplete offer cards; refusing a partial import")

    offers = {}
    for node, heading, text in cards:
        price_match, expiry = PRICE.search(text), EXPIRY.search(text)
        if not price_match or not expiry:
            raise RuntimeError(f"Netto+ price or expiry could not be read for {heading}")
        non_member, price = (float(re.sub(r"\s+", "", p).replace(",", ".")) for p in price_match.groups())
        days = int(expiry[1] or 0)
        if not all(math.isfinite(p) for p in (price, non_member)) or price <= 0 or non_member < price or not 0 <= days <= 60:
            raise RuntimeError(f"Netto+ invalid price or expiry for {heading}")
        expiry_day = fetched_at.astimezone(COPENHAGEN).date() + timedelta(days=days)
        till = datetime.combine(expiry_day, time(23, 59, 59), COPENHAGEN).isoformat()
        # Exclude the changing countdown from the identity, but keep pack sizes
        # and purchase limits: two variants must not overwrite one another.
        description = PRICE.sub("", EXPIRY.sub("", text)).replace(MEMBER_MARKER, "", 1).replace(heading, "", 1)
        description = " ".join(description.split())
        identity = f"{heading}|{description}|{price}|{non_member}|{till}"
        offer_id = "netto-plus:" + hashlib.sha256(identity.encode()).hexdigest()[:20]
        images = [n.attrs.get("src") or n.attrs.get("data-src") for n in node.descendants() if n.tag == "img"]
        image = next((url for url in images if url and url.startswith("https://")), None)
        # Keep pack sizes, limits and conditions searchable, without repeating
        # the title, price and expiry that the app already displays.
        offers[offer_id] = {
            "id": offer_id, "store": "netto", "heading": heading, "description": description,
            "price": price, "prePrice": None, "nonMemberPrice": non_member,
            "quantity": "", "unitPrice": "", "from": None, "till": till,
            "image": image, "imageLarge": image, "membership": "Netto+",
            "sourceKey": "netto-plus", "sourceUrl": NETTO_PLUS_URL,
        }
    return list(offers.values())


def fetch_netto_plus(fetched_at: datetime) -> list[dict]:
    request = urllib.request.Request(NETTO_PLUS_URL, headers={
        "User-Agent": "sdu-utils-flier-summary/1.0 (+https://github.com/goldeneas/sdu-utils)",
        "Accept": "text/html", "Cache-Control": "no-cache",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if "text/html" not in response.headers.get("Content-Type", ""):
                raise RuntimeError("Netto+ did not return HTML")
            # Even a short-lived cache may cross local midnight. Interpret a
            # relative expiry only when the response originated on today's date.
            age = int(response.headers.get("Age", "0"))
            response_date = parsedate_to_datetime(response.headers["Date"]) if response.headers.get("Date") else fetched_at
            if response_date.tzinfo is None:
                raise RuntimeError("Netto+ response date has no timezone")
            rendered_at = min(response_date, fetched_at - timedelta(seconds=age))
            if age < 0 or rendered_at.astimezone(COPENHAGEN).date() != fetched_at.astimezone(COPENHAGEN).date():
                raise RuntimeError("Netto+ page is too old to interpret relative expiry")
            html = response.read().decode(response.headers.get_content_charset() or "utf-8")
    except (urllib.error.URLError, TimeoutError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"Netto+ fetch failed: {exc}") from exc
    return parse_netto_plus(html, fetched_at)
