"""Regressions for the real missing Protein Lab offer and ordinary store feeds."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import bilka_store_offers as bo
import fetch_offers as fo
import probe_member_sources as probe

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-11-15T20:00:00+00:00")


def products():
    return json.loads((FIXTURES / "bilka-public-promotions-2026-11-15.json").read_text())


class StorePriceTest(unittest.TestCase):
    def test_actual_missing_mousse_is_ten_kroner_without_plus_or_invented_dates(self):
        offer, = bo.parse_store_product(products()[0], NOW)
        self.assertEqual(offer["heading"], "Protein Lab Chokolademousse")
        self.assertEqual((offer["price"], offer["quantity"], offer["unitPrice"]), (10, "200 g", "50 kr/kg"))
        self.assertFalse(offer.get("membership"))
        self.assertIsNone(offer["prePrice"])
        self.assertIsNone(offer["from"])
        self.assertIsNone(offer["till"])
        self.assertEqual(offer["priceObservedAt"], NOW.isoformat())
        self.assertEqual(offer["sourceProductId"], "125829")

    def test_actual_bundle_total_and_dominated_bundle(self):
        offer, = bo.parse_store_product(products()[1], NOW)
        self.assertEqual(offer["price"], 25)
        self.assertEqual(offer["quantity"], "10 stk. á 1 stk")
        self.assertIn("Mix 10 for 25 kr.", offer["description"])
        self.assertEqual(bo.parse_store_product(products()[2], NOW), [])

    def test_no_fabricated_price_for_buy_three_pay_two(self):
        product = products()[0]
        product["storeData"]["1654"].update(multipromo="wine", offerCount=3, multiPromoPrice="", offerDescription="3 for 2")
        single, bundle = bo.parse_store_product(product, NOW)
        self.assertEqual(single["price"], 10)
        self.assertIsNone(bundle["price"])
        self.assertTrue(bundle["description"].startswith("3 for 2."))
        self.assertNotEqual(single["id"], bundle["id"])

    def test_explicit_dates_are_retained_and_bad_dates_reject_the_source(self):
        product = products()[0]
        product["storeData"]["1654"].update(offerFrom="2026-11-12", offerUntil="2026-11-19")
        offer, = bo.parse_store_product(product, NOW)
        self.assertEqual(offer["from"], "2026-11-12T00:00:00+01:00")
        self.assertEqual(offer["till"], "2026-11-19T23:59:59+01:00")
        for value in ("unknown", "2026-11-01", "2026-11-19T12:00:00"):
            product["storeData"]["1654"]["offerUntil"] = value
            with self.assertRaises(RuntimeError):
                bo.parse_store_product(product, NOW)

    def test_invalid_eligibility_or_prices_fail_closed(self):
        original = products()[0]
        cases = [dict(original, isInOffer=[]), dict(original, isInOffer=None),
                 dict(original, nonsearchable=True), dict(original, storeData={}),
                 dict(original, price=0), dict(original, name=None), dict(original, images="url")]
        for value in (True, -1, 10.5, 10**1000):
            product = copy.deepcopy(original)
            product["storeData"]["1654"]["price"] = value
            cases.append(product)
        for product in cases:
            with self.subTest(product=product.get("objectID")), self.assertRaises(RuntimeError):
                bo.parse_store_product(product, NOW)

    def test_complete_cursor_pagination_and_source_failure_boundaries(self):
        first, second = products()[:2]
        with mock.patch.object(bo, "fetch_store_page", side_effect=[{"hits": [first], "cursor": "next"}, {"hits": [second]}]) as fetch:
            self.assertEqual(len(bo.fetch_bilka_store_offers(NOW)), 2)
        self.assertEqual(fetch.call_args_list, [mock.call(None), mock.call("next")])
        for pages in ([{"hits": [first], "cursor": "same"}, {"hits": [second], "cursor": "same"}],
                      [{"hits": [first], "cursor": "next"}, {"hits": [first]}],
                      [{"hits": [], "cursor": "next"}], [{"hits": []}], [{"hits": "invalid"}],
                      [{"hits": [first], "cursor": "next"}, RuntimeError("network")]):
            with mock.patch.object(bo, "fetch_store_page", side_effect=pages), self.assertRaises(RuntimeError):
                bo.fetch_bilka_store_offers(NOW)
        with mock.patch.object(bo, "MAX_PAGES", 1), mock.patch.object(bo, "fetch_store_page", return_value={"hits": [first], "cursor": "next"}), self.assertRaises(RuntimeError):
            bo.fetch_bilka_store_offers(NOW)

    def test_fallback_preserves_observation_time_and_stays_separate_from_plus(self):
        offer, = bo.parse_store_product(products()[0], NOW)
        previous = {"offerFeeds": [{"key": "bilkatogo-offers", "fetchedAt": NOW.isoformat(), "offers": [offer]}],
                    "memberFeeds": [{"key": "bilka-plus", "offers": []}]}
        with mock.patch.object(fo, "fetch_bilka_store_offers", side_effect=RuntimeError("offline")):
            for _ in range(2):
                feed = fo.bilka_store_feed(previous, "2026-11-17T20:00:00+00:00")
                self.assertEqual(feed["status"], "cached")
                self.assertEqual(feed["fetchedAt"], NOW.isoformat())
                self.assertEqual(feed["offers"][0]["priceObservedAt"], NOW.isoformat())
                self.assertIsNone(feed["offers"][0]["till"])
                previous["offerFeeds"] = [feed]

    def test_cli_can_publish_ordinary_prices_when_other_feeds_fail(self):
        offers = bo.parse_store_product(products()[0], NOW)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fo, "resolve_dealers", return_value={}), \
                mock.patch.object(fo, "fetch_bilka_store_offers", return_value=offers), \
                mock.patch.object(fo, "fetch_bilka_plus", side_effect=RuntimeError("offline")):
            output = Path(tmp) / "offers.json"
            self.assertEqual(fo.main(["--bilka-store-offers", "--bilka-plus", "--no-translate", "--out", str(output)]), 0)
            data = json.loads(output.read_text())
        self.assertEqual(data["stores"][2]["count"], 1)
        self.assertEqual(data["memberFeeds"][0]["status"], "unavailable")
        self.assertEqual(data["offerFeeds"][0]["status"], "ok")
        self.assertFalse(data["offers"][0].get("membership"))

    def test_diagnostic_retains_raw_public_pages_without_exporting_a_feed(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(probe, "fetch_store_page", return_value={"hits": [products()[0]]}):
            result = probe.probe_bilka_store_prices(Path(tmp))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["offerCount"], 1)
            self.assertTrue((Path(tmp) / result["pages"][0]["json"]).exists())
            self.assertFalse((Path(tmp) / "offers.json").exists())


if __name__ == "__main__":
    unittest.main()
