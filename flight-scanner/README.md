# Flight Scanner

An installable PWA with the cheapest round trips from **Billund (BLL), Copenhagen
(CPH) and Malmö (MMX)** to Italy. The scanner runs in GitHub Actions; the browser
reads the published results without credentials or a backend.

After deployment: <https://goldeneas.github.io/sdu-utils/flight-scanner/>.

## App

- **Top deals:** the cheapest unique round trips within the configured budget.
- **By destination:** the best options per airport, including prices above budget.
- Filter by departure or destination airport, or sort by departure date.
- See local flight times, stops, nights, fare sources and booking links. Different
  return airports and separate tickets are explicitly marked.
- Install from the browser menu, or Safari → Share → Add to Home Screen on iPhone.
  The app and last downloaded results are available offline.
- Refresh loads the latest published scan. Departed flights are hidden.

## Daily scan and deployment

The shared `.github/workflows/deploy-pages.yml` workflow runs every day at
**03:15 UTC** (04:15 in winter / 05:15 in summer in Italy and Denmark).
It runs only on that schedule; pushing changes does not trigger a run.
Scheduled runs use the default branch and may be delayed by GitHub.
Pages must use **Source: GitHub Actions**, as the other modules do.

The `flights` job installs dependencies, runs the scanner tests, reads
`config.yaml`, and writes `data/flights.json`. The `deploy` job combines the result
with the other PWAs in one Pages artifact. Only static assets and flight results
are included in the flight app's web directory. The repository root page is
unchanged and no scan results are committed.

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
| `search.top_n` | Number of top deals |
| `search.top_per_airport` | Number of results per destination, regardless of budget |
| `search.window_days` / `exclude_next_days` | Departure search window |
| `search.min_nights` / `max_nights` | Stay length; returns may extend beyond the departure window |
| `search.max_transfers` | Maximum stops per leg |
| `search.unique_flights` | Avoid reusing individual flights in the top results |
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
```

To preview existing results, serve the repository root with a local HTTP server
and open `/flight-scanner/`. A snapshot must exist at
`flight-scanner/data/flights.json`; the app shows an unavailable state otherwise.
The internal Pages job reads `PREVIOUS_FLIGHTS_PATH` for failed-scan fallback and
writes to `data/flights.json`.
