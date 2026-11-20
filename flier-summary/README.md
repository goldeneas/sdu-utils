# flier-summary

A phone-first web app (PWA) that collects this week's supermarket offers in **Odense** from
**Netto, 365discount, Bilka, SuperBrugsen, Lidl and REMA 1000** in one list, and lets you **star** the products you like.

- **Offers** tab: everything valid today, or "Coming up" for fliers that start in the next days. Filter by store,
  search ("kaffe", "kylling", ...), sort by most recent first (the default, based on the offer’s start date), store, biggest discount, lowest price or name. Tap a product to open its page with a big, zoomable picture, the full text, dates and similar offers.
  **Featured for you** at the top shows today's offers that match your stars (product stars first, then watch words),
  and matching cards in the list get a gold outline. **Category chips** (Protein, Meat & fish, Dairy & eggs, ...) come
  from keywords in the offer name, because the flier API has no categories; odd products end up in "Other".
  Select **Food** to see offers classified as food or drinks.
- **Starred** tab: the products you starred. Stars remember the *product name*, not this week's offer, so a starred
  item lights up under "On sale now" whenever any of the stores has it in a flier again (the red badge on the
  tab counts these). Items not on sale show where and for how much you last saw them.
- **Watch words**: on the Starred tab you can type a word like `Zoégas` or `oksemørbrad` to match every offer that
  contains it, even ones you have never seen.
- **Cart** tab: a one-off shopping list, separate from stars. Tap the basket next to the star on any offer (or **Add to cart** on its product page) to add that
  exact offer (store, price, picture, end date), or type anything ("mælk") at the top of the tab; typed items show
  the cheapest offer that matches them today. Tick items off as you shop, remove one with ×, clear the ticked ones,
  or empty the whole cart. Unlike stars, nothing comes back next week. The badge on the tab counts what is left to buy.
- **DA / EN** switch at the top: shows every product name in English instead of Danish. The setting is remembered
  on the phone. Names are machine translated by the fetcher when it can (see below); Google often refuses requests from GitHub's servers, so the phone translates the names on screen itself and keeps them in `localStorage`. Search finds both the Danish and
  the English name, and stars keep working on the Danish name, so switching never loses anything. The product page
  shows the original Danish name under the English one, which is handy in the shop.
- Stars live in the browser on your phone (`localStorage`). Use **Back up stars** / **Restore** to move them to
  another device or keep a copy before clearing site data.

## Where the offers come from

