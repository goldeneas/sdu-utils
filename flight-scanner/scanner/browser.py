"""Build small browser indexes and bounded detail chunks; retain full scanner archives."""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

CHUNK_SIZE = 200


def write_json(path: Path, data, compressed=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    path.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0) if compressed else payload)


def build_scan(source: Path, root: Path, target: Path):
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()[:24]
    data = json.loads(gzip.decompress(source.read_bytes()) if source.suffix == ".gz" else source.read_bytes())
    complete = isinstance(data.get("flights"), list)
    if complete:
        flights = data["flights"]
    else:
        rows = data.get("top", []) + [f for rows in data.get("per_airport", {}).values() for f in rows]
        flights = list({json.dumps(f, sort_keys=True): f for f in rows}.values())
    bins, pairs = {}, defaultdict(list)
    for f in flights:
        pair = f["departure_at"][:10] + "_" + f["return_at"][:10]
        pairs[pair].append(f)
        # These are exactly the fields used by the browser filters. Split by budget
        # so both the minimum AND the number of matching offers remain exact.
        key = (pair, f["origin"], f["destination"], f.get("return_origin") or f["destination"],
               f.get("return_destination") or f["origin"], f.get("out_stops"), f.get("in_stops"),
               f["currency"], f["price"] <= data["search"]["max_price"])
        best, count = bins.get(key, (f, 0))
        bins[key] = (f if f["price"] < best["price"] else best, count + 1)
    fields = ("price", "currency", "origin", "destination", "return_origin", "return_destination",
              "departure_at", "return_at", "nights", "airline", "out_stops", "in_stops")
    summaries = [{**{key: best.get(key) for key in fields}, "offer_count": count}
                 for best, count in bins.values()]
    chunks = {}
    for pair, offers in pairs.items():
        offers.sort(key=lambda f: (f["price"], f["departure_at"], f["return_at"]))
        files = []
        for start in range(0, len(offers), CHUNK_SIZE):
            name = f"scans/{digest}/{pair}/{start // CHUNK_SIZE}.json.gz"
            write_json(root / name, offers[start:start + CHUNK_SIZE], compressed=True)
            files.append(name)
        chunks[pair] = files
    # Never send the entire scan to a phone just to draw the departure board.
    summary = {k: v for k, v in data.items() if k not in ("flights", "top", "per_airport")}
    summary.update(browser_version=1, complete_results=complete, total_count=len(flights),
                   flights=summaries, top=[], per_airport={}, detail_files=chunks)
    write_json(target, summary)
    return len(flights), len(summaries)


def build_browser_data(data: Path):
    root = data / "browser"
    if (data / "flights.json").exists():
        print("Browser latest: %s offers → %s filter summaries" % build_scan(data / "flights.json", root, root / "latest.json"))
    index = data / "history/index.json"
    if index.exists():
        for scan in json.loads(index.read_text())["scans"]:
            source = data / "history" / scan["file"]
            build_scan(source, root, root / "history" / (source.name.removesuffix(".gz")))


if __name__ == "__main__":
    import sys
    build_browser_data(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data"))
