# flier-summary

A phone-first web app (PWA) that collects this week's supermarket offers in **Odense** from
**Netto, 365discount, Bilka and SuperBrugsen** in one list, and lets you **star** the products you like.

- **Offers** tab: everything valid today, or "Coming up" for fliers that start in the next days. Filter by store,
  search ("kaffe", "kylling", ...), sort by store, biggest discount, lowest price or name. Tap a product to open its page with a big, zoomable picture, the full text, dates and similar offers.
  **Featured for you** at the top shows today's offers that match your stars (product stars first, then watch words),
  and matching cards in the list get a gold outline. **Category chips** (Protein, Meat & fish, Dairy & eggs, ...) come
  from keywords in the offer name, because the flier API has no categories; odd products end up in "Other".
- **Starred** tab: the products you starred. Stars remember the *product name*, not this week's offer, so a starred
  item lights up under "On sale now" whenever any of the four stores has it in a flier again (the red badge on the
  tab counts these). Items not on sale show where and for how much you last saw them.
- **Watch words**: on the Starred tab you can type a word like `Zoégas` or `oksemørbrad` to match every offer that
  contains it, even ones you have never seen.
- Stars live in the browser on your phone (`localStorage`). Use **Back up stars** / **Restore** to move them to
  another device or keep a copy before clearing site data.

## Where the offers come from

`scraper/fetch_offers.py` reads the public (unofficial, undocumented) API behind [etilbudsavis.dk](https://etilbudsavis.dk),
which publishes the fliers of all four chains. It asks for offers valid around Odense (15 km radius) and writes a
small `data/offers.json` that the app loads. Only the Python standard library is used.

```sh
python3 flier-summary/scraper/fetch_offers.py           # writes flier-summary/data/offers.json
python3 -m unittest discover -s flier-summary/scraper  # offline tests
```

The store list (names, dealer ids) and the location are at the top of `fetch_offers.py`. If a dealer id stops
working the script looks the chain up by name and prints a note.

Because the API is unofficial it can change without notice. When a fetch fails the deploy keeps the previously
published offers, and the run shows a warning in the Actions tab.

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
