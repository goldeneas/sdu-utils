"""Offline tests for offer collection, fallback, normalisation and translation. Run: python3 -m unittest discover flier-summary/scraper"""
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


class CategorizeTest(unittest.TestCase):
    def test_food(self):
        self.assertEqual(fo.categorize("Hakket dansk grisekød 8-12%"), ["meat"])
        self.assertEqual(fo.categorize("Arla protein-milkshake*"), ["dairy", "protein"])
        self.assertEqual(fo.categorize("Barebells spread proteinbar"), ["snacks", "protein"])
        self.assertEqual(fo.categorize("Coca-Cola, Fanta eller Tuborg Squash"), ["drinks"])
        self.assertEqual(fo.categorize("Godt papir"), ["household"])

    def test_whole_word_terms(self):
        self.assertEqual(fo.categorize("Bland selv slik"), ["snacks"])  # not "and" -> meat
        self.assertEqual(fo.categorize("Raakraft hundesnacks"), ["household"])
        self.assertEqual(fo.categorize("Dior Sauvage Parfum Spray"), ["household"])

    def test_nonfood_catalog_and_unknown(self):
        self.assertEqual(fo.categorize("Fjernstyret bil", "Bilka Nonfood Uge 46"), ["nonfood"])
        self.assertEqual(fo.categorize("Verdi"), [])


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
            self.assertEqual(fo.main(["--out", str(out), "--no-translate"]), 0)
            data = json.loads(out.read_text())
        self.assertEqual(len(data["offers"]), 1)
        self.assertEqual([s["count"] for s in data["stores"]], [1] + [0] * (len(fo.STORES) - 1))
        self.assertEqual(data["stores"][0]["color"], "#ff0000")

    def test_page_error_rejects_incomplete_download(self):
        def fake(path, params):
            if params["offset"] >= fo.MAX_OFFSET - fo.PAGE_LIMIT:
                raise RuntimeError("HTTP Error 400: PAGINATION_MAX_REACHED")
            return [dict(OFFER, id=f"o{params['offset'] + i}") for i in range(fo.PAGE_LIMIT)]
        with mock.patch.object(fo, "get_json", fake):
            with self.assertRaisesRegex(RuntimeError, "PAGINATION_MAX_REACHED"):
                fo.fetch_paged({"catalog_ids": "x"})

    def test_no_offers_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fo, "get_json", lambda p, q: []):
            out = Path(d) / "offers.json"
            self.assertEqual(fo.main(["--out", str(out), "--no-translate"]), 1)
            self.assertFalse(out.exists())


