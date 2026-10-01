# sdu-exam-watch

Get a **push notification on your iPhone** the moment SDU publishes (or
revises) your exam schedule — no app to build, no developer certificate, no
account, no dependencies.

It watches the official SDU programme page, notices when the exam-schedule
PDF/Excel is published or updated, reads the spreadsheet, and tells you *your*
exam dates.

```
📅 New SDU exam schedule published
MSc Software Engineering (Odense)

Exam schedule for the Faculty of Engineering Summer 2026 - Odense

Your exams (10):
• 2026-06-01 — Model-based Software Development
• 2026-06-09 — Software Technology for Internet of Things
• 2026-06-22 → 2026-06-26 — Modularization and Platform Design
…
```

The published PDF/Excel is **attached** to the notification as well (ntfy
fetches it server-side), so the full plan is on your phone, not just the
summary. Set `notify.attach_files = false` to send only the text.

---

## How SDU actually publishes exam schedules

This tool is built on what the university really does, which is worth knowing:

- Each programme has a page on **`mitsdu.dk`**, e.g. the MSc Software
  Engineering page:
  `https://mitsdu.dk/da/mit_studie/kandidat/civilingenioer_i_softwareengineering/eksamen/eksamensplan`
- That page links to the **Faculty of Engineering schedule** as a **PDF** and
  an **Excel** file, e.g.
  `…/teknik/eksamensplaner/eksamensplan_tek_summer2026_odense.xlsx`.
- Schedules are approved **early October** (winter exams) and **early March**
  (summer exams), and they *do* get revised — the PDF filename even carries a
  revision marker such as `…_v_april_7.pdf`.
- The spreadsheet contains a table (`XPlan`) with a column **`Udd`** listing
  which programmes each exam belongs to, e.g.
  `",,,Kandidat i Software Engineering (MSc),,,Alle eksamener"`. That is how
  the tool shows **your** exams instead of the whole faculty's.
- All of this is **public — no login required**.

The tool records a fingerprint of every linked file (`ETag`, `Last-Modified`,
size) and alerts you when the set of links changes or a file is modified.

---

## Why ntfy (and how to set up the iPhone part)

Apple does not allow unsigned, self-built apps to send push notifications, so
"notify my iPhone" normally means a paid developer account and a real app.

