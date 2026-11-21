# Flight Scanner

An installable PWA with all matching round trips from **Billund (BLL), Copenhagen
(CPH) and Malmö (MMX)** to Italy. The scanner runs in GitHub Actions; the browser
reads the published results without credentials or a backend.

After deployment: <https://goldeneas.github.io/sdu-utils/flight-scanner/>.

## App

- **All flights:** every matching round trip found by the scan, including prices
  above budget and alternatives that share an outbound or return flight.
- **Within budget:** an optional browser filter, with no result-count limit.
- **Double weekend:** an additional search mode for future trips with credited
  days in exactly two consecutive weekends. Choose the weekend start day
  (Friday by default); weekends end on Sunday. Separate switches control whether
  the arrival day and the departure day earn weekend credit, both on by default.
  Weekdays at home still count, and excluded weekend travel days are not counted
  as weekdays. These preferences are saved on the device.
- Double weekend ranks offers by **most weekend days, fewest weekdays, then
  lowest price**. Each date pair shows its best-ranked fare and day counts;
  cheaper alternatives with fewer weekend days remain in its offer details.
  Counting uses local destination arrival through local return departure,
  including partial travel days. If arrival is unknown, outbound departure date
  is used. Existing airport, budget and calendar filters still apply; the mode
  searches the selected saved scan and does not run a new provider search.
- Filter the full set independently by **outbound departure**, **outbound arrival**,
  **return departure** and **return arrival** airports, including itineraries with
  different airports on the return trip.
- **Direct flights only (both ways)** requires zero stops on both legs. These
  browser filters work with existing saved scans and do not trigger a new search.
- The list shows **one entry per outbound/return date pair**, with the lowest
  round-trip price among offers matching the current filters. Click an entry to
  open all its offers, including different times, airlines and routes, with
  booking links. Offers within a date pair are ordered by price.
- Sort date pairs by their lowest price or departure/return date. Both the list
  of date pairs and the offers within a pair have pages of 40; pagination does
  not cap or discard results. Changing filters updates the groups and minima.
- Switch between **List** and **Calendar**. Each outbound day shows the lowest
  saved round-trip price across all return dates; choosing an outbound date
  updates the return calendar to prices for that departure. Select a return day
  to see the matching date pair below. Click a selected day again to clear that
  date while keeping the other date selected. The lowest fare in each month is highlighted.
  Both calendars respect airport, direct-flight and budget filters. A dash means
  no matching fare was saved, not that flights are sold out.
- Enter either or both dates directly in either view; **Clear dates** restores
  all days. Dates remain selected when switching views or refreshing, and reset
  when choosing another scan. Calendar prices come from the selected saved scan;
  selecting dates does not run a live search.
- **Scan:** choose the latest scan or an earlier saved scan. Daily and manual runs
  are retained separately, including multiple runs on the same day.
- See local flight times, stops, nights, fare sources and booking links. Different
  return airports and separate tickets are explicitly marked.
- Install from the browser menu, or Safari → Share → Add to Home Screen on iPhone.
  The app and last downloaded price index are available offline. Flight details
  are downloaded only when opening a date pair; previously downloaded details
  can also be read offline. Opening new dates requires a connection.
- Refresh reloads the selected scan. Departed flights stay accessible and are
  labelled for reference. Previously opened scans can be read offline.

## Daily scan and deployment

The shared `.github/workflows/deploy-pages.yml` workflow runs every day at
**03:15 UTC** (04:15 in winter / 05:15 in summer in Italy and Denmark).
It can also be started manually from **Actions → Deploy web apps to GitHub Pages
→ Run workflow**. Pushing changes does not trigger a run.
Scheduled runs use the default branch and may be delayed by GitHub.
Pages must use **Source: GitHub Actions**, as the other modules do.

The `flights` job installs dependencies, runs the scanner tests, reads
`config.yaml`, and writes the complete result set to `data/flights.json`. Only
exact duplicate quotes are removed; alternative providers, prices and airlines
are retained. The configured departure dates, stay length and stop limit still
determine which round trips match the search.

The `deploy` job combines the result
with the other PWAs in one Pages artifact. Only static assets and flight results
are included in the flight app's web directory. The repository root page is
unchanged.