class ReliabilityTest(unittest.TestCase):
    def test_pagination_reaches_second_page(self):
        def fake(path, params):
            return [dict(OFFER, id=str(params["offset"] + i))
                    for i in range(fo.PAGE_LIMIT if params["offset"] == 0 else 1)]
        with mock.patch.object(fo, "get_json", fake):
            self.assertEqual(len(fo.fetch_paged({})), fo.PAGE_LIMIT + 1)

    def test_pagination_limit_is_not_silently_accepted(self):
        with mock.patch.object(fo, "get_json", return_value=[OFFER] * fo.PAGE_LIMIT):
            with self.assertRaisesRegex(RuntimeError, "completeness"):
                fo.fetch_paged({})

    def test_malformed_page_is_a_failure(self):
        with mock.patch.object(fo, "get_json", return_value={"error": "unavailable"}):
            with self.assertRaisesRegex(RuntimeError, "non-list"):
                fo.fetch_paged({})

    def test_one_failed_catalog_rejects_whole_store(self):
        def fake(path, params):
            if path == "catalogs":
                return [{"id": "one"}, {"id": "two"}]
            if params["catalog_ids"] == "two":
                raise RuntimeError("failed catalog")
            return [OFFER]
        with mock.patch.object(fo, "get_json", fake):
            with self.assertRaisesRegex(RuntimeError, "failed catalog"):
                fo.fetch_dealer_offers("9ba51")

    def test_failed_store_reuses_previous_without_replacing_healthy_store(self):
        with tempfile.TemporaryDirectory() as d:
            old = fo.slim(OFFER, "netto")
            previous = Path(d) / "previous.json"
            previous.write_text(json.dumps({
                "generatedAt": "2026-11-08T00:00:00+00:00",
                "stores": [{"key": "netto", "fetchedAt": "2026-11-07T00:00:00+00:00"}],
                "offers": [old],
            }))
            def fetch(dealer):
                if dealer == "9ba51":
                    raise RuntimeError("failed page")
                return [dict(OFFER, id=dealer)]
            dealers = {s["key"]: {"id": s["id"]} for s in fo.STORES}
            for attempt in range(2):
                out = Path(d) / f"out{attempt}.json"
                with mock.patch.object(fo, "resolve_dealers", return_value=dealers), mock.patch.object(fo, "fetch_dealer_offers", fetch):
                    self.assertEqual(fo.main(["--out", str(out), "--previous", str(previous), "--no-translate"]), 0)
                data = json.loads(out.read_text())
                self.assertEqual(data["stores"][0]["status"], "cached")
                self.assertEqual(data["stores"][0]["fetchedAt"], "2026-11-07T00:00:00+00:00")
                self.assertEqual(data["stores"][1]["status"], "ok")
                self.assertIn(old, data["offers"])
                self.assertEqual(len(data["offers"]), len(fo.STORES))
                previous = out

    def test_failed_store_without_previous_is_visible(self):
        dealers = {s["key"]: {"id": s["id"]} for s in fo.STORES}
        def fetch(dealer):
            if dealer == "9ba51":
                raise RuntimeError("failed page")
            return [dict(OFFER, id=dealer)]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fo, "resolve_dealers", return_value=dealers), mock.patch.object(fo, "fetch_dealer_offers", fetch):
            out = Path(d) / "out.json"
            fo.main(["--out", str(out), "--no-translate"])
            self.assertEqual(json.loads(out.read_text())["stores"][0]["status"], "unavailable")

    def test_full_description_is_kept_for_search_and_conditions(self):
        description = "x" * 350 + " Netto+ special condition"
        self.assertEqual(fo.slim(dict(OFFER, description=description), "netto")["description"], description)



class TranslationTest(unittest.TestCase):
    def test_brand_names_survive_translation(self):
        line, kept = fo._protect("Netto hakket oksekød fra Løgismose")
        self.assertEqual(line, "BX0 hakket oksekød fra BX1")
        self.assertEqual(fo._restore("BX0 minced beef from BX1", kept), "Netto minced beef from Løgismose")
        self.assertIsNone(fo._restore("Net minced beef", kept))  # placeholder lost: drop the translation

    def test_only_new_names_are_sent_and_failures_keep_danish(self):
        sent = []

        def fake(lines):
            sent.append(list(lines))
            return None if "Ukendt" in lines else [f"EN {x}" for x in lines]
        with mock.patch.object(fo, "_translate_batch", fake), mock.patch.object(fo.time, "sleep", lambda s: None):
            out = fo.translate_names(["Kaffe", "Mælk", "Ukendt", "Mælk"], {"Kaffe": "Coffee"})
        self.assertEqual(out, {"Kaffe": "Coffee", "Mælk": "EN Mælk"})
        self.assertEqual(sent[0], ["Mælk", "Ukendt"])  # one batch, then retried one by one

    def test_unreachable_service_stops_at_once(self):
        calls = []

        def fake(lines):
            calls.append(lines)
            raise fo.TranslateError("HTTP Error 429")
        names = [f"Vare {i} " + "x" * 200 for i in range(100)]  # many batches
        with mock.patch.object(fo, "_translate_batch", fake), mock.patch.object(fo.time, "sleep", lambda s: None):
            out = fo.translate_names(names, {"Kaffe": "Coffee"})
        self.assertEqual(out, {})
        self.assertEqual(len(calls), 1)

    def test_previous_translations_are_reused(self):
        with tempfile.TemporaryDirectory() as d:
            prev = Path(d) / "prev.json"
            prev.write_text(json.dumps({"offers": [{"heading": "Kaffe", "headingEn": "Coffee"}, {"heading": "Mira"}]}))
            self.assertEqual(fo.load_known_translations(str(prev)), {"Kaffe": "Coffee"})
            self.assertEqual(fo.load_known_translations(str(Path(d) / "missing.json")), {})


if __name__ == "__main__":
    unittest.main()
