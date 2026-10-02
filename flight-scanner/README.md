# flight-scanner — Odense (DK) ⇄ Salerno (IT)

Finds the cheapest **whole trip** — not just the cheapest flight — between
Odense, Denmark and Salerno, Italy, balancing money against travel time.

It joins three things that budget flight search sites make you assemble by hand:

1. **Live low-cost fares** (Ryanair's public fare feed) from every airport near
   Odense to every Italian airport it serves.
2. **Ground transfers at both ends** — DSB/Rejsekort trains in Denmark and
   Trenitalia/Italo/Bus in Italy — modelled with realistic cost *and* duration.
3. **A cost/time optimizer** that ranks complete round-trips with a single
   tunable number: how many euros one hour of your life is worth.

Salerno is a high-speed rail stop, and Naples is 40–60 minutes away, so the
classic trick applies: fly into a big cheap hub (Rome, Milan, Bologna, Venice,
Turin) and take the train down, or fly straight into Naples when the parents can
collect you.

## Quick start

No dependencies — Python 3.11+ standard library only.

> New here? [INSTALL.md](INSTALL.md) is the full step-by-step setup guide
> (install, ntfy topic, scheduling).

```bash
# always the next 30 days, ~1-week trips (the defaults):
./run.sh --pickup-naples

# narrower window, with flight numbers and bookable ground hops:
./run.sh --days 14 --details

# or install it (gives you the `flight-scanner` command)
pip install -e .
flight-scanner --pickup-naples
```

## What it prints

- **Top trips** — best `cost + time_value × hours` balance.
- **Pareto front** — the cheapest trip for each achievable total travel time, so
  you can see exactly what an extra hour buys you.
- **Per-destination cheapest** — e.g. *out to Rome, back from Milan*, which is
  often cheaper than a same-airport round-trip.
- **Costs split air vs ground** — every total reads like
  `EUR137 (air 61 + ground 76)`, and each leg shows `air EUR31 + ground EUR18`,
  so it's obvious what the flights cost versus the trains/buses.
- **Details (`--details`)** — per trip: the Ryanair flight number (e.g. `FR406`),
  and each ground hop to book (station pair, operator/service, frequency, and the
  operator's site). Add `--live` for real train numbers and times.
- Optional `--json out.json` for the full result set.

## Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--days` | `30` | Rolling window: always look this many days ahead. |
| `--out-start` / `--out-end` | — | Optional explicit outbound window (override). |
| `--ret-start` / `--ret-end` | — | Optional explicit return window (override). |
| `--trip-min` / `--trip-max` | `5` / `9` | Allowed nights at home (short trip). |
| `--details` | off | Flight numbers and bookable ground hops. |
| `--live` | off | Fetch real train/bus times (DSB for DK, Transitous for IT). |
| `--rail-danish` | `rejseplanen` | Provider for Danish legs. |
| `--rail-italian` | `transitous` | Provider for Italian legs. |
| `--rejseplanen-access-id` | — | Free DSB/Rejseplanen key (labs.rejseplanen.dk). |
| `--origins` | `CPH,AAR,BLL` | Danish/nearby departure airports (ground legs must be known). |
| `--time-value` | `8` | EUR you'll pay to save one hour (raise it to favour fast options). |
| `--overhead` | `2.5` | Fixed airport overhead hours per flight (check-in, bags, exits). |
| `--ground` | `min` | Ground pricing: `min` = advance/online, `typ` = walk-up. |
| `--pickup-naples` | off | Parents collect you in Naples ⇒ NAP transfer is free. |
| `--oneway` | off | Only scan the outbound direction. |
| `--top` | `15` | Rows to print per table. |
| `--no-cache` | off | Bypass the 6-hour on-disk cache. |
| `--json FILE` | — | Write the full result set. |

## Deal watcher — alerts on your phone (ntfy)

`watch` re-runs the scan on a schedule, remembers the best prices it has ever
seen, and pushes an [ntfy](https://ntfy.sh) notification only when something is
actually worth booking:

- **first scan** — one baseline alert (set `deals.notify_first_run = false` to stay silent)
- **new best** — the cheapest total ever beats the previous best by `improve_by` EUR
- **under threshold** — any round-trip at or below `deals.max_total`
- **price drop** — a trip you were already alerted about got cheaper

Unchanged results never re-notify, so your phone stays quiet between real deals.

### Setup

1. Install the free **ntfy** app (iOS/Android) and subscribe to a topic name.
   Make it long and unguessable — anyone who knows it can read/publish on ntfy.sh.
2. Copy the config and set your ntfy topic (the look-ahead is automatic):
   ```bash
   cp config.example.toml config.toml
   $EDITOR config.toml
   ```
3. Preview without sending anything:
   ```bash
   ./run.sh watch --config config.toml --dry-run
   ```
4. Send a real check, then schedule it (systemd timer or cron — see
   [deploy/README.md](deploy/README.md)):
   ```bash
   ./run.sh watch --config config.toml
   ./run.sh watch --config config.toml --loop   # stay resident instead
   ```

After `pip install -e .` the command is `flight-scanner-watch`. The watcher also
accepts `--state`, `--interval-hours`, `--json`, and `-v`.

### Config sections (`config.toml`)

- **`[trip]`** — `days` (rolling look-ahead), `trip_min` / `trip_max` (nights),
  and `pickup_naples`. The other scanner knobs (`origins`, `time_value`,
  `ground`) keep sensible defaults and are overridable per CLI run.
- **`[deals]`** — `mode` (`best` / `threshold` / `both`), `max_total`,
  `improve_by`, `max_alerts`, `notify_first_run`.
- **`[notify]`** — `ntfy_topic`, `ntfy_server`, `ntfy_token`, `priority`,
  `tags`, `click`, and `stdout = true` for cron mail/dry runs.
- **`[rail]`** — `live` (add real times), `danish` / `italian` provider names,
  `rejseplanen_access_id`, and `timezone`. See *Live train/bus times*.
- **`[watch]`** — `interval_hours` for `--loop`, and `state_file`.

Deal memory lives in `watch-state.json` next to the config (atomic writes; a
corrupt file is treated as empty). Delete it to re-baseline.

## Data sources

- **Flights** — Ryanair *Fare Finder* public endpoints
  (`services-api.ryanair.com/farfnd/v4/...`), no API key. Prices are per adult,
  one-way, taxes included, **hand luggage only** (add bag/seat fees yourself).
  Route discovery is automatic: the tool asks which Italian airports each Danish
  origin actually serves in your window, then pulls the cheapest fare per day.
- **Odense → airport** — estimated DSB/Rejsekort fares and durations
  (`ground.py`). Verify on [rejseplanen.dk](https://www.rejseplanen.dk) / [dsb.dk](https://www.dsb.dk).
- **Italy airport → Salerno** — estimated Trenitalia/Italo/bus fares and times
  (`ground.py`). High-speed fares are dynamic: book early. Verify on
  [trenitalia.com](https://www.trenitalia.com) / [italotreno.it](https://www.italotreno.it).
- **Ground identifiers** — each ground leg carries curated *reference hops* you
  can book (station pair, operator and service, typical frequency, booking
  site). With `--live` (or `[rail] live = true`) those are replaced by **real
  dated services with train numbers** — see below.

### Live train/bus times

`--live` (scanner) and `[rail] live = true` (watcher) replace the estimated
ground hops with real dated connections:

| Leg | Provider | Notes |
| --- | --- | --- |
| Odense ↔ Danish airport | **DSB / Rejseplanen** | Official HAFAS API. Needs a **free `accessId`** from <https://labs.rejseplanen.dk/> → `rail.rejseplanen_access_id`. Covers DSB trains and Danish buses. |
| Italian airport ↔ Salerno | **Transitous** (open router) | No key. Returns real services, e.g. `FIUMICINO AEROPORTO -> ROMA TERMINI · TRENITALIA RV 4683` or `ROMA TERMINI -> SALERNO · TRENITALIA FR 9515`. |

```bash
./run.sh --details --live --rejseplanen-access-id YOUR_ID
```

> **Trainline cannot be used.** Its website API is protected by a DataDome
> captcha and returns `403` to non-browser clients; the `trainline` provider
> exists only to report that clearly. Transitous serves the same Italian
> Trenitalia/Italo services.

Live lookups are cached for 3 h and fall back to the curated model when a
provider or key is unavailable, so the tool never breaks.

### How the static ground model works

Without `--live`, ground fares/durations in `ground.py` are curated estimates
(advance fares, `--ground min`, or realistic walk-up, `--ground typ`) used for
**ranking** (fast and offline). Treat those lines as the services to search, not
confirmed connections. Flight fares are always live.

The `cache/` directory stores raw API responses for 6 hours; delete it to force
a refresh.

## How "good balance" is scored

```text
score = total_cost_EUR + time_value × total_hours
```

`total_hours` includes the flight, both ground transfers, and a fixed airport
overhead per flight. Set `--time-value 0` for pure-cheapest, `--time-value 25`
if a long layover is unacceptable.

## Ground model (summary)

**Odense →** `CPH` ~1h50 train, `BLL` ~2h train+bus, `AAR` ~3h train+bus,
`MMX` ~3h12 train+bus, `HAM` ~4h50 train.

**To Salerno from** `NAP` ~1h20 bus/train (~€5–9), `QSR` Salerno airport
~30 min, `FCO` ~2h55 train via Roma Termini, `BLQ` ~4h25, `PSA` ~4h10,
`VCE` ~5h, `BGY`/`MXP`/`LIN` ~6½–7h, `TRN` ~6h25, `BRI` ~4h, `SUF` ~3h10.

## Limitations & how to extend

- **Only Ryanair is queried live.** SAS, Norwegian, easyJet, Wizz, Volotea and
  ITA fly some of these routes too. To include them, add a provider module with
  the same two functions (`discover_destinations`, `cheapest_over_window`) that
  returns `ryanair.Fare` objects, then let `scan.py` merge it in.
- Fares shown are the airlines' *"from"* prices for those days; they can sell
  out or change. Always re-check before booking.
- Ground figures are planning estimates, not live quotes.

## Development

```bash
python3 -m unittest discover -s tests -v   # 45 unit tests, no network
ruff check src tests
./run.sh watch --config config.toml --dry-run --json run.json  # no POST
```
