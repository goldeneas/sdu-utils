"""Keep complete scan snapshots on a dedicated Git branch and stage them for Pages."""
from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .publish import load_previous

BRANCH = "flight-data"


def results_count(snapshot: dict) -> int:
    if isinstance(snapshot.get("flights"), list):
        return len(snapshot["flights"])
    # Older snapshots only contain highlights. Preserve what is recoverable.
    rows = snapshot.get("top", []) + [
        row for group in snapshot.get("per_airport", {}).values() for row in group
    ]
    return len({json.dumps(row, sort_keys=True) for row in rows})


def save_scan(snapshot: dict, directory: Path, run_id: str) -> bool:
    """Append an immutable compressed snapshot; retries of the same run are idempotent."""
    if not snapshot.get("generated_at"):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid scan run ID")
    stamp = datetime.fromisoformat(snapshot["generated_at"])
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    name = stamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{run_id}.json.gz"
    target = directory / "scans" / name
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    target.write_bytes(gzip.compress(payload, mtime=0))
    index_path = directory / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"schema_version": 1, "scans": []}
    index["scans"].append({
        "file": f"scans/{name}",
        "generated_at": snapshot["generated_at"],
        "status": snapshot["status"],
        "count": results_count(snapshot),
        "complete_results": isinstance(snapshot.get("flights"), list),
    })
    index["scans"].sort(key=lambda entry: (entry["generated_at"], entry["file"]), reverse=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def preserve_history(repository: Path, output: Path, previous_path: str | None = None) -> None:
    """Restore history, append this run, and publish with a normal non-forced Git push."""
    def git(*args: str, cwd: Path = repository, **kwargs):
        return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, **kwargs)

    remote = git("ls-remote", "--exit-code", "origin", f"refs/heads/{BRANCH}")
    if remote.returncode not in (0, 2):
        raise RuntimeError("Could not read the scan history branch")
    exists = remote.returncode == 0
    if exists:
        git("fetch", "--depth=1", "origin", f"refs/heads/{BRANCH}", check=True)
        base = "FETCH_HEAD"
    else:
        tree = git("mktree", input="", check=True).stdout.strip()
        base = git("-c", "user.name=github-actions[bot]", "-c",
                   "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                   "commit-tree", tree, "-m", "Initialize flight scan history", check=True).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="flight-history-") as temporary:
        checkout = Path(temporary) / "history"
        git("worktree", "add", "--detach", str(checkout), base, check=True)
        try:
            output.mkdir(parents=True, exist_ok=True)
            latest_path = output / "flights.json"
            stored_latest = load_previous(str(checkout / "latest.json.gz"))
            previous = load_previous(previous_path)
            # Import the last published snapshot when history is first introduced.
            if not exists and previous:
                save_scan(previous, checkout, "import")

            snapshot = json.loads(latest_path.read_text()) if latest_path.exists() else None
            recovered = max(
                (data for data in (previous, stored_latest) if data),
                key=lambda data: data["generated_at"], default=None,
            )
            if (not snapshot or snapshot["status"] in ("stale", "unavailable")) and recovered:
                snapshot = {**recovered, "status": "stale",
                            "attempted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                latest_path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")

            if snapshot and snapshot.get("generated_at"):
                if snapshot["status"] in ("ok", "partial"):
                    run_id = os.getenv("GITHUB_RUN_ID", "local") + "-" + os.getenv("GITHUB_RUN_ATTEMPT", "1")
                    save_scan(snapshot, checkout, run_id)
                payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
                (checkout / "latest.json.gz").write_bytes(gzip.compress(payload, mtime=0))

            # Stage before pushing, so a failed archive push still leaves a recoverable artifact.
            history = output / "history"
            history.mkdir(exist_ok=True)
            if (checkout / "index.json").exists():
                shutil.copy2(checkout / "index.json", history / "index.json")
                shutil.copytree(checkout / "scans", history / "scans", dirs_exist_ok=True)

            git("add", "--all", cwd=checkout, check=True)
            if git("diff", "--cached", "--quiet", cwd=checkout).returncode:
                git("-c", "user.name=github-actions[bot]", "-c",
                    "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "commit", "-m", "Preserve daily flight scan results", cwd=checkout, check=True)
                git("push", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=checkout, check=True)
        finally:
            git("worktree", "remove", "--force", str(checkout), check=True)


if __name__ == "__main__":
    preserve_history(Path.cwd().parent, Path("data").resolve(), os.getenv("PREVIOUS_FLIGHTS_PATH"))
