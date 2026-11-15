"""Real-capture parsing and whole-source failure/fallback regressions."""
import json
import tempfile
import unittest
from datetime import datetime
from email.message import Message
from pathlib import Path
from unittest import mock

import bilka_offers as bo
import fetch_offers as fo
import member_offers as mo
import probe_member_sources as probe

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-11-15T16:00:00+00:00")


def products():
    return json.loads((FIXTURES / "bilka-plus-2026-11-15.json").read_text())


def page(hits, total=None, number=0):
    total = len(hits) if total is None else total
    return {"hits": hits, "nbHits": total, "page": number,
            "nbPages": (total + 99) // 100, "hitsPerPage": 100, "exhaustiveNbHits": True}


class RealCaptureTest(unittest.TestCase):
    def test_netto_full_public_selection_from_actual_html(self):
        metadata = json.loads((FIXTURES / "netto-plus-2026-11-15.json").read_text())
        captured_at = datetime.fromisoformat(metadata["checkedAt"])
        mo.validate_netto_capture(metadata["headers"], captured_at)
        offers = mo.parse_netto_plus((FIXTURES / "netto-plus-2026-11-15.html").read_text(), captured_at)
        self.assertEqual([o["price"] for o in offers], metadata["expectedPrices"])
        self.assertEqual([o["nonMemberPrice"] for o in offers], metadata["expectedNonMemberPrices"])
        self.assertEqual(len({o["id"] for o in offers}), 6)
        self.assertTrue(all(o["till"] == "2026-11-20T23:59:59+01:00" for o in offers))
        self.assertTrue(all(o["image"] and o["membership"] == "Netto+" for o in offers))

    def test_bilka_actual_prices_pack_brand_and_calendar_dates(self):
        first, second, higher = [bo.parse_bilka_product(p) for p in products()]
        self.assertEqual(first["heading"], "AMA Flydende til madlavning")
        self.assertEqual((first["price"], first["nonMemberPrice"], first["quantity"]), (10, 12, "500 ml"))
        self.assertEqual(second["heading"], "Karen Volf Snøfler")
        self.assertEqual(second["price"], 13)
        self.assertEqual(first["from"], "2026-11-13T00:00:00+01:00")
        self.assertEqual(first["till"], "2026-11-27T23:59:59+01:00")
        self.assertEqual(higher["price"], 13)
        self.assertEqual(higher["nonMemberPrice"], 12)
        self.assertTrue(all(o["prePrice"] is None for o in (first, second, higher)))
        self.assertEqual(first["membership"], "Bilka Plus")
        self.assertIn("BilkaToGo", first["description"])

    def test_mix_price_is_bundle_total_and_never_compared_to_one_pack(self):
        p = dict(products()[0], cpOfferAmount=3, cpOfferPrice=2500)
        offer = bo.parse_bilka_product(p)
        self.assertEqual(offer["price"], 25)
        self.assertEqual(offer["quantity"], "3 stk. á 500 ml")
        self.assertIn("Plus Mix 3 for 25 kr.", offer["description"])
        self.assertIsNone(offer["nonMemberPrice"])

    def test_variant_conditions_and_promotion_are_part_of_identity(self):
        original = products()[0]
        offer = bo.parse_bilka_product(original)
        for changes in ({"cpOfferAmount": 2}, {"cpOfferPrice": 900}, {"cpOfferId": 123}, {"netcontent": "1 l"}):
            self.assertNotEqual(offer["id"], bo.parse_bilka_product(dict(original, **changes))["id"])
        self.assertEqual(offer, bo.parse_bilka_product(original))

    def test_actual_same_name_price_variants_keep_distinct_product_ids(self):
        variants = json.loads((FIXTURES / "bilka-plus-variants-2026-11-15.json").read_text())
        offers = [bo.parse_bilka_product(p) for p in variants]
        self.assertEqual(len(fo.merge_member_offers([], offers + offers)), 4)
        self.assertEqual(len({o["sourceProductId"] for o in offers}), 4)
        self.assertEqual(len({o["heading"] for o in offers}), 2)

    def test_sub_brand_identifies_flavour_without_repeating_brand(self):
        p = dict(products()[0], name="Energidrik", brand="Faxe Kondi", subBrand="Booster Frosty Blue")
        self.assertEqual(bo.parse_bilka_product(p)["heading"], "Faxe Kondi Booster Frosty Blue Energidrik")

    def test_bad_or_nonpublic_product_rejects_the_source(self):
        original = products()[0]
        cases = [{"cpOffer": False}, {"cpOffer": "true"}, {"nonsearchable": True},
                 {"cpOfferPrice": 0}, {"cpOfferPrice": True}, {"cpOfferPrice": 12.5},
                 {"cpOfferAmount": None}, {"cpOfferAmount": 0}, {"cpOfferId": None},
                 {"cpOfferPrice": 10**1000},
                 {"cpOfferFromDate": "2026-11-99"}, {"cpOfferToDate": "2026-01-01"},
                 {"cpOfferToDate": None}, {"objectID": ""}, {"name": ""},
                 {"storeData": {}}, {"images": "image.jpg"}, {"netcontent": None},
                 {"description": "Personlig kupon"}]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                bo.parse_bilka_product(dict(original, **change))
        with mock.patch.object(bo, "fetch_bilka_page", return_value=page([original, dict(original, cpOffer=False)])), self.assertRaises(RuntimeError):
            bo.fetch_bilka_plus(NOW)


class PaginationTest(unittest.TestCase):
    def setUp(self):
        self.hits = [dict(products()[0], objectID=str(i + 1)) for i in range(101)]

    def test_complete_two_page_window(self):
        with mock.patch.object(bo, "fetch_bilka_page", side_effect=[page(self.hits[:100], 101), page(self.hits[100:], 101, 1)]) as fetch:
            offers = bo.fetch_bilka_plus(NOW)
        self.assertEqual(len(offers), 101)
        self.assertEqual(fetch.call_args_list, [mock.call(0), mock.call(1)])

    def test_empty_success(self):
        with mock.patch.object(bo, "fetch_bilka_page", return_value=page([])):
            self.assertEqual(bo.fetch_bilka_plus(NOW), [])

    def test_incomplete_or_unverifiable_pages_fail(self):
        first, second = page(self.hits[:100], 101), page(self.hits[100:], 101, 1)
        cases = [[dict(first, exhaustiveNbHits=False)], [dict(first, nbHits=1000)],
                 [dict(first, nbPages=1)], [dict(first, page=1)], [dict(first, hitsPerPage=99)],
                 [dict(first, hits=self.hits[:99])], [first, dict(second, nbHits=102)],
                 [first, dict(second, hits=[])], [first, dict(second, hits=[self.hits[0]])],
                 [first, RuntimeError("second page failed")]]
        for responses in cases:
            with self.subTest(responses=len(responses)), mock.patch.object(bo, "fetch_bilka_page", side_effect=responses), self.assertRaises(RuntimeError):
                bo.fetch_bilka_plus(NOW)

    def test_http_json_client_and_anonymous_request(self):
        response = mock.MagicMock()
        response.status = 200
        response.headers = Message()
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.read.return_value = json.dumps(page(products())).encode()
        response.__enter__.return_value = response
        with mock.patch.object(bo.urllib.request, "urlopen", return_value=response) as get:
            self.assertEqual(len(bo.fetch_bilka_plus(NOW)), 3)
        request = get.call_args.args[0]
        self.assertIn("cpOffer%3Atrue", request.full_url)
        self.assertIn("isInAssortmentIn%3A1654", request.full_url)
        self.assertIsNone(request.get_header("Cookie"))
        self.assertIsNone(request.get_header("Authorization"))
        for body in (b"not json", b"[]", b"", b"x" * (mo.MAX_PAGE_BYTES + 1)):
            response.read.return_value = body
            with mock.patch.object(bo.urllib.request, "urlopen", return_value=response), self.assertRaises(RuntimeError):
                bo.fetch_bilka_page(0)
        response.headers.replace_header("Content-Type", "text/html")
        with mock.patch.object(bo.urllib.request, "urlopen", return_value=response), self.assertRaises(RuntimeError):
            bo.fetch_bilka_page(0)
        with mock.patch.object(bo.urllib.request, "urlopen", side_effect=ConnectionResetError("reset")), self.assertRaises(RuntimeError):
            bo.fetch_bilka_page(0)


class FeedIntegrationTest(unittest.TestCase):
    def test_diagnostic_retains_actual_response_even_when_product_validation_fails(self):
        for valid in (True, False):
            hits = products() if valid else [dict(products()[0], cpOfferPrice=0)]
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as directory, \
                    mock.patch.object(probe, "fetch_bilka_page", return_value=page(hits)):
                result = probe.probe_bilka_products(Path(directory))
                self.assertEqual(result["status"], "ok" if valid else "error")
                capture = Path(directory) / result["pages"][0]["json"]
                self.assertEqual(json.loads(capture.read_text())["hits"], hits)
                self.assertEqual(len(result["pages"][0]["sha256"]), 64)
                self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), [capture.name])

    def test_bilka_fallback_retains_original_dates_and_freshness(self):
        offer = bo.parse_bilka_product(products()[0])
        previous = {"memberFeeds": [{"key": "bilka-plus", "fetchedAt": NOW.isoformat(), "offers": [offer]}]}
        with mock.patch.object(fo, "fetch_bilka_plus", side_effect=RuntimeError("offline")):
            for _ in range(2):
                feed = fo.bilka_member_feed(previous, "2026-11-17T16:00:00+00:00")
                self.assertEqual(feed["status"], "cached")
                self.assertEqual(feed["fetchedAt"], NOW.isoformat())
                self.assertEqual(feed["offers"], [offer])
                previous = {"memberFeeds": [feed]}

    def test_independent_member_sources_and_counts_in_cli(self):
        member = bo.parse_bilka_product(products()[0])
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(fo, "resolve_dealers", return_value={}), \
                mock.patch.object(fo, "fetch_bilka_plus", return_value=[member]), \
                mock.patch.object(fo, "fetch_netto_plus", side_effect=RuntimeError("offline")):
            output = Path(directory) / "offers.json"
            self.assertEqual(fo.main(["--bilka-plus", "--netto-plus", "--no-translate", "--out", str(output)]), 0)
            data = json.loads(output.read_text())
        self.assertEqual(data["memberFeeds"][0]["status"], "unavailable")
        self.assertEqual(data["memberFeeds"][1]["status"], "ok")
        self.assertEqual(data["stores"][2]["count"], 1)
        self.assertEqual(data["offers"][0]["membership"], "Bilka Plus")
        self.assertIn("Bilka Plus", data["source"]["name"])
        self.assertIn("cats", data["offers"][0])


if __name__ == "__main__":
    unittest.main()
