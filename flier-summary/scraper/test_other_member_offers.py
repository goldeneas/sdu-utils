"""Real Coop and Lidl captures, eligibility boundaries and independent fallback."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import coop_offers as co
import fetch_offers as fo
import lidl_offers as li
import probe_member_sources as probe
from member_offers import PageParser

FIXTURES = Path(__file__).parent / "fixtures"
COOP = (FIXTURES / "coop-members-2026-11-15.html").read_text(encoding="utf-8")
LIDL = (FIXTURES / "lidl-plus-2026-11-15.html").read_text(encoding="utf-8")
NOW = datetime.fromisoformat("2026-11-15T20:00:00+00:00")


def lidl_products():
    parser = PageParser()
    parser.feed(LIDL)
    return [json.loads(n.attrs["data-grid-data"]) for n in parser.root.descendants() if "data-grid-data" in n.attrs]


class CoopTest(unittest.TestCase):
    def test_actual_chain_mapping_prices_and_missing_closing_p_tags(self):
        discount = co.parse_coop_members(COOP, NOW, "365discount")
        superbrugsen = co.parse_coop_members(COOP, NOW, "superbrugsen")
        self.assertEqual(len(discount), 2)
        self.assertEqual(len(superbrugsen), 5)
        self.assertEqual([o["price"] for o in discount], [45, 22])
        self.assertEqual([o["price"] for o in superbrugsen], [45, 119, 22, None, 18])
        self.assertEqual(discount[0]["quantity"], "1 pakke · 500-875 g.")
        self.assertEqual(discount[1]["heading"], "Mou komplet suppe")
        self.assertEqual(discount[0]["nonMemberPrice"], 45)
        self.assertEqual(superbrugsen[0]["nonMemberPrice"], 55)
        self.assertTrue(superbrugsen[0]["nonMemberPriceIsUpperBound"])
        self.assertFalse(superbrugsen[1]["nonMemberPriceIsUpperBound"])
        self.assertEqual(discount[0]["from"], "2026-11-01T00:00:00+01:00")
        self.assertEqual(discount[0]["till"], "2026-11-30T23:59:59+01:00")
        self.assertTrue(all(o["store"] == "superbrugsen" for o in superbrugsen))
        self.assertTrue(all(o["prePrice"] is None and o["membership"] == "Coop" for o in discount + superbrugsen))

    def test_percentage_offer_keeps_conditions_without_a_fabricated_price(self):
        offer = co.parse_coop_members(COOP, NOW, "superbrugsen")[3]
        self.assertIn("Medlemsrabat 30 %", offer["heading"])
        self.assertIn("silikoneservice", offer["description"])
        self.assertIsNone(offer["price"])
        self.assertIsNone(offer["nonMemberPrice"])
        self.assertEqual(offer["till"], "2026-11-19T23:59:59+01:00")

    def test_personal_card_or_ambiguous_price_fails_only_its_chain(self):
        bad = COOP.replace('data-fancy-personal-offer=1349437 data-offertype=2', 'data-fancy-personal-offer=1349437 data-offertype=1')
        with self.assertRaisesRegex(RuntimeError, "public member"):
            co.parse_coop_members(bad, NOW, "superbrugsen")
        self.assertEqual(len(co.parse_coop_members(bad, NOW, "365discount")), 2)
        for html in (COOP.replace('logo-superbrugsen.png', 'unknown.png'),
                     COOP.replace('45<sup>00</sup>', '???<sup>00</sup>'),
                     COOP.replace('1. nov. - 30. nov.', '31. nov. - 30. nov.'),
                     COOP.replace('data-fancy-personal-offer=1359893', 'data-fancy-personal-offer=1349437')):
            with self.subTest(html=html[:30]), self.assertRaises(RuntimeError):
                co.parse_coop_members(html, NOW, "superbrugsen")

    def test_year_resolution_handles_new_year_but_rejects_ambiguous_old_dates(self):
        start, till = co.coop_period("28. dec. - 3. jan.", datetime.fromisoformat("2027-01-01T12:00:00+00:00"))
        self.assertEqual(start, "2026-12-28T00:00:00+01:00")
        self.assertEqual(till, "2027-01-03T23:59:59+01:00")
        for period in ("1. jan. - 31. jan.", "1. xxx. - 3. nov.", "31. nov. - 30. nov."):
            with self.subTest(period=period), self.assertRaises(RuntimeError):
                co.coop_period(period, NOW)

    def test_collection_requires_dated_fresh_html_before_resolving_a_year(self):
        headers = {"Date": "Sun, 15 Nov 2026 20:00:00 GMT"}
        with mock.patch.object(co, "fetch_public_html", return_value=(COOP, headers, co.COOP_MEMBERS_URL)):
            self.assertEqual(len(co.fetch_coop_members("365discount", NOW)), 2)
        for headers in ({}, {"Date": "Sat, 14 Nov 2026 20:00:00 GMT"},
                        {"Date": "Sun, 15 Nov 2026 20:00:00 GMT", "Age": "999999999999999999999"}):
            with mock.patch.object(co, "fetch_public_html", return_value=(COOP, headers, co.COOP_MEMBERS_URL)), self.assertRaises(RuntimeError):
                co.fetch_coop_members("365discount", NOW)
        with mock.patch.object(co, "fetch_public_html", side_effect=ConnectionResetError("reset")), self.assertRaises(RuntimeError):
            co.fetch_coop_members("365discount", NOW)


class LidlTest(unittest.TestCase):
    def test_actual_prices_dates_comparisons_and_coupon_exclusion(self):
        offers = li.parse_lidl_plus(LIDL)
        self.assertEqual(len(offers), 6)
        self.assertNotIn("11277082", [o["sourceProductId"] for o in offers])
        butter, coffee = offers[:2]
        self.assertEqual((butter["price"], butter["quantity"]), (12, "200 g"))
        self.assertIsNone(butter["prePrice"])
        self.assertIsNone(butter["nonMemberPrice"])  # oldPrice does not prove a non-member comparison
        self.assertEqual(coffee["nonMemberPrice"], 45)
        self.assertEqual(butter["from"], "2026-11-15T00:00:00+01:00")
        self.assertEqual(butter["till"], "2026-11-21T23:59:59+01:00")
        self.assertTrue(all(o["membership"] == "Lidl Plus" for o in offers))

    def test_price_publication_timestamp_does_not_backdate_the_offer(self):
        product = lidl_products()[2]  # future bakery bundle, price authored earlier
        offer = li.parse_lidl_product(product)
        self.assertEqual(offer["from"], "2026-11-19T00:00:00+01:00")
        self.assertNotEqual(offer["from"][:10], product["regionsPrices"]["1"]["currentLidlPlusPrice"]["price"]["startDate"][:10])

    def test_bundles_keep_total_prices_without_multiplying_a_prepacked_amount(self):
        offers = {o["sourceProductId"]: o for o in li.parse_lidl_plus(LIDL)}
        self.assertEqual((offers["11252137"]["price"], offers["11252137"]["quantity"]), (9, "3 stk. á 110 g"))
        self.assertEqual((offers["11002727"]["price"], offers["11002727"]["quantity"]), (89, "18 x 20 cl"))
        self.assertIn("18 stk. for 89 kr.", offers["11002727"]["description"])
        self.assertEqual(offers["11059879"]["quantity"], "5 stk.")
        self.assertTrue(all(o["nonMemberPrice"] is None for o in offers.values() if "stk." in o["description"]))

    def test_expiry_from_explicit_member_price_when_store_card_has_no_end(self):
        coffee = lidl_products()[1]
        self.assertNotIn("storeEndDate", coffee)
        self.assertEqual(li.parse_lidl_product(coffee)["till"], "2026-11-21T23:59:59+01:00")
        del coffee["regionsPrices"]["1"]["currentLidlPlusPrice"]["price"]["endDate"]
        with self.assertRaisesRegex(RuntimeError, "expiry"):
            li.parse_lidl_product(coffee)

    def test_current_campaign_is_discovered_and_never_replaced_with_an_external_host(self):
        self.assertEqual(li.discover_lidl_campaign('<a href="/c/store/ugens-lidl-plus/a10107260">Ugens</a>'),
                         "https://www.lidl.dk/c/store/ugens-lidl-plus/a10107260")
        for html in ('<a href="https://example.com/c/store/ugens-lidl-plus/a1">Other</a>',
                     '<a href="/c/store/ugens-lidl-plus/a1"></a><a href="/c/store/ugens-lidl-plus/a2"></a>', ''):
            with self.subTest(html=html), self.assertRaises(RuntimeError):
                li.discover_lidl_campaign(html)

    def test_changed_markup_missing_cards_and_duplicate_products_fail_the_source(self):
        for html in ('<html>Maintenance</html>', LIDL.replace('data-grid-data=', 'data-unknown=', 1),
                     LIDL.replace('&quot;productId&quot;:11267403', '&quot;productId&quot;:11277276'),
                     LIDL.replace('&quot;price&quot;:12', '&quot;price&quot;:0', 1)):
            with self.subTest(html=html[:40]), self.assertRaises(RuntimeError):
                li.parse_lidl_plus(html)

    def test_wrong_region_ambiguous_price_personal_offer_or_missing_identity_fail(self):
        original = lidl_products()[0]
        cases = [dict(original, regionsPrices={}), dict(original, productId=None),
                 dict(original, fullTitle="Personligt tilbud"), dict(original, timezoneId="UTC"),
                 dict(original, canonicalUrl="https://example.com/product"),
                 dict(original, storeStartDate=999999999999999999)]
        for key, value in (("price", True), ("price", float("nan")), ("price", -1),
                           ("variantsHaveDifferentPrices", True), ("currencyCode", "EUR")):
            product = copy.deepcopy(original)
            product["regionsPrices"]["1"]["currentLidlPlusPrice"]["price"][key] = value
            cases.append(product)
        for product in cases:
            with self.subTest(product=product.get("productId")), self.assertRaises(RuntimeError):
                li.parse_lidl_product(product)

    def test_collector_follows_the_observed_week_link_and_wraps_network_errors(self):
        with mock.patch.object(li, "fetch_public_html", side_effect=[
            ('<a href="/c/store/ugens-lidl-plus/a10107260">Ugens</a>', {}, li.LIDL_HOME),
            (LIDL, {}, "https://www.lidl.dk/c/store/ugens-lidl-plus/a10107260"),
        ]) as fetch:
            self.assertEqual(len(li.fetch_lidl_plus(NOW)), 6)
        self.assertEqual(fetch.call_args_list, [mock.call(li.LIDL_HOME), mock.call("https://www.lidl.dk/c/store/ugens-lidl-plus/a10107260")])
        with mock.patch.object(li, "fetch_public_html", side_effect=ConnectionResetError("reset")), self.assertRaises(RuntimeError):
            li.fetch_lidl_plus(NOW)


class IntegrationTest(unittest.TestCase):
    def test_new_member_feeds_have_independent_fallback_and_original_expiries(self):
        for key, store, factory, patch_name, offers in (
            ("coop-365discount", "365discount", lambda prev, at: fo.coop_member_feed(prev, at, "365discount"), "fetch_coop_members", co.parse_coop_members(COOP, NOW, "365discount")),
            ("coop-superbrugsen", "superbrugsen", lambda prev, at: fo.coop_member_feed(prev, at, "superbrugsen"), "fetch_coop_members", co.parse_coop_members(COOP, NOW, "superbrugsen")),
            ("lidl-plus", "lidl", fo.lidl_member_feed, "fetch_lidl_plus", li.parse_lidl_plus(LIDL)),
        ):
            previous = {"memberFeeds": [{"key": key, "fetchedAt": NOW.isoformat(), "offers": offers}]}
            with mock.patch.object(fo, patch_name, side_effect=RuntimeError("offline")):
                for _ in range(2):
                    feed = factory(previous, "2026-11-17T20:00:00+00:00")
                    self.assertEqual((feed["status"], feed["fetchedAt"], feed["offers"]), ("cached", NOW.isoformat(), offers))
                    self.assertEqual(feed["store"], store)
                    previous = {"memberFeeds": [feed]}

    def test_one_failed_coop_chain_does_not_discard_lidl_or_the_other_chain(self):
        sb = co.parse_coop_members(COOP, NOW, "superbrugsen")
        lidl = li.parse_lidl_plus(LIDL)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fo, "resolve_dealers", return_value={}), \
                mock.patch.object(fo, "fetch_coop_members", side_effect=[RuntimeError("365 offline"), sb]), \
                mock.patch.object(fo, "fetch_lidl_plus", return_value=lidl):
            out = Path(tmp) / "offers.json"
            self.assertEqual(fo.main(["--coop-members", "--lidl-plus", "--no-translate", "--out", str(out)]), 0)
            data = json.loads(out.read_text())
        self.assertEqual([f["status"] for f in data["memberFeeds"]], ["unavailable", "ok", "ok"])
        self.assertEqual(len(data["offers"]), 11)
        self.assertEqual({s["key"]: s["count"] for s in data["stores"] if s["count"]},
                         {"superbrugsen": 5, "lidl": 6})

    def test_diagnostic_retains_html_and_reports_validation_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "coop.html").write_text(COOP)
            (directory / "home.html").write_text('<a href="/c/store/ugens-lidl-plus/a10107260"></a>')
            (directory / "lidl.html").write_text(LIDL)
            sources = [{"key": "coop-members", "status": "ok", "html": "coop.html", "checkedAt": NOW.isoformat(), "headers": {}},
                       {"key": "lidl-home", "status": "ok", "html": "home.html"},
                       {"key": "lidl-selection", "status": "ok", "html": "lidl.html"}]
            with mock.patch.object(probe, "probe_source", side_effect=sources):
                results = probe.probe_other_members(directory)
            self.assertTrue(results[0]["validationFailed"])
            self.assertEqual(results[2]["lidlValidation"], {"status": "ok", "offerCount": 6})
            self.assertEqual((directory / "coop.html").read_text(), COOP)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(probe, "SOURCES", []), \
                mock.patch.object(probe, "probe_other_members", return_value=[{"key": "coop-members", "status": "ok", "validationFailed": True}]):
            self.assertEqual(probe.main(["--other-members", "--out-dir", str(Path(tmp) / "capture")]), 1)


if __name__ == "__main__":
    unittest.main()
