import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.history import preserve_history, save_scan
from scanner.publish import load_previous


def snapshot(day=11, count=65):
    return {
        "schema_version": 1,
        "generated_at": f"2026-11-{day:02d}T03:15:00+00:00",
        "attempted_at": f"2026-11-{day:02d}T03:15:00+00:00",
        "status": "ok", "search": {"origins": ["MMX"]},
        "flights": [{"price": i + 40} for i in range(count)],
        "top": [{"price": 40}], "per_airport": {},
    }


def test_archive_preserves_complete_snapshots_and_separate_manual_runs(tmp_path):
    original = snapshot()
    assert save_scan(original, tmp_path, "100-1")
    assert save_scan(snapshot(count=80), tmp_path, "101-1")
    assert not save_scan(snapshot(count=5), tmp_path, "100-1")
    index = json.loads((tmp_path / "index.json").read_text())
    assert sorted(entry["count"] for entry in index["scans"]) == [65, 80]
    assert all(entry["complete_results"] for entry in index["scans"])
    old = next(entry for entry in index["scans"] if "100-1" in entry["file"])
    assert json.loads(gzip.decompress((tmp_path / old["file"]).read_bytes())) == original


def test_old_highlights_can_be_preserved_but_failed_refreshes_are_not_new_scans(tmp_path):
    old = snapshot()
    del old["flights"]
    assert save_scan(old, tmp_path, "import")
    entry = json.loads((tmp_path / "index.json").read_text())["scans"][0]
    assert entry["count"] == 1 and not entry["complete_results"]
    assert not save_scan({**snapshot(), "generated_at": None}, tmp_path, "failed")
    with pytest.raises(ValueError):
        save_scan(snapshot(), tmp_path, "../../outside")


def git(directory, *args):
    return subprocess.run(["git", *args], cwd=directory, check=True, text=True, capture_output=True).stdout.strip()


def test_history_survives_new_runners_and_recovers_latest_without_touching_main(tmp_path, monkeypatch):
    remote, repository = tmp_path / "remote.git", tmp_path / "first-runner"
    git(tmp_path, "init", "--bare", str(remote))
    git(tmp_path, "init", "-b", "main", str(repository))
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@example.com")
    (repository / "README.md").write_text("Source code only\n")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "Initial source")
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "origin", "main")
    source_head = git(repository, "rev-parse", "HEAD")

    output = tmp_path / "first-output"
    output.mkdir()
    first = snapshot()
    (output / "flights.json").write_text(json.dumps(first))
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    preserve_history(repository, output)
    index = json.loads((output / "history/index.json").read_text())
    first_file = index["scans"][0]["file"]
    assert len(index["scans"]) == 1
    assert json.loads(gzip.decompress((output / "history" / first_file).read_bytes())) == first

    # A new runner only checks out main. The first scan must be restored from Git.
    fresh = tmp_path / "second-runner"
    git(tmp_path, "clone", "--branch", "main", str(remote), str(fresh))
    second_output = tmp_path / "second-output"
    second_output.mkdir()
    second = snapshot(day=12, count=90)
    (second_output / "flights.json").write_text(json.dumps(second))
    monkeypatch.setenv("GITHUB_RUN_ID", "101")
    preserve_history(fresh, second_output)
    index = json.loads((second_output / "history/index.json").read_text())
    assert [row["count"] for row in index["scans"]] == [90, 65]
    assert json.loads(gzip.decompress((second_output / "history" / first_file).read_bytes())) == first

    # No new snapshot (for example a timeout): restore the last result and all history.
    recovered_output = tmp_path / "failed-output"
    preserve_history(fresh, recovered_output)
    recovered = json.loads((recovered_output / "flights.json").read_text())
    assert recovered["status"] == "stale"
    assert recovered["generated_at"] == second["generated_at"]
    assert recovered["flights"] == second["flights"]
    assert len(json.loads((recovered_output / "history/index.json").read_text())["scans"]) == 2
    assert git(remote, "rev-parse", "refs/heads/main") == source_head
    assert set(git(remote, "ls-tree", "--name-only", "flight-data").splitlines()) == {"index.json", "latest.json.gz", "scans"}


def test_previous_compressed_snapshot_is_validated(tmp_path):
    path = tmp_path / "latest.json.gz"
    data = snapshot()
    path.write_bytes(gzip.compress(json.dumps(data).encode()))
    assert load_previous(str(path)) == data
    path.write_bytes(b"broken gzip")
    assert load_previous(str(path)) is None
    path.write_bytes(gzip.compress(json.dumps(data).encode())[:12])
    assert load_previous(str(path)) is None
