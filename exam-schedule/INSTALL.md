# Installing sdu-exam-watch

A complete installation guide for macOS and Linux. For what the tool does and
why it works, see [README.md](README.md).

- [Requirements](#requirements)
- [1. Get the code](#1-get-the-code)
- [2. Install](#2-install)
- [3. Configure](#3-configure)
- [4. Verify](#4-verify)
- [5. Schedule it](#5-schedule-it)
  - [macOS (LaunchAgent)](#macos-launchagent)
  - [Linux (systemd timer — recommended)](#linux-systemd-timer--recommended)
  - [Linux (cron)](#linux-cron)
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
| **Network** | Outbound HTTPS to `mitsdu.dk` and (for ntfy) `ntfy.sh`. |
| **Packages** | **None.** The tool is standard-library only. |
| **OS** | macOS or Linux. |

> **The command is `python3`, not `python`.** Fresh macOS and many Linux
> installs have no bare `python` on `PATH`. Every command below uses `python3`.

---

## 1. Get the code

```bash
git clone <this-repo> sdu-exam-watch
cd sdu-exam-watch
```

Or copy the directory across (e.g. `rsync -a sdu-exam-watch/ server:/opt/`).
All commands below assume you are **in the project root**.

---

## 2. Install

There are two supported ways to run it. Pick one.

### Option A — no install (run from the checkout)

Nothing to build; just point Python at `src/`:

```bash
PYTHONPATH=src python3 -m sdu_exam_watch --version
PYTHONPATH=src python3 -m sdu_exam_watch --config config.toml check
```

Good for a quick trial or a locked-down machine. You must set `PYTHONPATH=src`
every time and always invoke it as `-m sdu_exam_watch`.

### Option B — install a `sdu-exam-watch` command (recommended)

In a virtual environment, so nothing leaks into the system Python:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e .
./.venv/bin/sdu-exam-watch --version
```

You then either use the full path `./.venv/bin/sdu-exam-watch`, or activate the
environment in your shell:

```bash
source .venv/bin/activate
sdu-exam-watch --version
```

`pip install -e .` is an *editable* install: it links to the source tree, so a
`git pull` takes effect immediately with no reinstall.

> **Linux note:** if `venv` is missing, install it first:
> `sudo apt install python3-venv` (Debian/Ubuntu) or
> `sudo dnf install python3` (Fedora).
>
> **No `pip`/internet?** Use Option A instead — there is nothing to download.

---

## 3. Configure

Generate a starter config. This also creates a **random ntfy topic** and writes
the MSc Software Engineering target for you:

```bash
./.venv/bin/sdu-exam-watch init
```

```text
Wrote config.toml

Next steps:
  1. Install the free 'ntfy' app from the App Store.
  2. In the app, subscribe to the topic: sdu-exam-9f3a1c7d
  ...
```

**Write down the topic** — that is what you subscribe to on your phone.

### Subscribe on your phone

1. Install the free **ntfy** app (App Store / Play Store).
2. Tap **+** and subscribe to the topic printed above.

No account and no developer certificate are involved.

### Reusing an existing topic

Moving to a new machine? Reuse the same topic so your existing phone
subscription keeps working:

```bash
./.venv/bin/sdu-exam-watch init --topic sdu-exam-9f3a1c7d
```

### Choosing the config location

By default the tool looks for `./config.toml`, then
`~/.config/sdu-exam-watch/config.toml`. To be explicit (recommended in service
units), pass `--config`:

```bash
./.venv/bin/sdu-exam-watch --config /opt/sdu-exam-watch/config.toml check
```

### What to edit

Open `config.toml`. The parts most people change:

```toml
[settings]
interval_hours = 6      # how often to poll (1 = hourly)
state_file     = "state.json"   # relative to this file

[notify]
ntfy_topic   = "sdu-exam-9f3a1c7d"
attach_files = true     # attach the real PDF/Excel to the notification

[[target]]
name       = "MSc Software Engineering (Odense)"
programmes = ["Kandidat i Software Engineering (MSc)"]
```

- **`programmes`** must match the name in the spreadsheet's `Udd` column. Run
  `summary` (below) to check. The MSc Software Engineering value is correct as
  generated.
- **Add more programmes** by adding another `[[target]]` block (e.g. a
  bachelor programme).
- **Traffic:** each check makes 3 requests and downloads nothing unless
  something changed. See
  [README → How often does it check](README.md#how-often-does-it-check-and-how-much-traffic).

---

## 4. Verify

Run these in order. Each one proves a different layer.

```bash
# 1. Can it reach your phone? (sends a real push)
./.venv/bin/sdu-exam-watch test-notify

# 2. Can it read SDU's page and your programme's exams?
./.venv/bin/sdu-exam-watch summary

# 3. Record the current state. Silent on the first run — see the caveat below.
./.venv/bin/sdu-exam-watch check -v

# 4. What did it record?
./.venv/bin/sdu-exam-watch status
```

`summary` should print something like:

```text
== MSc Software Engineering (Odense)
   https://mitsdu.dk/da/mit_studie/kandidat/civilingenioer_i_softwareengineering/eksamen/eksamensplan
   Exam schedule for the Faculty of Engineering Summer 2026 - Odense
   10 exam(s) for ('Kandidat i Software Engineering (MSc)',)

• 2026-06-01 — Model-based Software Development
• 2026-06-09 — Software Technology for Internet of Things
…
```

To see exactly what a notification would contain **without sending it**:

```bash
./.venv/bin/sdu-exam-watch check --dry-run --force-notify
```

---

## 5. Schedule it

### macOS (LaunchAgent)

```bash
./.venv/bin/sdu-exam-watch install-launchd
# or override the interval:
./.venv/bin/sdu-exam-watch install-launchd --interval-hours 6
```

This writes and loads
`~/Library/LaunchAgents/dk.sdu.examwatch.plist`, running `check` at the
configured interval **and at login**. Verify:

```bash
launchctl list | grep examwatch                 # exit status should be 0
tail -f ~/Library/Logs/sdu-exam-watch/stdout.log
```

Change the interval by editing `interval_hours` in `config.toml` and re-running
`install-launchd` (it reloads cleanly). Remove it with
`uninstall-launchd`.

### Linux (systemd timer — recommended)

A timer is preferred over cron because `Persistent=true` runs a missed check
after the machine has been off — the same behaviour the macOS agent gives you.

Create `/etc/systemd/system/sdu-exam-watch.service` (replace `YOUR_USER` and
the path):

```ini
[Unit]
Description=Watch SDU exam schedules
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=YOUR_USER
WorkingDirectory=/opt/sdu-exam-watch
ExecStart=/opt/sdu-exam-watch/.venv/bin/sdu-exam-watch check --config /opt/sdu-exam-watch/config.toml
```

Create `/etc/systemd/system/sdu-exam-watch.timer`:

```ini
[Unit]
Description=Run SDU exam watch periodically

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sdu-exam-watch.timer
systemctl list-timers sdu-exam-watch.timer      # next run time
journalctl -u sdu-exam-watch.service -n 20      # logs
```

Set `OnUnitActiveSec` to your desired interval (`1h`, `6h`, …).

> **Without root:** put the two units in `~/.config/systemd/user/`, use
> `systemctl --user enable --now sdu-exam-watch.timer`, and run
> `sudo loginctl enable-linger YOUR_USER` so it runs when you are not logged in.

### Linux (cron)

If you prefer cron, add a line with `crontab -e`:

```cron
# every hour
0 * * * * cd /opt/sdu-exam-watch && ./.venv/bin/sdu-exam-watch check --config config.toml >> watch.log 2>&1
```

Cron does **not** catch up missed runs if the machine was off.

### Foreground

For testing, containers, or a long-lived terminal:

```bash
./.venv/bin/sdu-exam-watch daemon --interval-hours 6
```

---

## First-run behaviour (important)

The **first** `check` on a machine records a *baseline* and deliberately stays
silent — otherwise installing the tool would immediately alert you about a
schedule you already know about.

The consequence: **a schedule published before you install will not trigger a
notification.** If the exam plan may already be out, either look at it directly:

```bash
./.venv/bin/sdu-exam-watch summary
```

…or opt into a first-run alert for one run: set `notify_on_first_run = true` in
`config.toml`, run `check`, then set it back to `false`.

> When moving from one machine to another, do **not** copy `state.json`. A fresh
> baseline on the new machine is the correct behaviour; copying state would make
> the new machine miss the next real change.

---

## Updating

```bash
cd /opt/sdu-exam-watch
git pull
./.venv/bin/python -m pip install -e .   # usually unnecessary (editable install)
```

`config.toml` and `state.json` are never overwritten by an update. Run the test
suite after updating if you want to be sure (see below).

---

## Uninstalling

```bash
# macOS: remove the scheduled job
./.venv/bin/sdu-exam-watch uninstall-launchd

# Linux (systemd)
sudo systemctl disable --now sdu-exam-watch.timer
sudo rm /etc/systemd/system/sdu-exam-watch.{service,timer}
sudo systemctl daemon-reload

# then, if you want the files gone too
rm -rf /opt/sdu-exam-watch
rm -rf ~/.config/sdu-exam-watch        # if you used the default config location
```

Finally, unsubscribe from the topic inside the ntfy app.

---

## File locations

| What | Where |
| --- | --- |
| Config | `./config.toml`, else `~/.config/sdu-exam-watch/config.toml` (override with `--config`) |
| State | `settings.state_file` (default `state.json`, relative to the config file) |
| macOS logs | `~/Library/Logs/sdu-exam-watch/stdout.log` and `stderr.log` |
| Linux logs | `journalctl -u sdu-exam-watch.service` (systemd) or `watch.log` (cron) |
| macOS agent | `~/Library/LaunchAgents/dk.sdu.examwatch.plist` |
| Linux units | `/etc/systemd/system/sdu-exam-watch.{service,timer}` |

---

## Troubleshooting

**`python: command not found`**
Use `python3` everywhere.

**`pip install -e .` fails on Linux**
Install venv support (`sudo apt install python3-venv`), or skip installing and
use [Option A](#option-a--no-install-run-from-the-checkout).

**No notification arrives**
Run `test-notify`. If the template arrives, check that the topic in
`config.toml` matches the one you subscribed to in the app (topics are
case-sensitive).

**`ntfy publish failed: HTTP 400`**
The error message now includes ntfy's own reason, e.g.
`…: request body must be valid JSON`. This indicates a malformed publish
payload; make sure you are running the current version of the tool.

**`summary` reports no exams**
Your `programmes` string does not match the spreadsheet's `Udd` value. The exact
names are in the Excel file's *Search Education* dropdown.

**First run printed `baseline recorded` and sent nothing**
That is intended — see [First-run behaviour](#first-run-behaviour-important).

**The macOS job does not run**
`launchctl list | grep examwatch` shows a non-zero status; read
`~/Library/Logs/sdu-exam-watch/stderr.log`. Re-run `install-launchd` to reload.

**It seems to have hung once**
SDU occasionally responds slowly; the client retries with backoff and then
falls back from `HEAD` to a full download. Occasional retry lines in the log are
normal and self-healing.

---

## Running the tests

No network required, no test dependencies:

```bash
python3 -m unittest discover -s tests -v
```

All 58 tests should pass.
