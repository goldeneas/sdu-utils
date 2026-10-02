#!/usr/bin/env bash
# Run the scanner or watcher straight from the source checkout (no install).
#   ./run.sh [scan] [scanner args...]
#   ./run.sh watch [watcher args...]
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m flight_scanner "$@"
