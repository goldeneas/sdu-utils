"""Offline tests for the offer normalisation. Run: python3 -m unittest discover flier-summary/scraper"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fetch_offers as fo

OFFER = {
    "id": "abc123",
    "heading": "Zoégas kaffe",
    "description": "400-450 g.  Flere varianter\n Max 2 pr. kunde",
    "catalog_id": "cat1",
    "catalog_page": 3,
    "pricing": {"price": 39.95, "pre_price": 59.0, "currency": "DKK"},
    "quantity": {
        "unit": {"symbol": "g", "si": {"symbol": "kg", "factor": 0.001}},
        "size": {"from": 400, "to": 450},
        "pieces": {"from": 1, "to": 1},
    },
    "images": {"thumb": "https://img/t.jpg", "view": "https://img/v.jpg"},
    "run_from": "2026-11-01T00:00:00+0000",
    "run_till": "2026-11-07T22:59:59+0000",
    "dealer_id": "9ba51",
}


class SlimTest(unittest.TestCase):
    def test_fields(self):
        s = fo.slim(OFFER, "netto")
        self.assertEqual(s["store"], "netto")
        self.assertEqual(s["heading"], "Zoégas kaffe")
        self.assertEqual(s["price"], 39.95)
        self.assertEqual(s["prePrice"], 59.0)
        self.assertEqual(s["quantity"], "400-450 g")
        self.assertEqual(s["unitPrice"], "99,88 kr/kg")
        self.assertEqual(s["description"], "400-450 g. Flere varianter Max 2 pr. kunde")
        self.assertEqual(s["image"], "https://img/t.jpg")

    def test_pre_price_dropped_when_not_higher(self):
        o = dict(OFFER, pricing={"price": 10, "pre_price": 10})
        self.assertIsNone(fo.slim(o, "netto")["prePrice"])

    def test_no_heading_skipped(self):
        self.assertIsNone(fo.slim(dict(OFFER, heading=" "), "netto"))

    def test_pieces(self):
        q = {"unit": {"symbol": "l", "si": {"symbol": "l", "factor": 1}}, "size": {"from": 1.5, "to": 1.5}, "pieces": {"from": 4, "to": 4}}
        self.assertEqual(fo.quantity_text(q), "1,5 l · 4 stk")
        self.assertEqual(fo.unit_price(30.0, q), "5,00 kr/l")

    def test_pcs_unit(self):
        one = {"unit": {"symbol": "pcs", "si": {"symbol": "pcs", "factor": 1}}, "size": {"from": 1, "to": 1}, "pieces": {"from": 1, "to": 1}}
        self.assertEqual(fo.quantity_text(one), "")
        self.assertEqual(fo.quantity_text(dict(one, size={"from": 10, "to": 10})), "10 stk")
        self.assertEqual(fo.quantity_text(dict(one, pieces={"from": 2, "to": 2})), "2 stk")

    def test_missing_quantity(self):
        self.assertEqual(fo.quantity_text(None), "")
        self.assertEqual(fo.unit_price(10, {"unit": None}), "")


class MainTest(unittest.TestCase):
    def fake_get(self, path, params):
        if path == "dealers":
            return [{"id": s["id"], "name": s["name"], "branding": {"color": "ff0000"}} for s in fo.STORES]
        if path == "catalogs":
            return [{"id": "cat1"}, {"id": "cat2"}] if params["dealer_ids"] == "9ba51" else []
        if params.get("catalog_ids") == "cat1" and params["offset"] == 0:
            return [OFFER, OFFER]  # duplicate is removed
        return []

    def test_writes_json(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fo, "get_json", self.fake_get):
            out = Path(d) / "offers.json"
            self.assertEqual(fo.main(["--out", str(out)]), 0)
            data = json.loads(out.read_text())
        self.assertEqual(len(data["offers"]), 1)
        self.assertEqual([s["count"] for s in data["stores"]], [1, 0, 0, 0])
        self.assertEqual(data["stores"][0]["color"], "#ff0000")

    def test_pagination_cap_keeps_fetched_offers(self):
        def fake(path, params):
            if params["offset"] >= fo.MAX_OFFSET - fo.PAGE_LIMIT:
                raise RuntimeError("HTTP Error 400: PAGINATION_MAX_REACHED")
            return [dict(OFFER, id=f"o{params['offset'] + i}") for i in range(fo.PAGE_LIMIT)]
        with mock.patch.object(fo, "get_json", fake):
            offers = fo.fetch_paged({"catalog_ids": "x"})
        self.assertEqual(len(offers), fo.MAX_OFFSET - fo.PAGE_LIMIT)

    def test_no_offers_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fo, "get_json", lambda p, q: []):
            out = Path(d) / "offers.json"
            self.assertEqual(fo.main(["--out", str(out)]), 1)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
