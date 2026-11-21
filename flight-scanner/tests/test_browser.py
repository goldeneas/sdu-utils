"""The phone downloads exact filter summaries, never a full scan at startup."""
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scanner.browser import CHUNK_SIZE, build_scan, build_browser_data


def scan():
    flights = [{
        "price": i + 10, "currency": "EUR", "origin": "CPH", "destination": "FCO",
        "return_origin": "NAP" if i % 3 else "FCO", "return_destination": "CPH",
        "departure_at": "2030-01-13T08:00" if i % 2 else "2030-01-13T19:00",
        "return_at": "2030-01-21T20:00", "nights": 8, "airline": "Example",
        "out_stops": i % 2, "in_stops": 0, "link": "https://example.com/" + str(i),
    } for i in range(2 * CHUNK_SIZE + 7)]
    return {"schema_version": 1, "status": "ok", "generated_at": "2026-11-21T03:15:00Z",
            "search": {"max_price": 100}, "flights": flights, "top": flights[:1], "per_airport": {}}


def test_browser_summary_counts_minima_and_chunks_are_lossless(tmp_path):
    data = scan()
    source = tmp_path / "flights.json"
    source.write_text(json.dumps(data))
    root = tmp_path / "browser"
    build_scan(source, root, root / "latest.json")
    summary = json.loads((root / "latest.json").read_text())
    assert summary["total_count"] == len(data["flights"])
    assert len(summary["flights"]) < 10
    assert "link" not in summary["flights"][0]
    # All existing airport, stop and budget filters have identical counts/minima.
    for airport in ("FCO", "NAP"):
        for direct in (True, False):
            for budget in (True, False):
                def matches(f):
                    return (f["return_origin"] == airport and
                            (not direct or f["out_stops"] == f["in_stops"] == 0) and
                            (not budget or f["price"] <= 100))
                full = list(filter(matches, data["flights"]))
                small = list(filter(matches, summary["flights"]))
                assert sum(f["offer_count"] for f in small) == len(full)
                assert min(f["price"] for f in small) == min(f["price"] for f in full)
    restored = []
    for files in summary["detail_files"].values():
        for file in files:
            rows = json.loads(gzip.decompress((root / file).read_bytes()))
            assert len(rows) <= CHUNK_SIZE
            restored.extend(rows)
    assert sorted(restored, key=lambda f: f["price"]) == data["flights"]
    assert json.loads(source.read_text()) == data


def test_browser_stages_history_legacy_highlights_and_empty_scan(tmp_path):
    data = scan()
    data.pop("flights")
    source = tmp_path / "history/scans/old.json.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(gzip.compress(json.dumps(data).encode()))
    (tmp_path / "history/index.json").write_text(json.dumps({"scans": [{"file": "scans/old.json.gz"}]}))
    empty = {**data, "flights": [], "top": [], "status": "unavailable"}
    (tmp_path / "flights.json").write_text(json.dumps(empty))
    build_browser_data(tmp_path)
    summary = json.loads((tmp_path / "browser/history/old.json").read_text())
    assert summary["complete_results"] is False
    assert summary["total_count"] == 1
    latest = json.loads((tmp_path / "browser/latest.json").read_text())
    assert latest["flights"] == [] and latest["detail_files"] == {}
    assert latest["status"] == "unavailable"
