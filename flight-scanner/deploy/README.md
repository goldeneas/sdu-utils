# flight-scanner deal watcher — scheduling helpers

The watcher is designed to be run periodically by the OS rather than kept
resident, so it survives reboots and sleeps. Two options:

## systemd user timer (recommended on Linux)

```bash
# 1. Put the config where the unit expects it
mkdir -p ~/.config/flight-scanner
cp config.example.toml ~/.config/flight-scanner/config.toml
$EDITOR ~/.config/flight-scanner/config.toml   # set ntfy_topic (dates are automatic)

# 2. Test it once
./run.sh watch --config ~/.config/flight-scanner/config.toml --dry-run

# 3. Install the units
mkdir -p ~/.config/systemd/user
cp deploy/flight-scanner-watch.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now flight-scanner-watch.timer

# Inspect / trigger
systemctl --user list-timers flight-scanner-watch.timer
systemctl --user start flight-scanner-watch.service
journalctl --user -u flight-scanner-watch.service -n 50
```

## cron

```cron
# every 6 hours; adjust paths to your checkout
0 */6 * * * cd "$HOME/Workspace/sdu-utils/flight-scanner" && ./run.sh watch --config "$HOME/.config/flight-scanner/config.toml" >> "$HOME/.local/state/flight-scanner/cron.log" 2>&1
```

## All-in-one (no scheduler)

```bash
./run.sh watch --config ~/.config/flight-scanner/config.toml --loop
```
