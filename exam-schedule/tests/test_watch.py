"""Tests for link extraction, fingerprint diffing and summary formatting."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sdu_exam_watch import watch  # noqa: E402
from sdu_exam_watch.config import Target  # noqa: E402
from sdu_exam_watch.xlsx import ExamEntry, Schedule  # noqa: E402

PAGE = """
<html><body>
  <a href="/media/plan.pdf">PDF</a>
  <a href='/media/plan.xlsx'>Excel</a>
  <a href="/media/plan.xlsx#download">dup</a>
  <a href="https://other.example/thing.pdf?x=1">abs</a>
  <a href="mailto:someone@sdu.dk">mail</a>
  <a href="/media/notes.txt">not a schedule</a>
</body></html>
"""


class ExtractUrlTests(unittest.TestCase):
    def test_extracts_only_matching_absolute_urls(self) -> None:
        urls = watch.extract_artifact_urls(
            PAGE, "https://mitsdu.dk/page", r"\.(xlsx|xls|pdf)([?#]|$)"
        )
        self.assertEqual(
            urls,
            [
                "https://mitsdu.dk/media/plan.pdf",
                "https://mitsdu.dk/media/plan.xlsx",
                "https://other.example/thing.pdf?x=1",
            ],
        )

    def test_ignores_unknown_schemes_and_non_matches(self) -> None:
        urls = watch.extract_artifact_urls(PAGE, "https://mitsdu.dk/", r"\.txt$")
        self.assertEqual(urls, ["https://mitsdu.dk/media/notes.txt"])


class DiffTests(unittest.TestCase):
    def test_added_removed_changed(self) -> None:
        previous = {
            "https://x/a.pdf": {"etag": "1", "content_length": 10},
            "https://x/b.xlsx": {"etag": "2", "content_length": 20},
            "https://x/gone.pdf": {"etag": "3"},
        }
        current = {
            "https://x/a.pdf": watch.Artifact("https://x/a.pdf", etag="1", content_length=10),
            "https://x/b.xlsx": watch.Artifact("https://x/b.xlsx", etag="9", content_length=21),
            "https://x/new.pdf": watch.Artifact("https://x/new.pdf", etag="4"),
        }
        added, removed, changed = watch.diff_artifacts(previous, current)
        self.assertEqual(added, ["https://x/new.pdf"])
        self.assertEqual(removed, ["https://x/gone.pdf"])
        self.assertEqual(changed, ["https://x/b.xlsx"])

    def test_no_change(self) -> None:
        previous = {"https://x/a.pdf": {"etag": "1"}}
        current = {"https://x/a.pdf": watch.Artifact("https://x/a.pdf", etag="1")}
        self.assertEqual(watch.diff_artifacts(previous, current), ([], [], []))

    def test_artifact_roundtrip(self) -> None:
        artifact = watch.Artifact(
            "https://x/a.pdf", etag="e", last_modified="lm", content_length=5, sha256="h"
        )
        restored = watch.Artifact.from_dict("https://x/a.pdf", artifact.to_dict())
        self.assertEqual(restored.fingerprint(), artifact.fingerprint())

    def test_fingerprint_changes_with_etag(self) -> None:
        a = watch.Artifact("https://x/a.pdf", etag="1")
        b = watch.Artifact("https://x/a.pdf", etag="2")
        self.assertNotEqual(a.fingerprint(), b.fingerprint())


class SummaryTests(unittest.TestCase):
    def test_formats_dates_and_limits(self) -> None:
        schedule = Schedule(
            title="S26",
            exams=[
                ExamEntry(title="Alpha", date="20-05-2026"),
                ExamEntry(title="Beta", date="2026-06-01"),
                ExamEntry(title="Gamma", date=""),
            ],
        )
        text = watch.format_summary(schedule, limit=2)
        self.assertIn("2026-05-20 — Alpha", text)
        self.assertIn("2026-06-01 — Beta", text)
        self.assertIn("…and 1 more", text)
        self.assertNotIn("Gamma", text)

    def test_normalises_date_ranges(self) -> None:
        schedule = Schedule(
            title="S26",
            exams=[ExamEntry(title="Thesis", date="08-06-2026 - 26-06-2026")],
        )
        text = watch.format_summary(schedule, limit=5)
        self.assertIn("2026-06-08 → 2026-06-26 — Thesis", text)

    def test_spreadsheet_detection(self) -> None:
        self.assertTrue(watch.Artifact("https://x/a.xlsx").is_spreadsheet())
        self.assertTrue(watch.Artifact("https://x/a.XLS").is_spreadsheet())
        self.assertFalse(watch.Artifact("https://x/a.pdf").is_spreadsheet())


class TargetValidationTests(unittest.TestCase):
    def test_rejects_non_http(self) -> None:
        from sdu_exam_watch.config import ConfigError

        with self.assertRaises(ConfigError):
            Target(name="x", url="file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
