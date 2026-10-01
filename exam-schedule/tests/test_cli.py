"""Tests for the check orchestration: when to notify and what to persist.

These cover the bugs that matter operationally:

* the very first check must be a silent *baseline* (not a burst of alerts),
* a change must produce a notification whose text names the change,
* a summary failure must never lose the previously cached exams.

The workbook parser is exercised in ``test_xlsx``; here it is mocked so these
tests stay focused on orchestration.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sdu_exam_watch import cli, watch, xlsx  # noqa: E402
from sdu_exam_watch.config import (  # noqa: E402
    Config,
    NotifyConfig,
    Settings,
    Target,
)
from sdu_exam_watch.xlsx import ExamEntry, Schedule  # noqa: E402

SWE = "Kandidat i Software Engineering (MSc)"
XLSX_URL = "https://example.org/eksamensplan.xlsx"


def _settings(**overrides) -> Settings:
    state_file = Path(tempfile.gettempdir()) / "sdu-exam-watch-test-state.json"
    base = Settings(state_file=state_file)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _target(**overrides) -> Target:
    base = {"name": "t", "url": "https://example.org/page", "programmes": (SWE,)}
    base.update(overrides)
    return Target(**base)


class FakeResponse:
    """Structural stand-in for :class:`sdu_exam_watch.http.Response`."""

    def __init__(self, body: bytes, url: str) -> None:
        self.body = body
        self.url = url

    def header(self, name: str, default: str | None = None) -> str | None:
        return default


class FakeFetcher:
    """Returns a canned body for any GET; records the URLs requested."""

    def __init__(self, body: bytes = b"") -> None:
        self.body = body
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(url)
        return FakeResponse(self.body, url)

    def head(self, url: str):  # noqa: ANN201
        return None


class ShouldNotifyTests(unittest.TestCase):
    def test_first_run_is_silent_by_default(self) -> None:
        result = watch.CheckResult(
            target=_target(), page_url="u", baseline=True, added=[XLSX_URL]
        )
        self.assertFalse(cli._should_notify(result, _settings(), False))

    def test_first_run_can_opt_in(self) -> None:
        result = watch.CheckResult(
            target=_target(), page_url="u", baseline=True, added=[XLSX_URL]
        )
        self.assertTrue(
            cli._should_notify(result, _settings(notify_on_first_run=True), False)
        )

    def test_change_notifies(self) -> None:
        result = watch.CheckResult(
            target=_target(), page_url="u", baseline=False, added=[XLSX_URL]
        )
        self.assertTrue(cli._should_notify(result, _settings(), False))

    def test_no_change_is_silent(self) -> None:
        result = watch.CheckResult(target=_target(), page_url="u", baseline=False)
        self.assertFalse(cli._should_notify(result, _settings(), False))

    def test_force_notify_overrides(self) -> None:
        result = watch.CheckResult(target=_target(), page_url="u", baseline=False)
        self.assertTrue(cli._should_notify(result, _settings(), True))


class LoadSummaryTests(unittest.TestCase):
    def _result(self, target: Target, *, added: bool = True) -> watch.CheckResult:
        return watch.CheckResult(
            target=target,
            page_url="u",
            added=[XLSX_URL] if added else [],
            artifacts={XLSX_URL: watch.Artifact(XLSX_URL)},
        )

    @mock.patch.object(xlsx, "read_schedule")
    def test_summarises_changed_spreadsheet(self, read_schedule) -> None:  # noqa: ANN001
        read_schedule.return_value = Schedule(
            title="S26", exams=[ExamEntry(code="EKA1", title="Course")]
        )
        result = self._result(_target())
        schedule = watch.load_summary(FakeFetcher(b"bytes"), result, _settings())
        self.assertIsNotNone(schedule)
        assert schedule is not None
        self.assertEqual(schedule.exams[0].code, "EKA1")
        # The parser must be asked for the target's programme filter.
        self.assertEqual(read_schedule.call_args.args[1], (SWE,))

    @mock.patch.object(xlsx, "read_schedule")
    def test_falls_back_to_published_file_when_nothing_changed(
        self, read_schedule
    ) -> None:  # noqa: ANN001
        read_schedule.return_value = Schedule(title="S26", exams=[ExamEntry(code="X")])
        # No added/changed file, as with --force-notify.
        result = self._result(_target(), added=False)
        fetcher = FakeFetcher(b"bytes")
        schedule = watch.load_summary(fetcher, result, _settings())
        self.assertIsNotNone(schedule)
        self.assertEqual(fetcher.calls, [XLSX_URL])

    def test_disabled_by_target_returns_none(self) -> None:
        result = self._result(_target(summary=False))
        self.assertIsNone(watch.load_summary(FakeFetcher(), result, _settings()))


class BuildNotificationTests(unittest.TestCase):
    def _config(self) -> Config:
        return Config(
            settings=_settings(),
            notify=NotifyConfig(ntfy_topic="t"),
            targets=[_target()],
        )

    def test_new_schedule_title_and_click(self) -> None:
        result = watch.CheckResult(
            target=_target(), page_url="https://page", added=[XLSX_URL]
        )
        note = cli._build_notification(result, None, self._config(), False)
        self.assertIn("New", note.title)
        self.assertEqual(note.click, "https://page")
        self.assertIn(XLSX_URL, note.message)

    def test_changed_schedule_title(self) -> None:
        result = watch.CheckResult(target=_target(), page_url="u", changed=[XLSX_URL])
        note = cli._build_notification(result, None, self._config(), False)
        self.assertIn("updated", note.title)

    def test_lists_exams_when_summary_present(self) -> None:
        schedule = Schedule(
            title="S26",
            exams=[ExamEntry(title="Introduktion til OOP", date="20-05-2026")],
        )
        result = watch.CheckResult(target=_target(), page_url="u", added=[XLSX_URL])
        note = cli._build_notification(result, schedule, self._config(), False)
        self.assertIn("Introduktion til OOP", note.message)
        self.assertIn("2026-05-20", note.message)

    def test_attaches_pdf_in_preference_to_spreadsheet(self) -> None:
        result = watch.CheckResult(
            target=_target(),
            page_url="u",
            added=[XLSX_URL],
            changed=["https://example.org/plan.pdf"],
        )
        note = cli._build_notification(result, None, self._config(), False)
        self.assertEqual(note.attach, "https://example.org/plan.pdf")

    def test_attachment_can_be_disabled(self) -> None:
        config = self._config()
        config.notify.attach_files = False
        result = watch.CheckResult(target=_target(), page_url="u", added=[XLSX_URL])
        note = cli._build_notification(result, None, config, False)
        self.assertEqual(note.attach, "")

    def test_attachment_name_derived_from_schedule_title(self) -> None:
        schedule = Schedule(title="Exam schedule Summer 2026 - Odense")
        result = watch.CheckResult(target=_target(), page_url="u", added=[XLSX_URL])
        note = cli._build_notification(result, schedule, self._config(), False)
        self.assertEqual(
            note.attachment_name, "Exam schedule Summer 2026 - Odense.xlsx"
        )


class PersistTests(unittest.TestCase):
    def test_keeps_previous_exams_without_new_schedule(self) -> None:
        state: dict = {}
        result = watch.CheckResult(
            target=_target(),
            page_url="u",
            artifacts={XLSX_URL: watch.Artifact(XLSX_URL)},
        )
        previous = {"exams": [{"code": "OLD"}], "schedule_title": "Old"}
        cli._persist_target(state, result, None, previous)
        entry = state["targets"]["t"]
        self.assertEqual(entry["exams"], [{"code": "OLD"}])
        self.assertEqual(entry["schedule_title"], "Old")
        self.assertIn(XLSX_URL, entry["artifacts"])
        self.assertTrue(entry["last_checked"])

    def test_replaces_exams_with_new_schedule(self) -> None:
        state: dict = {}
        result = watch.CheckResult(target=_target(), page_url="u")
        schedule = Schedule(exams=[ExamEntry(code="T510063102")])
        cli._persist_target(state, result, schedule, {})
        entry = state["targets"]["t"]
        self.assertEqual(len(entry["exams"]), 1)
        self.assertEqual(entry["exams"][0]["code"], "T510063102")


if __name__ == "__main__":
    unittest.main()
