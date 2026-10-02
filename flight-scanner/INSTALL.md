# Installing flight-scanner

A step-by-step setup guide for the Odense ⇄ Salerno fare scanner and its
phone-alert watcher. For what it does and why it works, see [README.md](README.md).

- [Requirements](#requirements)
- [1. Get the code](#1-get-the-code)
- [2. Run it](#2-run-it)
  - [Option A — run from the checkout (no install)](#option-a--run-from-the-checkout-no-install)
  - [Option B — install commands (recommended)](#option-b--install-commands-recommended)
- [3. Configure](#3-configure)
- [4. Verify](#4-verify)
- [5. Schedule it](#5-schedule-it)
  - [Linux (systemd user timer — recommended)](#linux-systemd-user-timer--recommended)
  - [Linux (cron)](#linux-cron)
  - [macOS (LaunchAgent)](#macos-launchagent)
  - [Foreground](#foreground)
- [First-run behaviour (important)](#first-run-behaviour-important)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [File locations](#file-locations)
- [Troubleshooting](#troubleshooting)
- [Running the tests](#running-the-tests)

---

## Requirements

| | |
| --- | --- |
| **Python** | 3.11 or newer (uses `tomllib`). Check with `python3 --version`. |
| **Network** | Outbound HTTPS to `services-api.ryanair.com` and (for alerts) `ntfy.sh` or your own ntfy server. |
| **Packages** | **None.** Standard library only — no `pip install` needed to run it. |
| **OS** | Linux or macOS. |

> **The command is `python3`, not `python`.** Fresh macOS and many Linux
> installs have no bare `python` on `PATH`.

---

## 1. Get the code

If it is already on this machine, just enter the directory:

```bash
cd ~/Workspace/sdu-utils/flight-scanner
```

Otherwise copy/clone it anywhere and `cd` in. All commands below assume you are
**in the project root** (the folder containing `run.sh`).

---

## 2. Run it

There are two supported ways. Pick one.

### Option A — run from the checkout (no install)

Nothing to build. `run.sh` puts `src/` on the path for you:

```bash
./run.sh --help                 # the one-off scanner
./run.sh watch --help           # the periodic watcher
./run.sh --pickup-naples        # scan the next 30 days now
```

If you get `permission denied`, run `chmod +x run.sh` once.

Equivalent without `run.sh`:

```bash
PYTHONPATH=src python3 -m flight_scanner --pickup-naples
PYTHONPATH=src python3 -m flight_scanner watch --config config.toml
```

### Option B — install commands (recommended)

In a virtual environment, so nothing leaks into the system Python:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e .
./.venv/bin/flight-scanner --help
./.venv/bin/flight-scanner-watch --help
```

You then either use the full paths above, or activate the environment:

```bash
source .venv/bin/activate
flight-scanner --pickup-naples
flight-scanner-watch --config config.toml
```

The two entry points are:

| Command | What it does |
| --- | --- |
| `flight-scanner` | One-off scan, prints ranked trips. |
| `flight-scanner-watch` | Checks for deals and sends an ntfy alert. |

---

## 3. Configure

The **scanner** needs no configuration at all — it always scans the next 30
days. Configuration is only for the **watcher** (where to send alerts).

```bash
cp config.example.toml config.toml
```

You can keep `config.toml` next to the project, or in the standard location:

```bash
mkdir -p ~/.config/flight-scanner
cp config.example.toml ~/.config/flight-scanner/config.toml
```

The watcher looks in `./config.toml` first, then
`~/.config/flight-scanner/config.toml`.

Edit at least the ntfy topic:

```toml
[notify]
ntfy_topic = "change-me-to-a-long-random-topic"
```

Then install the free **ntfy** app (iOS/Android) and subscribe to that exact
topic. Use something long and unguessable — anyone who knows the topic can read
it on `ntfy.sh`. To self-host or use a protected topic:

```toml
ntfy_server = "https://ntfy.example.com"
ntfy_token  = "tk_..."
```

The full config is small; the important parts:

```toml
[trip]
days          = 30    # always look this many days ahead
trip_min      = 5     # nights at home (short trip)
trip_max      = 9
pickup_naples = true  # parents collect you in Naples => NAP transfer free

[deals]
max_total = 200       # alert on any round-trip <= EUR200 (0 = off)

[notify]
ntfy_topic = "change-me-to-a-long-random-topic"

[watch]
interval_hours = 6
```

`config.toml` holds your topic, so it is **git-ignored** — do not commit it.

---

## 4. Verify

Send yourself a test notification straight from the ntfy CLI first:

```bash
curl -d "hello from flight-scanner" https://ntfy.sh/YOUR-TOPIC
```

Then check the watcher without sending anything. It prints the alert it would
send, including the air/ground cost split, the Ryanair flight number, and the
train/bus hops to book (station pair, operator, frequency, booking site):

```bash
./run.sh watch --config config.toml --dry-run
```

> Train/bus legs are curated reference services by default. Enable live times
> with `[rail] live = true` (DSB/Rejseplanen needs a free accessId from
> <https://labs.rejseplanen.dk/>; Italian legs use the open Transitous router).
> Trainline is captcha-blocked and cannot be used.

When that looks right, do one real check:

```bash
./run.sh watch --config config.toml
```

You should see `checked N round-trips ... ; X new deal(s)` and, if there are
deals, `notified via ntfy`.

---

## 5. Schedule it

The watcher is a one-shot check, so a scheduler runs it periodically. Use any
one option below.

### Linux (systemd user timer — recommended)

```bash
mkdir -p ~/.config/flight-scanner
cp config.example.toml ~/.config/flight-scanner/config.toml
$EDITOR ~/.config/flight-scanner/config.toml        # set ntfy_topic

mkdir -p ~/.config/systemd/user
cp deploy/flight-scanner-watch.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now flight-scanner-watch.timer
```

The timer checks shortly after login and every 6 hours, and catches up after
sleep. Inspect and trigger it with:

```bash
systemctl --user list-timers flight-scanner-watch.timer
systemctl --user start flight-scanner-watch.service
journalctl --user -u flight-scanner-watch.service -n 50
```

The packaged unit runs `run.sh` from this checkout. If you installed with
Option B, edit the `ExecStart=` line to use `%h/.venv/bin/flight-scanner-watch`
or the commented alternative already in the unit file.

To keep it running when you are **not logged in** (e.g. a headless server):

```bash
loginctl enable-linger "$USER"
```

### Linux (cron)

```cron
# every 6 hours; adjust the paths
0 */6 * * * cd "$HOME/Workspace/sdu-utils/flight-scanner" && ./run.sh watch --config "$HOME/.config/flight-scanner/config.toml" >> "$HOME/.local/state/flight-scanner/cron.log" 2>&1
```

### macOS (LaunchAgent)

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/dk.flightscanner.watch.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dk.flightscanner.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd "$HOME/Workspace/sdu-utils/flight-scanner" &amp;&amp; ./run.sh watch --config "$HOME/.config/flight-scanner/config.toml"</string>
  </array>
  <key>StartInterval</key><integer>21600</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
PLIST
launchctl load ~/Library/LaunchAgents/dk.flightscanner.watch.plist
```

### Foreground

Simplest of all — stay resident and check on an interval (Ctrl-C to stop):

```bash
./run.sh watch --config config.toml --loop
```

---

## First-run behaviour (important)

The **first** check sends a baseline alert (unless you set
`deals.notify_first_run = false`). After that the watcher only pings you when
something *changes*: a new cheapest total, a trip that drops under
`max_total`, or an existing trip getting cheaper. Unchanged results never
re-notify.

Deal memory lives in `watch-state.json` next to the config. Delete it to
re-baseline from scratch.

---

## Updating

```bash
cd ~/Workspace/sdu-utils/flight-scanner
git pull                       # or copy the new files across
./.venv/bin/python -m pip install -e .   # only for Option B
./run.sh watch --config config.toml --dry-run
```

`config.toml`, `watch-state.json` and `cache/` are local and are not touched.

---

## Uninstalling

```bash
# stop the scheduler, if used
systemctl --user disable --now flight-scanner-watch.timer
rm -f ~/.config/systemd/user/flight-scanner-watch.{service,timer}

# Option B: remove the installed commands
./.venv/bin/python -m pip uninstall flight-scanner
rm -rf .venv

# local state/config (optional)
rm -f watch-state.json config.toml
rm -rf cache ~/.config/flight-scanner
```

---

## File locations

| Path | What |
| --- | --- |
| `./config.toml` or `~/.config/flight-scanner/config.toml` | Your watcher config (ntfy topic). |
| `watch-state.json` (next to the config) | Deal memory; delete to re-baseline. |
| `cache/` (repo root) or `~/.cache/flight-scanner` | Cached API responses (6 h). Override with `FLIGHT_SCANNER_CACHE`. |
| `src/flight_scanner/` | The Python package (scanner, watcher, ground model). |
| `deploy/` | systemd unit files and cron notes. |

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `python3: command not found` | Install Python 3.11+ (`python3 --version`). |
| `permission denied: ./run.sh` | `chmod +x run.sh`. |
| `configuration error: config file not found` | Pass `--config config.toml`, or use `./run.sh watch --dry-run` from the project root. |
| `no notification channel configured` | Set `notify.ntfy_topic` (or `notify.stdout = true`). |
| No alert on the first run | That is the baseline. Use `--dry-run` to see what it found; set `deals.notify_first_run = false` to keep it silent. |
| Nothing on my phone | Topic must match exactly; test with the `curl -d` command above. Check `ntfy_server` if self-hosted. |
| Prices look stale | Responses are cached 6 h. Scanner: add `--no-cache`. Or delete `cache/`. |
| Systemd timer never fires | `systemctl --user list-timers`; for headless use `loginctl enable-linger "$USER"`. |
| `scan failed: request failed ...` | Transient network/Ryanair issue; it retries and falls back to the last cache. Re-run later. |

---

## Running the tests

No extra packages needed:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Optional lint (only if you have `ruff`):

```bash
ruff check src tests
```

The suite is offline — it never calls Ryanair or ntfy.
