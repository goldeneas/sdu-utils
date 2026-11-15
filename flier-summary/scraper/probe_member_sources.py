#!/usr/bin/env python3
"""Check anonymous member-source access and retain HTML for offline inspection.

This is a diagnostic, not an offer feed or a deployment command. Bilka HTML
access alone does not establish product coverage, prices or public API access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from member_offers import (
    NETTO_PLUS_URL, fetch_public_html, parse_netto_plus, validate_netto_capture,
)
from bilka_offers import BILKA_SEARCH_URL, BILKA_STORE, fetch_bilka_page, fetch_bilka_plus

SOURCES = (
    ("netto-plus", NETTO_PLUS_URL),
    ("bilka-plus", "https://www.bilka.dk/plus/"),
    ("bilkatogo", "https://www.bilkatogo.dk/"),
    ("bilkatogo-plus", "https://www.bilkatogo.dk/inspiration/om-bilka-togo/bilka-plus-koncept/"),
    ("bilkatogo-selection", "https://www.bilkatogo.dk/s?query=plus"),
)


def probe_source(key: str, url: str, directory: Path) -> dict:
    checked_at = datetime.now(timezone.utc)
    result = {"key": key, "url": url, "checkedAt": checked_at.isoformat(timespec="seconds")}
    try:
        html, headers, final_url = fetch_public_html(url)
    except urllib.error.HTTPError as exc:
        result.update(status="http-error", httpStatus=exc.code, error=str(exc))
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        # CONNECT denials have no origin HTTP response. Do not label the site
        # itself as returning 403 or suggest a different route around the proxy.
        status = "proxy-denied" if "tunnel connection failed: 403" in reason.lower() else "connection-error"
        result.update(status=status, error=reason)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        result.update(status="error", error=str(exc))
    else:
        filename = f"{key}.html"
        body = html.encode("utf-8")
        (directory / filename).write_bytes(body)
        result.update(status="ok", httpStatus=200, finalUrl=final_url,
                      headers=headers, html=filename, encoding="utf-8",
                      sha256=hashlib.sha256(body).hexdigest())
        if key == "netto-plus":
            try:
                validate_netto_capture(headers, checked_at)
                offers = parse_netto_plus(html, checked_at)
                result["nettoValidation"] = {"status": "ok", "offerCount": len(offers)}
            except RuntimeError as exc:
                # Retain a genuine capture even when markup or dates fail
                # validation; it is evidence for fixing the parser, not a feed.
                result["nettoValidation"] = {"status": "error", "error": str(exc)}
    return result


def probe_bilka_products(directory: Path) -> dict:
    """Capture public search responses before validation; never write an offer feed."""
    checked_at = datetime.now(timezone.utc)
    result = {"key": "bilka-products", "url": BILKA_SEARCH_URL,
              "checkedAt": checked_at.isoformat(timespec="seconds"),
              "storeId": BILKA_STORE, "pages": []}

    def capture(page):
        data = fetch_bilka_page(page)
        filename = f"bilka-products-page-{page}.json"
        body = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (directory / filename).write_bytes(body)
        result["pages"].append({"page": page, "json": filename,
                                "sha256": hashlib.sha256(body).hexdigest()})
        return data

    try:
        offers = fetch_bilka_plus(checked_at, page_fetcher=capture)
    except (RuntimeError, OSError, ValueError) as exc:
        result.update(status="error", error=str(exc))
    else:
        result.update(status="ok", offerCount=len(offers))
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", required=True, help="new directory for report.json and UTF-8 HTML captures")
    ap.add_argument("--bilka-products", action="store_true", help="also capture and validate every public Bilka Plus search page for Odense")
    args = ap.parse_args(argv)
    directory = Path(args.out_dir)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        ap.error(f"cannot create a new capture directory: {exc}")
    report = {"schemaVersion": 1, "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "purpose": "anonymous-access-and-html-inspection", "sources": []}
    for key, url in SOURCES:
        result = probe_source(key, url, directory)
        report["sources"].append(result)
        print(f"{key}: {result['status']}", file=sys.stderr)
    if args.bilka_products:
        result = probe_bilka_products(directory)
        report["sources"].append(result)
        print(f"bilka-products: {result['status']}", file=sys.stderr)
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return int(any(source["status"] != "ok" or source.get("nettoValidation", {}).get("status") == "error"
                   for source in report["sources"]))


if __name__ == "__main__":
    sys.exit(main())
