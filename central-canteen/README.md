# central-canteen

An iPhone-friendly, offline-capable weekly menu viewer for
<https://jtkmenu.torvekoekken.dk/86>, specifically **The Central Canteen** (canteen ID `701`).

## Use and installation

Open <https://goldeneas.github.io/sdu-utils/central-canteen/> in Safari, then choose
**Share → Add to Home Screen**. The last successfully downloaded menu is available offline.
The manifest uses standalone display, a module-local scope and dedicated app icons.

The page shows the source's dishes and categories, opening hours, a shortcut for each
published day and a Today marker. Dates and the current Monday–Sunday week use
Europe/Copenhagen. Days without a planned menu keep the source's note. A saved menu
from an earlier week is explicitly labelled; it is never relabelled as this week's menu.
Source spelling and language are preserved.

## Data and daily refresh

The existing `.github/workflows/deploy-pages.yml` publishes this module alongside the other
apps on pushes to main and daily at 03:15 UTC. GitHub Pages is static, so the workflow uses
Python Playwright/Chromium to render the Blazor Server source, selects canteen `701` and
the current ISO year/week, and writes `data/menu.json` into the deployment artifact.
It waits for the requested week's cards, parses only dated mobile cards (the desktop
markup repeats dishes), and requires all five weekday cards plus at least one dish.
Incomplete pages, wrong weeks and source failures do not replace a good menu.

On failure it selects the newest usable menu from the previously published JSON and
`seed-menu.json`, preserving the original generation time. The seed is the real rendered
source supplied on 9 November 2026 for ISO week 46, not invented sample content. The app
shows a source-update warning when fallback is used. Once a live fetch succeeds, that
menu takes over; a successful response with no actual dishes is not treated as an update.
The source is an unofficial dependency and its markup may change.

The source hostname was blocked in the development environment. Parser and browser
checks use the supplied HTML; the live fetch runs in GitHub Actions. The original HTML
is retained as `scraper/fixtures/week-2026-46.html` for regression tests.

## Development

```sh
python3 -m unittest discover -s central-canteen/scraper
python3 -m pip install -r central-canteen/scraper/requirements.txt
python3 -m playwright install chromium
python3 central-canteen/scraper/fetch_menu.py
python3 -m http.server 8000
```

Open <http://localhost:8000/central-canteen/>. To use the saved source without network or
Playwright, run:

```sh
python3 central-canteen/scraper/fetch_menu.py --html central-canteen/scraper/fixtures/week-2026-46.html --week 2026-W46
```

`--previous` and `--seed` enable fallback. `CANTEEN_BROWSER_PATH` optionally selects an
existing Chromium executable for local testing. Generated `data/` is ignored by Git.
Menu text is rendered with `textContent`, never inserted as HTML.

Bump the version in `sw.js` when changing the app shell. Its cache cleanup deletes only
`central-canteen-*` entries; the other modules also retain their own cache prefixes so
all installed PWAs can coexist on the same GitHub Pages origin.