`scraper/fetch_offers.py` reads the public (unofficial, undocumented) API behind [etilbudsavis.dk](https://etilbudsavis.dk),
which publishes the fliers of these chains. It asks for offers valid around Odense (15 km radius) and writes a
small `data/offers.json` that the app loads. Only the Python standard library is used.

### Public member offers

`--netto-plus` imports the public selection on
[Netto+](https://netto.dk/netto-plus/). `--bilka-plus` imports public Plus prices
from the search used by [BilkaToGo](https://www.bilkatogo.dk/s?query=plus), scoped
to **Bilka Odense, Niels Bohrs Alle 150** (store `1654`, verified against the site's
public pickup-address listing). `--coop-members` adds the public Coop selections
for 365discount and SuperBrugsen, and `--lidl-plus` adds the current weekly Lidl
Plus prices. All four flags are configured in this branch's deploy workflow.
They take effect when the workflow is published and run; changing a branch does
not update the live site.

Live access and a full collection were verified on **15 November 2026**: six Netto+
cards, 148 Bilka Plus products across two complete search pages, two 365discount
and five SuperBrugsen member promotions, and 35 automatic Lidl Plus prices. Reviewed real
excerpts, source URLs, capture hashes and dated metadata are in `scraper/fixtures/`.
These are public selections, not complete coverage of the apps or a guarantee of
stock or identical pricing in every physical branch. Personal coupons are excluded.

`--bilka-store-offers` additionally collects **confirmed** public BilkaToGo
promotions for Odense, including products outside fliers and without Plus
membership. Its source is a separate `offerFeeds` snapshot, not a member feed. The collector
uses the website's public read-only browse cursor to exhaust the selection;
ordinary search exceeds its 1,000-result window and does not give exact counts.
Public store prices and mix conditions are used; coupon or personal cart prices
are not queried. Single-pack discounts require an explicit store `beforePrice`
above the current price; this comparison is shown on the detail page. The broad
`isInOffer` flag, campaign dates, labels such as `Skarp pris`/`Se Her`, and a
reduction from the root catalog reference are insufficient by themselves.
**Protein Lab Chokolademousse, 200 g, 10 kr** is therefore excluded: the observed
record has only a catalog-reference reduction, not a confirmed promotion.
Mix totals are preserved,
while variable-total promotions such as "3 for 2" retain their conditions without
an invented kr amount. Mixes costing the same as or more than buying the pieces
are excluded. Each exported deal carries `promotionEvidence`; the collector's
fallback and the app reject older BilkaToGo records without this evidence, so
cached files cannot restore the previous broad price selection. Published fliers and
the separately verified Bilka Plus selection continue to be included.

Some ordinary promotions publish no expiry. These carry `priceObservedAt` with
`from`/`till` left unknown. The app displays **Price checked …**, not a fictional
end date. An undated price is current only on its observation day in Copenhagen;
failed refreshes retain the original observation, and cannot keep an undated price
current indefinitely. Saved cart items and remembered starred prices retain the
observation date. Explicitly dated promotions keep their actual validity period.

```sh
python3 flier-summary/scraper/fetch_offers.py --netto-plus --bilka-plus --coop-members --lidl-plus --bilka-store-offers --previous previous-offers.json
```

The Netto importer requires a member-offer label, heading, explicit price and readable
expiry on every card; a missing or malformed card fails the entire member source.
Cards mentioning personal prices or coupons reject the source rather than
being published as prices for every member. Relative expiry dates use the member
page's own collection time in Europe/Copenhagen, even if flier downloads span
midnight. Missing HTTP dates, dates more than five minutes in the future and
responses whose HTTP date or cache age crosses local midnight are rejected. Start dates
are left unknown rather than invented. The non-member comparison price is stored
as `nonMemberPrice`, not as a historical price or a claimed discount.

Each member feed has a separate snapshot in `memberFeeds` with `status`,
`fetchedAt` and its original offers. On failure, only that feed reuses its old
snapshot and original expiry dates, without advancing its freshness timestamp.
Flier collection and member collection can succeed or fail independently.
Store `count` includes both sources; existing store `status` and `fetchedAt` still
describe its flier feed. Exact duplicates are collapsed; different prices, pack
sizes, conditions or membership requirements are preserved. A flier with unknown
membership conditions is not assumed to be the same offer as a Plus price.

Member prices show **Requires Netto+ / Bilka Plus / Coop / Lidl Plus** in cards, featured offers,
product details, saved cart entries and remembered starred prices. Details link
to the source and distinguish the non-member comparison price. A source notice
identifies the limited public selection and distinguishes saved offers from
temporarily unavailable member offers. Variant IDs include purchase conditions,
so equal names and prices with different pack sizes or limits are kept distinct.
Bilka's source product IDs also participate in deduplication: distinct variants
can share a name, price and pack size while having different product pictures.

Bilka's HTML contains program information; products come from its public Algolia
search index. The site's own public search-only key is used, without a login,
cookie, personal coupon activation or cart access. The importer requires
`cpOffer:true`, `nonsearchable:false` and assortment in store `1654`. It validates
every product and requires exact, exhaustive page counts, unique product IDs and
stable totals. Any failed or incomplete page rejects the entire Bilka member source.
The website API and its public search key are undocumented and can change; a
schema or access failure triggers the independent saved-snapshot fallback.

Bilka's monetary fields use øre and are converted to kroner. Explicit calendar
dates are interpreted in Europe/Copenhagen; they never extend on a failed refresh.
Mix offers preserve the total bundle price and required number of packs rather
than presenting a per-pack price. For single-pack offers, the ordinary price at
Odense is shown separately as `nonMemberPrice`; a Plus price can exceed an ordinary
promotion, so no saving or historical price is inferred. Mix bundles have no
invented ordinary comparison price. The BilkaToGo/Odense scope is shown in offer
descriptions and the source notice.
Personal coupons and local food-waste clearance are outside this importer.

Coop's [public member page](https://medlem.coop.dk/medlemsfordele/medlemstilbud/medlemstilbud/)
contains separate chain sections. The importer maps the actual chain logos and
public offer type (`2`) to 365discount or SuperBrugsen; it never assigns Kvickly or
Brugsen offers to another chain. Coop uses the CSS name `personal-offer-wrapper`
for these anonymous public cards too: the class name alone does not establish
personal eligibility. Every card requires an ID, title, validity period and either
an explicit fixed price or a clearly stated percentage promotion. Percentage-only
promotions keep `price: null`; a 30% promotion never becomes an invented kr price.
Month/day ranges without a year are anchored to a fresh, dated HTTP response in
Europe/Copenhagen, with an unambiguous nearby year. A failed refresh retains the
original resolved dates. Each Coop chain has its own snapshot and fallback.

Lidl's importer discovers the current weekly Plus campaign link on the official
homepage, then reads its embedded `data-grid-data` JSON. It requires explicit
`Med Lidl Plus` prices in the single observed Danish price region and rejects
ambiguous variants, missing cards and duplicate product IDs. Store availability
dates determine the start; price-authoring timestamps do not backdate an offer.
The explicit member-price expiry bounds the end even where the card omits a store
end date. Mix/bundle conditions and total prices are preserved, including packs
already described as e.g. `18 x 20 cl`, without multiplying them again.

Lidl coupon prices are excluded because a public advertisement does not establish
eligibility for every member. [Lidl's coupon information](https://www.lidl.dk/c/lidl-plus-kuponer/s10014639)
distinguishes personal, opening-day and reward coupons and requires activation.
Coop's fruit-and-vegetable bonus is likewise not treated as an immediate price
reduction. Comparison prices explicitly described as an upper bound retain
**Up to**; exact Coop/Lidl comparisons are displayed without that qualifier.

#### Check access and capture the actual pages

Run the diagnostic before attempting live validation (choose a **new** directory
each time, so an old capture cannot appear to be a successful fresh download):

```sh
python3 flier-summary/scraper/probe_member_sources.py --bilka-products --other-members --bilka-store-prices --out-dir work/member-sources/check-01
```

It uses the same anonymous standard-library HTTP client, proxy, TLS verification
and headers as the Netto+ collector. It checks Netto+, Bilka Plus, BilkaToGo,
the BilkaToGo Plus information page and its linked `/s?query=plus` selection.
The report distinguishes proxy CONNECT denial from an origin HTTP error and
continues to check other sources after a failure. Accessible HTML is saved as
UTF-8 with a SHA-256 checksum, collection time and selected response headers;
cookies are not retained. Netto captures also undergo the freshness and parser
checks. Invalid Netto markup is retained for inspection, without exporting offers.
With `--bilka-products`, it also saves each actual public search JSON response,
its hash and the validation result, including invalid responses for investigation.
It does not save an importable offers feed or any session credentials.
`--other-members` also retains the actual Coop member page, validates each target
chain independently, discovers and captures the current Lidl campaign and checks
its automatic member prices. Invalid markup is retained with validation failures.
`--bilka-store-prices` captures every public ordinary-price browse page and checks
cursor termination and unique products. It does not produce a publishable feed.

Exit status is 1 if any access or validation check fails. Exit status 0
establishes HTML access and successful Netto parsing; `--bilka-products` additionally
checks Bilka product parsing and complete pagination. Neither mode proves full app
coverage or enables scheduled collection. Captures belong in `work/`, not the published `data/`
directory. Promote a reviewed, minimal real HTML excerpt and its dated metadata
to a test fixture only after live access succeeds.

```sh
python3 flier-summary/scraper/fetch_offers.py           # writes flier-summary/data/offers.json
python3 -m unittest discover -s flier-summary/scraper  # offline tests
```

The fetcher also adds an English `headingEn` to each offer using Google Translate's free web endpoint (no key).
Store and own-brand names in `KEEP_WORDS` are left untouched, so "Netto" does not become "Net". The deploy passes
yesterday's published file as `--previous`, so only new product names are translated each night; if translation
fails the offers simply stay in Danish. Use `--no-translate` to skip it.

The store list (names, dealer ids) and the location are at the top of `fetch_offers.py`. If a dealer id stops
working the script looks the chain up by name and prints a note.

Because the API is unofficial it can change without notice. When a store download fails or its pagination
cannot be verified as complete, the fetcher keeps that store's previously published offers (provided by
`--previous`) while updating the other stores. Each store carries `status` (`ok`, `cached`, `unavailable`)
and `fetchedAt`; cached data retains its original timestamp across repeated failures. A store without a
saved copy is marked unavailable. If there are no offers at all, the fetcher exits non-zero without writing
and the workflow attempts to reuse the whole published file.

Below each page title the app shows `Oggi` if the file was generated today in Denmark
(Europe/Copenhagen), otherwise the generation date as `DD/MM/YYYY`, without a time. If the date
is unknown, the label is empty. A failed refresh keeps already loaded offers and their date visible.
This label describes the file generation date; individual stores may still use saved offers after a failed download.

## How collection and search work

1. The scheduled GitHub Action resolves the five chain identifiers through `/dealers`.
2. For each chain, it requests `/catalogs` within **15 km of central Odense** (`55.3959, 10.3883`).
   This location is fixed: the app does not select or verify an individual branch.
3. It requests `/offers` separately for every returned catalog, in pages of 100. The API's 1,000-result
   ceiling applies to each query. A page error, unexpected response type, full 1,000-result window or
   full 100-catalog listing is treated as an incomplete download, triggering the per-store fallback.
   If no catalogs are returned, it tries a chain-wide offer query with the same location.
4. The fetcher drops blank headings, removes duplicate offer IDs **within each chain**, preserves the
   full description, and adds keyword-based categories and optional English heading translations.
5. The PWA downloads the generated JSON on opening, returning to the foreground, or reconnecting.
   Its service worker uses the network first and falls back to saved data offline.
6. Search runs **locally over that downloaded file**, not against Netto or eTilbudsavis in real time.
   Every normalized search word must appear somewhere in the Danish heading, available English heading
   or description. Store, category and Today/Coming up filters are also applied and remembered on the device.
   Today includes only offers whose start/end timestamps include the device's current time. Initially
   60 matching cards are rendered; Show more reveals the remaining matches.

### Why an offer seen at Netto may be missing

The source covers published fliers, not a live inventory of every branch's shelf prices. In-store-only
promotions, local clearance/short-dated products, member prices outside the public
Netto+/BilkaToGo selections and personalized promotions may not appear
in this feed. Geographic coverage does not guarantee an offer applies to every branch in that area.
These are coverage limits; a successful API download does not prove every in-store promotion was included.

Other possible causes are a nightly update that has not yet run, an upstream omission, saved/offline data,
a download failure, a remembered filter, a validity date mismatch, or an English name that was never
translated. Previously, page failures returned partial lists without a completeness marker and failed
chains could be published with zero offers while other chains succeeded. The per-store fallback and
freshness label address those failure modes. Descriptions were also truncated at 300 characters;
they are now kept in full for search and offer conditions.

For a specific missing-offer investigation, record the product, branch, price, visit time and whether
it appears in a flier or only on a shelf label/Netto+. Compare the source flier, the published JSON and
then the app filters. Without these details, the exact cause cannot be established.

## Hosting on GitHub Pages

### Browser checks before publishing

`tests/browser_smoke.py` runs fifteen end-to-end checks against a collected feed
using Chromium. It starts an isolated localhost site and browser profile, without
changing your saved preferences or publishing anything. It checks search, filters,
member prices and images, featured offers, cart and stars persistence, backup and
restore, source notices, failed refreshes, offline reload and mobile/desktop layout.
The English-name check uses a saved translation; it does not test Google's service.
Source failures and offline conditions are simulated, while the feed is collected
from the real sources.

Install Playwright in your development Python environment, then run:

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
python3 flier-summary/scraper/fetch_offers.py --netto-plus --bilka-plus --coop-members --lidl-plus --bilka-store-offers --no-translate --out /tmp/flier-offers.json
python3 flier-summary/tests/browser_smoke.py --data /tmp/flier-offers.json --artifacts /tmp/flier-browser-results
```

The current smoke scenarios require a fresh feed with all five member selections,
a Netto dairy offer, a Bilka Plus price above its ordinary comparison price and
a percentage-only Coop promotion. The new-chain scenario is skipped for legacy
feeds containing neither Coop nor Lidl Plus.
The Bilka regressions verify explicit discount details and inject the old
chocolate-mousse record into a cached feed to confirm it is absent from search
and direct details. An undated confirmed mix deal stops appearing as current on
the next day, while its saved cart and last-seen price retain their observation.
Keep the dated feed with the test report to reproduce a run; a future selection
can require updating those scenarios. Screenshots and `report.json` are written
to the artifacts directory. These checks cover Chromium at phone and desktop
sizes; installation on a physical phone and other browsers require separate tests.

### Publishing

Yes, it is hosted on GitHub Pages, next to `wise-tram-copier`, by `.github/workflows/deploy-pages.yml`:

- A static page cannot fetch the flier API directly from the phone (no CORS), so the workflow fetches the offers
  on GitHub's servers and publishes them together with the app. Nothing is committed back to the repo.
- It runs **every morning at 03:15 UTC**, so the list is fresh each day.
  You can also run it by hand: Actions, *Deploy web apps to GitHub Pages*, *Run workflow*.
- The app is at `https://<user>.github.io/sdu-utils/flier-summary/`.

See [INSTALL.md](INSTALL.md) for installing it on your phone.

## Files

- `index.html`: the page and its styles
- `app.js`: loading offers, filters, stars
- `sw.js`, `pwa.js`, `manifest.webmanifest`, `icons/`: installable/offline wrapper (same setup as `wise-tram-copier`)
- `scraper/`: the offer fetcher and its tests (not published to the site)
- `data/offers.json`: generated, git-ignored

Bump `VERSION` in `sw.js` when you change the app files so installed copies refresh. The offers file is always fetched
fresh when online, and the last copy is used offline.