Complete snapshots are compressed and committed to the dedicated **`flight-data`**
branch, with a history index. Only the **three newest saved scans** are retained
in that index and in the branch's current scan files; older files are removed.
Source code on `main` is unaffected by data updates. The flight job has repository contents
write permission for this archive; the deployment job retains read-only contents
access. Pages publishes compact browser indexes and compressed detail chunks
for the retained scans without contacting a fare provider. Artifacts are kept for 90 days
as an additional recovery copy, independently of the durable data branch.

Full snapshots begin with the first scan after the history update. The last published
snapshot is imported when available. Older snapshots contain only the highlights
that were previously saved; the app labels those snapshots explicitly.

The job has a time limit. If sources fail, the last available snapshot is preserved
with its original timestamp and a visible warning. Partial results are identified;
a successful search with no matching fares produces an empty result. A failed
flight job does not prevent the other modules from publishing. The internal job
entry point is `scanner.publish`; there is no interactive scanner CLI, terminal
report, CSV/text export or notification service.

## Sources

- **Ryanair:** live one-way fares, combined into round trips.
- **Google Flights:** one-way fares from multiple airlines through the unofficial
  `fast-flights` library, combined with Ryanair fares where applicable.
- **Travelpayouts / Aviasales:** cached round-trip prices. Optional: add
  `TRAVELPAYOUTS_TOKEN` under **Settings → Secrets and variables → Actions →
  Repository secrets**. Without it, the other sources still run.

Unofficial endpoints can change or block requests. Prices may change, cached fares
may expire, and bags or extras may cost more. Separate-ticket itineraries require
checking each booking and arranging any travel between different airports.

## Configuration

Edit `config.yaml` and push to `main` to update the scheduled search.

| Setting | Purpose |
| --- | --- |
| `airports.origins` / `destinations` | Departure and destination IATA codes |
| `search.currency` / `max_price` | Currency and total round-trip deal budget |
| `search.top_n` / `top_per_airport` | Compatibility highlights for older installed app versions; never limit the full export |
| `search.window_days` / `exclude_next_days` | Departure search window |
| `search.min_nights` / `max_nights` | Stay length; returns may extend beyond the departure window |
| `search.max_transfers` | Maximum stops per leg |
| `search.unique_flights` | Avoid repeated legs in compatibility highlights; full results keep these alternatives |
| `search.request_delay_seconds` | Delay between monthly provider requests |
| `sources.*` | Enable fare sources and combinations with different return airports |
| `google_flights.*` | Airlines, concurrency, date spacing, query limit and request delay |

Google Flights uses **8 concurrent requests**, with a 0.5-second pause per worker.
The progress line printed every 25 completed requests is a reporting interval;
it does not limit or batch the scan. Tune `google_flights.workers` to change
concurrency. Actual speed depends on provider latency and throttling.

## Development

Python 3.10+ is required for the scheduled scanner. The PWA is buildless HTML,
CSS and JavaScript.

```bash
cd flight-scanner
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests
npm ci
npm test
```

To preview existing results, serve the repository root with a local HTTP server
and open `/flight-scanner/`. A snapshot must exist at
`flight-scanner/data/flights.json`; the app shows an unavailable state otherwise.
The app stays buildless; Node 24 and jsdom are used only for automated tests.
The internal Pages job reads `PREVIOUS_FLIGHTS_PATH` for failed-scan fallback,
writes to `data/flights.json`, and uses `scanner.history` to archive results and
stage `data/history/index.json` and `data/history/scans/*.json.gz` for Pages.

The deploy job runs `python -m scanner.browser ../_site/flight-scanner/data` after
restoring scan data. It creates `data/browser/latest.json`, compact history
indexes and compressed chunks of at most 200 complete offers each. Index rows
combine only offers with identical dates, local arrival day, airport filters,
stops, currency and budget tier; each preserves its exact count and minimum. The phone never parses
the full scan to draw the list/calendar. It fetches one selected date pair's
chunks sequentially and releases details on close. The service worker caches
bytes without parsing a second copy and never prefetches complete scans.
