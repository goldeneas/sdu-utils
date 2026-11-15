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
USER_AGENT = "sdu-utils-flier-summary/1.0 (+https://github.com/goldeneas/sdu-utils)"
MAX_PAGE_BYTES = 5 * 1024 * 1024
# Keep capture metadata useful without retaining cookies or other session headers.
CAPTURE_HEADERS = ("Content-Type", "Date", "Age", "Cache-Control", "Last-Modified", "ETag")


def fetch_public_html(url: str) -> tuple[str, dict, str]:
    """Read a public page anonymously using the collector's normal HTTP client."""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html", "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status {response.status}")
        if response.headers.get_content_type() != "text/html":
            raise RuntimeError("source did not return HTML")
        body = response.read(MAX_PAGE_BYTES + 1)
        if not body or len(body) > MAX_PAGE_BYTES:
            raise RuntimeError("source returned empty or oversized HTML")
        html = body.decode(response.headers.get_content_charset() or "utf-8")
        headers = {key: response.headers[key] for key in CAPTURE_HEADERS if key in response.headers}
        return html, headers, response.geturl()


def validate_netto_capture(headers: dict, fetched_at: datetime) -> None:
    """A relative expiry needs a dated response from the same Copenhagen day."""
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise RuntimeError("Netto+ collection time has no timezone")
    if not headers.get("Date"):
        raise RuntimeError("Netto+ response has no HTTP Date for relative expiry")
    try:
        age = int(headers.get("Age", "0"))
        response_date = parsedate_to_datetime(headers["Date"])
        if response_date.tzinfo is None:
            raise ValueError("response date has no timezone")
        local_day = fetched_at.astimezone(COPENHAGEN).date()
        if response_date > fetched_at + timedelta(minutes=5):
            raise ValueError("response date is in the future")
        if (age < 0 or response_date.astimezone(COPENHAGEN).date() != local_day
                or (fetched_at - timedelta(seconds=age)).astimezone(COPENHAGEN).date() != local_day):
            raise RuntimeError("Netto+ page is too old to interpret relative expiry")
    except (ValueError, TypeError, OverflowError) as exc:
        raise RuntimeError(f"Netto+ invalid freshness headers: {exc}") from exc


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
PERSONAL_OFFER = re.compile(r"\b(?:personlig[et]?|kupon(?:er)?|coupon(?:s)?|personal(?:ised|ized)?)\b", re.I)


def parse_netto_plus(html: str, fetched_at: datetime) -> list[dict]:
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise RuntimeError("Netto+ collection time has no timezone")
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
        if PERSONAL_OFFER.search(text):
            raise RuntimeError(f"Netto+ personal coupon found in public offer cards: {heading}")
        price_match, expiry = PRICE.search(text), EXPIRY.search(text)
        if len(PRICE.findall(text)) != 1 or not expiry:
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
    try:
        html, headers, _ = fetch_public_html(NETTO_PLUS_URL)
        validate_netto_capture(headers, fetched_at)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"Netto+ fetch failed: {exc}") from exc
    return parse_netto_plus(html, fetched_at)
