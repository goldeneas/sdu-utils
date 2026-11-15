# flier-summary

A phone-first web app (PWA) that collects this week's supermarket offers in **Odense** from
**Netto, 365discount, Bilka, SuperBrugsen and Lidl** in one list, and lets you **star** the products you like.

- **Offers** tab: everything valid today, or "Coming up" for fliers that start in the next days. Filter by store,
  search ("kaffe", "kylling", ...), sort by most recent first (the default, based on the offer’s start date), store, biggest discount, lowest price or name. Tap a product to open its page with a big, zoomable picture, the full text, dates and similar offers.
  **Featured for you** at the top shows today's offers that match your stars (product stars first, then watch words),
  and matching cards in the list get a gold outline. **Category chips** (Protein, Meat & fish, Dairy & eggs, ...) come
  from keywords in the offer name, because the flier API has no categories; odd products end up in "Other".
- **Starred** tab: the products you starred. Stars remember the *product name*, not this week's offer, so a starred
  item lights up under "On sale now" whenever any of the five stores has it in a flier again (the red badge on the
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
which publishes the fliers of all five chains. It asks for offers valid around Odense (15 km radius) and writes a
small `data/offers.json` that the app loads. Only the Python standard library is used.

### Public member offers (experimental, opt-in)

`--netto-plus` adds an importer for the public selection on
[Netto+](https://netto.dk/netto-plus/). **It is not enabled in the deploy workflow:**
direct access to Netto/Bilka is blocked by the development environment's HTTP policy.
The parser has offline tests using representative HTML, but still needs validation
against a live HTML capture before enabling scheduled collection. The public page
does not establish complete coverage of offers in the Netto app.

```sh
python3 flier-summary/scraper/fetch_offers.py --netto-plus --previous previous-offers.json
```

The importer requires a member-offer label, heading, explicit price and readable
expiry on every card; a missing or malformed card fails the entire member source.
Relative expiry dates use the collection date in Europe/Copenhagen; responses
whose HTTP date or cache age crosses local midnight are rejected. Start dates
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

Member prices show **Requires Netto+ / Bilka Plus** in cards, featured offers,
product details, saved cart entries and remembered starred prices. Details link
to the source and distinguish the non-member comparison price. A source notice
identifies the limited public selection and distinguishes saved offers from
temporarily unavailable member offers. Variant IDs include purchase conditions,
so equal names and prices with different pack sizes or limits are kept distinct.

Bilka's public Plus page currently provides program information. The BilkaToGo
[Plus page](https://www.bilkatogo.dk/inspiration/om-bilka-togo/bilka-plus-koncept/)
links selected prices to `/s?query=plus`, but its public HTML does not expose a
product list through the research tool. Product requests in the live browser
still need inspection; no importable feed has been verified. Bilka collection is
not implemented yet.
Personal coupons and local food-waste clearance are outside this importer.

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
promotions, local clearance/short-dated products and Netto+ or personalized promotions may not appear
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

Yes, it is hosted on GitHub Pages, next to `wise-tram-copier`, by `.github/workflows/deploy-pages.yml`:

- A static page cannot fetch the flier API directly from the phone (no CORS), so the workflow fetches the offers
  on GitHub's servers and publishes them together with the app. Nothing is committed back to the repo.
- It runs on every push to `main` that touches the app, and **every morning at 03:15 UTC**, so the list is fresh each day.
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