**[ntfy.sh](https://ntfy.sh)** avoids all of that:

1. Install the free **ntfy** app from the App Store.
2. Subscribe to a **topic** — any hard-to-guess string, e.g.
   `sdu-exam-9f3a1c7d`. (Topics on the public server are not password-protected,
   so pick something random; the tool generates one for you.)
3. That's it. `sdu-exam-watch` publishes to `https://ntfy.sh/<topic>` over
   plain HTTP and the notification appears on your phone.

Prefer something else? The tool also supports:

| Channel | Config key | Notes |
| --- | --- | --- |
| ntfy (iPhone/Android) | `notify.ntfy_topic` | **Recommended.** Free App Store app. |
| Webhook | `notify.webhook_url` | Discord/Slack/custom JSON POST. |
| macOS banner | `notify.macos_notification` | Local `osascript` notification. |
| stdout | `notify.stdout` | Prints to the log (good for testing). |

You can enable several at once.

---

## Requirements

- **Python 3.11+** (uses `tomllib`). Tested on macOS; works on Linux too.
- **Zero third-party packages** — standard library only. Nothing to `pip install`.

---

## Quick start

For a complete, platform-by-platform guide — macOS LaunchAgent, Linux systemd
timer, cron, configuration, uninstalling and troubleshooting — see
**[INSTALL.md](INSTALL.md)**.

```bash
# 1. Create a config (generates a random ntfy topic and the MSc SE target)
python3 -m sdu_exam_watch init

#    → prints the topic to subscribe to in the ntfy app

# 2. Check it reaches your phone
python3 -m sdu_exam_watch test-notify

# 3. Record the current state (first run is deliberately silent — see below)
python3 -m sdu_exam_watch check

# 4. Run it automatically every 6 hours (macOS)
python3 -m sdu_exam_watch install-launchd
```

(If you'd rather not install the package, prefix commands with
`PYTHONPATH=src` and run `python3 -m sdu_exam_watch …` from the repo.)

To install as a proper command:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
sdu-exam-watch --help
```

---

## Commands

| Command | What it does |
| --- | --- |
| `init` | Write a starter `config.toml` with a random ntfy topic. |
| `check` | Run one check and notify on changes. **This is what cron/launchd calls.** |
| `daemon` | Run `check` in a foreground loop. |
| `test-notify` | Send a test notification on every configured channel. |
| `summary` | Print the exams currently published for your programme. |
| `status` | Show what the last check saw (files, fingerprints, last run). |
| `install-launchd` | Install a macOS LaunchAgent running `check` periodically. |
| `uninstall-launchd` | Remove that LaunchAgent. |

Useful flags: `--config PATH`, `-v` (verbose), `-q` (quiet), `--dry-run`
(print instead of send), `--force-notify`.

---

## Configuration

Configuration is TOML. Generate a commented starting point with
`sdu-exam-watch init`, or copy [`config.example.toml`](config.example.toml).

```toml
[settings]
state_file          = "state.json"   # relative to this file
timeout_seconds     = 30
retries             = 3
hash_files          = false   # true = download + hash every file each check
summary_limit       = 12      # exams listed in a notification
notify_on_first_run = false   # true = also notify on the very first check
interval_hours      = 6       # used by install-launchd / daemon

[notify]
ntfy_topic  = "sdu-exam-9f3a1c7d"
ntfy_server = "https://ntfy.sh"
priority    = "high"                  # min | low | default | high | max
tags        = ["calendar", "tada"]
# Attach the published PDF/Excel itself to the notification. ntfy fetches the
# file server-side, so the real plan ends up on your phone. Set false to send
# only the text summary.
attach_files = true
# ntfy_token         = ""             # for a protected/self-hosted topic
# webhook_url        = ""
# macos_notification = false
# stdout             = false

[[target]]
name         = "MSc Software Engineering (Odense)"
url          = "https://mitsdu.dk/da/mit_studie/kandidat/civilingenioer_i_softwareengineering/eksamen/eksamensplan"
link_pattern = '\.(xlsx|xls|pdf)([?#]|$)'
programmes   = ["Kandidat i Software Engineering (MSc)"]
summary      = true
```

Add more `[[target]]` blocks to watch other pages (e.g. a bachelor programme,
or the faculty-wide list at `https://mitsdu.dk/da/service/tek/eksamensplan`).

> The `programmes` value must match the name in the spreadsheet's `Udd` column.
> Run `sdu-exam-watch summary` to see what it finds; the programme list is also
> visible in the Excel file's "Search Education" dropdown.

---

## Scheduling

### macOS (recommended): LaunchAgent

```bash
sdu-exam-watch install-launchd --interval-hours 6
```

This writes `~/Library/LaunchAgents/dk.sdu.examwatch.plist`, loads it, and runs
`check` every 6 hours and at login. Logs:

```
~/Library/Logs/sdu-exam-watch/stdout.log
~/Library/Logs/sdu-exam-watch/stderr.log
```

Remove it with `sdu-exam-watch uninstall-launchd`.

### cron / Linux

```cron
# every 6 hours
0 */6 * * * cd /path/to/exam-schedule && PYTHONPATH=src /usr/bin/python3 -m sdu_exam_watch check >> watch.log 2>&1
```

### Foreground

```bash
sdu-exam-watch daemon --interval-hours 6
```

---

## How often does it check (and how much traffic?)

`interval_hours` controls the cadence (default **6**, i.e. **4 checks/day**
plus one at login). Each check makes exactly **3 requests** — a `GET` of the
programme page and a `HEAD` per linked file — and downloads nothing unless
something changed:

| Situation | Requests per check | Approx. daily traffic |
| --- | --- | --- |
| Nothing changed (default) | 1 GET + 2 HEAD | ~600 KB |
| `hash_files = true` | 1 GET + 2 full downloads | ~5.5 MB |
| A change is detected | + one XLSX download (~0.8 MB) | once per change |

The client identifies itself with a `User-Agent`, follows redirects, and caps
timeouts, response size and redirect count. If SDU is briefly slow it retries
with exponential backoff (bounded).

To poll less, raise `interval_hours` (e.g. `12`). Around publication time
(early October / early March) you could lower it to `1`–`2` for a few days.

---

## How change detection works

For each target, every check:

1. fetches the page and extracts links matching `link_pattern`;
2. fingerprints each file:
   - normally via a cheap `HEAD` (`ETag` / `Last-Modified` / `Content-Length`),
   - or by downloading and SHA-256 hashing when the server sends no validators
     or when `hash_files = true`;
3. diffs against the previous run and classifies each file as **new**,
   **changed** or **removed**.

Design choices that keep it quiet and reliable:

- **The first check is a silent baseline.** Otherwise installing the tool would
  immediately "alert" you about a schedule you already know about. Set
  `notify_on_first_run = true` if you want that alert.
- **Page text is not used as a change signal** (only the linked files), so
  cookie banners, timestamps and other page chrome never cause false alarms.
- **A summary failure never loses the alert:** if the spreadsheet cannot be
  parsed, you still get the "schedule changed" notification, and the previously
  cached exams are kept.

---

## Verifying and troubleshooting

```bash
# What does it see right now, and which of my exams are on it?
sdu-exam-watch summary

# What did the last check record?
sdu-exam-watch status

# Show what would be sent, without sending
sdu-exam-watch check --dry-run -v
```

- **No notification on a new topic** → run `sdu-exam-watch test-notify`. If the
  template works but real alerts don't, check that the topic in the config
  matches the one you subscribed to in the app.
- **`summary` shows no exams** → your `programmes` string probably doesn't match
  the spreadsheet's `Udd` value. Check the Excel file's "Search Education"
  dropdown, or a target's page for the exact programme name.
- **SDU changes the page layout** → the table-based reader falls back to
  scanning for a header row automatically; if that ever breaks, `summary` will
  say no spreadsheet was found.
- **Topic privacy** → public ntfy topics are only as secret as their name. This
  is just your exam dates, but use a random topic (or a self-hosted
  `ntfy_server` with `ntfy_token`) if you prefer.

---

## Project layout

```
src/sdu_exam_watch/
  cli.py       # subcommands and orchestration
  config.py    # TOML loading, validation, defaults
  watch.py     # link discovery, fingerprinting, diffing, summaries
  http.py      # stdlib HTTP client (GET/HEAD/POST) with retries + redirects
  notify.py    # ntfy, webhook, macOS, stdout channels
  xlsx.py      # dependency-free reader for the SDU schedule workbook
  xmlsafe.py   # hardened XML parsing for downloaded files
  state.py     # atomic JSON state
  launchd.py   # macOS LaunchAgent install/uninstall
tests/         # unit tests, no network required (a fixture builds a sample workbook)
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Design and security notes

- **No third-party dependencies**, so it runs from a plain checkout, cron or
  LaunchAgent with nothing to install.
- **XML is treated as untrusted.** All parsing of downloaded workbooks goes
  through `xmlsafe.py`, which rejects any document type/entity declaration
  (the mechanism behind "billion laughs"/XXE) before parsing.
- **Only `http(s)` URLs are ever fetched** — no `file:` handler can be reached
  through a mistyped config.
- **Bounded**: request size cap, redirect cap, timeouts and retries.
- **Atomic state writes** (temp file + `os.replace`), so an interrupted run
  cannot corrupt the state.
