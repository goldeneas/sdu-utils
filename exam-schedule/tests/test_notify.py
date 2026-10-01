"""Tests for notification channels and payload construction (no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sdu_exam_watch import notify  # noqa: E402
from sdu_exam_watch.config import NotifyConfig  # noqa: E402


class FakeFetcher:
    """Records POST calls instead of talking to the network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, dict | None]] = []

    def post_json(self, url, payload, *, extra_headers=None):  # noqa: ANN001, ANN201
        self.calls.append((url, payload, extra_headers))
        return None


class PriorityTests(unittest.TestCase):
    def test_named_and_numeric_priorities(self) -> None:
        self.assertEqual(
            notify.Notification("t", "m", priority="max").priority_rank(), 5
        )
        self.assertEqual(
            notify.Notification("t", "m", priority="min").priority_rank(), 1
        )
        self.assertEqual(notify.Notification("t", "m", priority="3").priority_rank(), 3)
        self.assertEqual(
            notify.Notification("t", "m", priority="bogus").priority_rank(), 3
        )


class NtfyTests(unittest.TestCase):
    def test_publishes_to_server_root(self) -> None:
        fetcher = FakeFetcher()
        channel = notify.NtfyNotifier("https://ntfy.sh", "my-topic", fetcher=fetcher)
        channel.send(
            notify.Notification(
                title="Hi",
                message="Body",
                priority="high",
                tags=("calendar",),
                click="https://example.org",
            )
        )
        url, payload, headers = fetcher.calls[0]
        self.assertEqual(url, "https://ntfy.sh/")
        self.assertEqual(payload["topic"], "my-topic")
        self.assertEqual(payload["priority"], 4)
        self.assertEqual(payload["click"], "https://example.org")
        self.assertEqual(payload["tags"], ["calendar"])
        # ntfy rejects a string here with HTTP 400; it must be a JSON boolean.
        self.assertIs(payload["markdown"], True)
        self.assertIsNone(headers)

    def test_token_adds_authorization(self) -> None:
        fetcher = FakeFetcher()
        notify.NtfyNotifier(
            "https://ntfy.sh",
            "t",
            token="tk_123",  # noqa: S106 - intentional dummy credential in a test
            fetcher=fetcher,
        ).send(notify.Notification("a", "b"))
        _, _, headers = fetcher.calls[0]
        self.assertEqual(headers, {"Authorization": "Bearer tk_123"})

    def test_attaches_file_when_present(self) -> None:
        fetcher = FakeFetcher()
        notify.NtfyNotifier("https://ntfy.sh", "t", fetcher=fetcher).send(
            notify.Notification(
                title="a",
                message="b",
                attach="https://example.org/plan.pdf",
                attachment_name="SDU exam plan.pdf",
            )
        )
        _, payload, _ = fetcher.calls[0]
        self.assertEqual(payload["attach"], "https://example.org/plan.pdf")
        self.assertEqual(payload["filename"], "SDU exam plan.pdf")

    def test_no_attach_field_when_absent(self) -> None:
        fetcher = FakeFetcher()
        notify.NtfyNotifier("https://ntfy.sh", "t", fetcher=fetcher).send(
            notify.Notification("a", "b")
        )
        _, payload, _ = fetcher.calls[0]
        self.assertNotIn("attach", payload)


class BuildNotifiersTests(unittest.TestCase):
    def test_only_enabled_channels(self) -> None:
        channels = notify.build_notifiers(NotifyConfig(ntfy_topic="t"))
        self.assertEqual([c.name for c in channels], ["ntfy"])

    def test_all_channels(self) -> None:
        channels = notify.build_notifiers(
            NotifyConfig(
                ntfy_topic="t",
                webhook_url="https://hook",
                macos_notification=True,
                stdout=True,
            )
        )
        self.assertEqual(
            sorted(c.name for c in channels), ["macos", "ntfy", "stdout", "webhook"]
        )

    def test_send_all_collects_errors_without_raising(self) -> None:
        class Broken:
            name = "broken"

            def send(self, note):  # noqa: ANN001, ANN201
                raise notify.NotifyError("nope")

        errors = notify.send_all([Broken()], notify.Notification("a", "b"))
        self.assertEqual(errors, ["broken: nope"])


if __name__ == "__main__":
    unittest.main()
