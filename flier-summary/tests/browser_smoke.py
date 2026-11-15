#!/usr/bin/env python3
"""Exercise the PWA with a collected feed, a real Chromium and isolated storage.

Requires Playwright and its Chromium: python3 -m playwright install chromium.
Run with --data /path/to/offers.json --artifacts /tmp/flier-browser-results.
The feed and static files are copied to a temporary site; nothing is published.
"""
import argparse
import copy
import functools
import json
import re
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


class SiteHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/flier-summary/data/offers.json":
            body = json.dumps(self.server.payload, ensure_ascii=False).encode()
            self.send_response(503 if self.server.fail_data else 200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A test may close its browser while the worker refreshes.
            return
        super().do_GET()


class BrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="flier-browser-site-")
        site = Path(cls.tmp.name) / "flier-summary"
        app = Path(__file__).resolve().parents[1]
        shutil.copytree(app, site, ignore=shutil.ignore_patterns("scraper", "tests", "data", "__pycache__"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SiteHandler, directory=cls.tmp.name))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/flier-summary/"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.netto = next(o for o in cls.feed["offers"] if o.get("sourceKey") == "netto-plus")
        cls.bilka = next(o for o in cls.feed["offers"] if o.get("sourceKey") == "bilka-plus")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.server.payload = copy.deepcopy(self.feed)
        self.server.fail_data = False
        self.context = self.browser.new_context(viewport={"width": 390, "height": 844},
                                               is_mobile=True, has_touch=True, locale="en-GB",
                                               timezone_id="Europe/Copenhagen")
        # External translation is deliberately unavailable: test local cached
        # translations and graceful fallback, independently of Google's uptime.
        self.context.route("https://translate.googleapis.com/**", lambda route: route.abort())
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.clock.set_fixed_time(datetime.fromisoformat(self.feed["generatedAt"]))

    def tearDown(self):
        self.page.screenshot(path=str(self.artifacts / f"{self._testMethodName}.png"), animations="disabled")
        self.context.close()
        self.assertEqual(self.errors, [], "Uncaught JavaScript error")

    def open(self, suffix=""):
        self.page.goto(self.url + suffix, wait_until="domcontentloaded")
        expect(self.page.locator("#status")).not_to_be_empty()

    def search(self, heading):
        self.page.locator("#q").fill(heading)
        self.page.wait_for_function("q => JSON.parse(localStorage.getItem('flier-summary:prefs'))?.query === q", arg=heading)
        expect(self.page.locator("#list article.offer").first).to_be_visible()

    def card(self, offer):
        return self.page.locator("#list article.offer").filter(has=self.page.locator("h3", has_text=offer["heading"])).filter(
            has=self.page.locator(".membership", has_text=f"Requires {offer['membership']}"))

    def detail(self, offer):
        self.page.goto(self.url + "#offer/" + offer["id"], wait_until="domcontentloaded")
        expect(self.page.locator("#view-detail h2")).to_have_text(offer["heading"])

    def current(self, offer):
        now = datetime.fromisoformat(self.feed["generatedAt"])
        return (not offer.get("from") or datetime.fromisoformat(offer["from"]) <= now) and (
            not offer.get("till") or datetime.fromisoformat(offer["till"]) >= now)

    def test_initial_load_recent_sort_and_show_more(self):
        self.open()
        current = [o for o in self.feed["offers"] if self.current(o)]
        expected = sorted(current, key=lambda o: datetime.fromisoformat(o["from"]).timestamp() if o.get("from") else 0, reverse=True)
        expect(self.page.locator("#count")).to_have_text(f"{len(current)} offers")
        expect(self.page.locator("#list article.offer")).to_have_count(min(60, len(current)))
        self.assertEqual(self.page.locator("#list h3").all_text_contents(), [o["heading"] for o in expected[:60]])
        self.page.locator("#list .more").click()
        expect(self.page.locator("#list article.offer")).to_have_count(min(180, len(current)))
        expect(self.page.locator("#member-status")).to_contain_text("Netto+")
        expect(self.page.locator("#member-status")).to_contain_text("Bilka Plus (BilkaToGo Odense)")

    def test_search_store_category_price_and_upcoming_filters(self):
        self.open()
        self.search(self.netto["heading"])
        expect(self.card(self.netto).first.locator(".membership")).to_have_text("Requires Netto+")
        self.page.locator("#q").fill("")
        self.page.wait_for_function("JSON.parse(localStorage.getItem('flier-summary:prefs'))?.query === ''")
        self.page.locator("#open-filters").click()
        self.page.locator("#stores .chip").filter(has_text=re.compile(r"^Netto")).click()
        self.page.locator('[data-sort="price"]').click()
        self.page.locator("#close-filters").click()
        self.assertEqual(set(self.page.locator("#list .badge").all_text_contents()), {"Netto"})
        prices = self.page.locator("#list .side .price").all_text_contents()
        parsed = [float(p.removesuffix(" kr").replace(",", ".")) for p in prices]
        self.assertEqual(parsed, sorted(parsed))
        self.page.locator("#open-filters").click()
        self.page.locator("#cats button").filter(has_text=re.compile(r"^Dairy")).click()
        self.page.locator("#close-filters").click()
        self.assertGreater(self.page.locator("#list article.offer").count(), 0)
        self.page.locator("#open-filters").click()
        self.page.locator("#reset-filters").click()
        self.page.locator('[data-when="upcoming"]').click()
        self.page.locator("#close-filters").click()
        upcoming = sum(bool(o.get("from")) and datetime.fromisoformat(o["from"]) > datetime.fromisoformat(self.feed["generatedAt"]) for o in self.feed["offers"])
        expect(self.page.locator("#count")).to_have_text(f"{upcoming} offer" + ("" if upcoming == 1 else "s"))

    def test_member_details_prices_and_picture_zoom(self):
        self.open()
        higher = next(o for o in self.feed["offers"] if o.get("sourceKey") == "bilka-plus" and o.get("nonMemberPrice", 1e9) < o["price"])
        for offer in (self.netto, self.bilka, higher):
            with self.subTest(source=offer["sourceKey"], price=offer["price"]):
                self.detail(offer)
                facts = self.page.locator("#view-detail .facts")
                expect(facts).to_contain_text("Requires " + offer["membership"])
                expect(facts).to_contain_text("Non-member price")
                expect(facts.locator("a")).to_have_attribute("href", offer["sourceUrl"])
                expect(self.page.locator("#view-detail .detail-price .pre, #view-detail .detail-price .save")).to_have_count(0)
                picture = self.page.locator("#view-detail .detail-pic")
                self.page.wait_for_function("document.querySelector('#view-detail .detail-pic img')?.naturalWidth > 0")
                picture.click()
                expect(picture).to_have_class("detail-pic zoomed")
                self.page.locator("#view-detail .back").click()

    def test_other_member_chains_exact_comparisons_and_percentage_promotion(self):
        keys = {"coop-365discount", "coop-superbrugsen", "lidl-plus"}
        present = {o.get("sourceKey") for o in self.feed["offers"]}
        if not keys.intersection(present):
            self.skipTest("Feed predates the Coop and Lidl Plus integrations")
        self.assertTrue(keys.issubset(present), "Collect every new member source before this check")
        self.open()
        for key in sorted(keys):
            offer = next(o for o in self.feed["offers"] if o.get("sourceKey") == key
                         and o.get("nonMemberPrice") is not None and o.get("nonMemberPriceIsUpperBound") is False)
            self.detail(offer)
            expect(self.page.locator("#view-detail .facts")).to_contain_text("Requires " + offer["membership"])
            comparison = self.page.locator("#view-detail dt").filter(has_text="Non-member price").evaluate("node => node.nextElementSibling.textContent")
            self.assertNotIn("Up to", comparison)
            self.page.locator("#view-detail .cartbtn").click()
            self.page.locator("#view-detail .back").click()
        promotion = next(o for o in self.feed["offers"] if o.get("sourceKey") == "coop-superbrugsen" and o["price"] is None)
        self.detail(promotion)
        expect(self.page.locator("#view-detail h2")).to_contain_text("30 %")
        expect(self.page.locator("#view-detail .detail-price .price")).to_have_text("")
        self.page.locator("#view-detail .cartbtn").click()
        self.page.locator("#view-detail .back").click()
        self.page.locator('[data-tab="cart"]').click()
        self.page.reload(wait_until="domcontentloaded")
        expect(self.page.locator("#cart .membership")).to_have_count(4)
        expect(self.page.locator("#cart")).to_contain_text("Requires Lidl Plus")
        expect(self.page.locator("#cart")).to_contain_text("Requires Coop")

    def test_ordinary_mousse_search_and_expiry_unknown_observation(self):
        offer = next((o for o in self.feed["offers"] if o.get("sourceKey") == "bilkatogo-offers"
                      and o.get("sourceProductId") == "125829"), None)
        if offer is None:
            self.skipTest("Feed has no ordinary BilkaToGo promotion selection")
        self.open()
        self.search("Chokolademousse Protein Lab")
        card = self.page.locator("#list article.offer").filter(has=self.page.locator("h3", has_text=offer["heading"]))
        expect(card).to_have_count(1)
        expect(card.locator(".price")).to_have_text("10 kr")
        expect(card.locator(".membership")).to_have_count(0)
        expect(card.locator(".valid")).to_contain_text("Price checked")
        self.detail(offer)
        expect(self.page.locator("#view-detail .facts")).to_contain_text("expiry not published")
        expect(self.page.locator("#view-detail .facts")).not_to_contain_text("Requires Bilka Plus")
        self.page.locator("#view-detail .detail-bar .star").click()
        self.page.locator("#view-detail .cartbtn").click()
        self.page.locator("#view-detail .back").click()
        self.page.locator('[data-tab="cart"]').click()
        expect(self.page.locator("#cart")).to_contain_text("Price checked")
        self.page.clock.set_fixed_time(datetime.fromisoformat(self.feed["generatedAt"]) + timedelta(days=1))
        self.server.payload["offerFeeds"][0]["status"] = "cached"
        self.page.reload(wait_until="domcontentloaded")
        expect(self.page.locator("#status")).not_to_be_empty()
        expect(self.page.locator("#cart .price")).to_have_text("10 kr")
        expect(self.page.locator("#cart .membership")).to_have_count(0)
        self.page.locator('[data-tab="offers"]').click()
        expect(self.page.locator("#list article.offer")).to_have_count(0)
        self.page.locator('[data-tab="starred"]').click()
        expect(self.page.locator("#starred .offer.idle")).to_have_count(1)
        expect(self.page.locator("#starred")).to_contain_text("checked")

    def test_saved_member_cart_and_stars_survive_missing_offers(self):
        self.open()
        for offer in (self.netto, self.bilka):
            self.detail(offer)
            self.page.locator("#view-detail .detail-bar .star").click()
            self.page.locator("#view-detail .cartbtn").click()
        self.page.locator("#view-detail .back").click()
        self.page.locator('[data-tab="offers"]').click()
        expect(self.page.locator("#featured .membership").filter(has_text="Requires Netto+").first).to_be_visible()
        expect(self.page.locator("#featured .membership").filter(has_text="Requires Bilka Plus").first).to_be_visible()
        self.page.locator('[data-tab="cart"]').click()
        expect(self.page.locator("#cart .membership")).to_have_count(2)
        self.page.reload(wait_until="domcontentloaded")
        expect(self.page.locator("#cart .membership")).to_have_count(2)
        names = {self.netto["heading"], self.bilka["heading"]}
        # Stars also match related names across stores; remove those offers too
        # to exercise the saved-price view after a product disappears entirely.
        tokens = {word.casefold() for name in names for word in name.split()}
        self.server.payload["offers"] = [o for o in self.feed["offers"] if not any(
            word in o["heading"].casefold() for word in tokens)]
        self.page.reload(wait_until="domcontentloaded")
        expect(self.page.locator("#cart .membership")).to_have_count(2)
        self.page.locator('[data-tab="starred"]').click()
        expect(self.page.locator("#starred .offer.idle")).to_have_count(2)
        expect(self.page.locator("#starred")).to_contain_text("Requires Netto+")
        expect(self.page.locator("#starred")).to_contain_text("Requires Bilka Plus")

    def test_watch_words_free_text_cart_and_clear_ticked(self):
        self.open()
        self.page.locator('[data-tab="starred"]').click()
        self.page.locator("#watch-word").fill(self.netto["heading"])
        self.page.locator("#watch-word").press("Enter")
        expect(self.page.locator("#starred .tag")).to_have_text("watch word")
        self.page.locator('[data-tab="cart"]').click()
        self.page.locator("#cart-word").fill(self.netto["heading"])
        self.page.locator("#cart-word").press("Enter")
        expect(self.page.locator("#cart .deal")).to_contain_text("Requires Netto+")
        self.page.locator('#cart [role="checkbox"]').click()
        expect(self.page.locator("#cart .citem.done")).to_have_count(1)
        self.page.locator("#cart-clear-done").click()
        expect(self.page.locator("#cart .citem")).to_have_count(0)

    def test_cached_and_unavailable_source_notices(self):
        self.server.payload["memberFeeds"][0]["status"] = "cached"
        self.server.payload["memberFeeds"][1]["status"] = "unavailable"
        self.open()
        expect(self.page.locator("#member-status")).to_contain_text("Netto+ could not refresh. Showing saved offers")
        expect(self.page.locator("#member-status")).to_contain_text("Bilka Plus (BilkaToGo Odense) offers are temporarily unavailable.")
        expect(self.page.locator("#member-status")).not_to_contain_text("Netto+: selected member offers")
        expect(self.page.locator("#member-status")).not_to_contain_text("Bilka Plus (BilkaToGo Odense): selected member offers")

    def test_offline_reload_keeps_offers_and_saved_cart(self):
        self.open()
        self.detail(self.netto)
        self.page.locator("#view-detail .cartbtn").click()
        self.page.locator("#view-detail .back").click()
        self.page.wait_for_function("navigator.serviceWorker.controller !== null")
        self.page.wait_for_function("async () => !!(await caches.match('/flier-summary/data/offers.json'))")
        self.context.set_offline(True)
        with self.page.expect_response(lambda r: r.url.endswith("/data/offers.json")) as loaded:
            self.page.reload(wait_until="domcontentloaded")
        self.assertTrue(loaded.value.from_service_worker)
        expect(self.page.locator("#list article.offer").first).to_be_visible()
        self.page.locator('[data-tab="cart"]').click()
        expect(self.page.locator("#cart .membership")).to_have_text("Requires Netto+")

    def test_failed_refresh_keeps_the_current_list_and_date(self):
        self.open()
        count = self.page.locator("#count").inner_text()
        date = self.page.locator("#status").inner_text()
        self.server.fail_data = True
        with self.page.expect_response(lambda r: r.url.endswith("/data/offers.json") and r.status == 503):
            self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(self.page.locator("#count")).to_have_text(count)
        expect(self.page.locator("#status")).to_have_text(date)

    def test_cached_english_names_preserve_star_keys(self):
        self.open()
        self.detail(self.netto)
        self.page.locator("#view-detail .detail-bar .star").click()
        self.page.locator("#view-detail .back").click()
        self.page.evaluate("([key, text]) => localStorage.setItem('flier-summary:en', JSON.stringify({[key]: text}))", [self.netto["heading"], "Cached English product name"])
        self.page.reload(wait_until="domcontentloaded")
        self.page.locator('[data-lang="en"]').click()
        self.search(self.netto["heading"])
        expect(self.page.locator("#list h3").filter(has_text="Cached English product name").first).to_be_visible()
        self.page.locator('[data-lang="da"]').click()
        expect(self.page.locator("#list h3").filter(has_text=self.netto["heading"]).first).to_be_visible()
        self.assertEqual(self.page.evaluate("JSON.parse(localStorage.getItem('flier-summary:stars'))[0].key"), self.netto["heading"])

    def test_backup_restore_of_watch_words(self):
        self.open()
        self.page.locator('[data-tab="starred"]').click()
        self.page.locator("#watch-word").fill("Backup test word")
        self.page.locator("#watch-word").press("Enter")
        with self.page.expect_download() as download:
            self.page.locator("#export").click()
        saved = self.artifacts / "stars-backup.json"
        download.value.save_as(saved)
        self.assertEqual(json.loads(saved.read_text())[0]["key"], "Backup test word")
        self.page.locator('#starred button[aria-label="Remove Backup test word"]').click()
        self.page.locator("#import").set_input_files(saved)
        expect(self.page.locator("#starred")).to_contain_text("Backup test word")

    def test_mobile_and_desktop_have_no_horizontal_overflow(self):
        self.open()
        self.search(self.bilka["heading"])
        for width, height in ((390, 844), (1440, 1000)):
            self.page.set_viewport_size({"width": width, "height": height})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            expect(self.card(self.bilka).first).to_be_visible()
            self.page.wait_for_function("Array.from(document.querySelectorAll('#list .thumb img')).some(img => img.naturalWidth > 0)")
            self.page.screenshot(path=str(self.artifacts / f"offers-{width}.png"), animations="disabled")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--artifacts", required=True)
    args = parser.parse_args()
    BrowserSmoke.feed = json.loads(Path(args.data).read_text())
    BrowserSmoke.artifacts = Path(args.artifacts)
    BrowserSmoke.artifacts.mkdir(parents=True, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BrowserSmoke))
    (BrowserSmoke.artifacts / "report.json").write_text(json.dumps({
        "browser": "Chromium", "feedGeneratedAt": BrowserSmoke.feed["generatedAt"],
        "offerCount": len(BrowserSmoke.feed["offers"]), "testsRun": result.testsRun,
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "notes": "Real collected feed; source failure/offline scenarios simulated; English names from seeded local cache.",
    }, indent=2) + "\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
