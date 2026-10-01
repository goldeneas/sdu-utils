"""Notification channels.

The recommended channel is `ntfy <https://ntfy.sh>`_: it needs no account, no
server and — crucially for iPhone users — no self-signed developer
certificate. You install the free *ntfy* app from the App Store and subscribe
to a topic name; publishing is a plain HTTP POST.

Two extra channels are available for flexibility: a generic JSON webhook
(works with Discord/Slack/custom endpoints) and a local macOS banner via
``osascript``.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from .config import NotifyConfig
from .http import Fetcher, FetchError

log = logging.getLogger(__name__)

_PRIORITY_RANK = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5}


class NotifyError(RuntimeError):
    """Raised by a channel when a notification could not be delivered."""


@dataclass(slots=True)
class Notification:
    """A message to deliver on every configured channel."""

    title: str
    message: str
    priority: str = "default"
    tags: tuple[str, ...] = field(default_factory=tuple)
    click: str = ""
    # Optional file to attach (a URL the ntfy server fetches and delivers).
    attach: str = ""
    attachment_name: str = ""

    def priority_rank(self) -> int:
        """Return the ntfy numeric priority (1-5)."""
        value = str(self.priority).strip().lower()
        if value in _PRIORITY_RANK:
            return _PRIORITY_RANK[value]
        try:
            rank = int(value)
        except ValueError:
            return 3
        return rank if 1 <= rank <= 5 else 3


class JsonPoster(Protocol):
    """Minimal interface for posting JSON (implemented by :class:`Fetcher`)."""

    def post_json(
        self,
        url: str,
        payload: dict,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> object:
        """POST ``payload`` as JSON to ``url``."""


class Notifier(Protocol):
    """Anything that can deliver a :class:`Notification`."""

    name: str

    def send(self, note: Notification) -> None:
        """Deliver ``note`` to this channel."""


class NtfyNotifier:
    """Publish to an ntfy topic (ntfy.sh or self-hosted)."""

    name = "ntfy"

    def __init__(
        self,
        server: str,
        topic: str,
        token: str = "",
        fetcher: JsonPoster | None = None,
    ) -> None:
        self.server = server.rstrip("/")
        self.topic = topic
        self.token = token
        self.fetcher = fetcher or Fetcher(retries=1)

    def send(self, note: Notification) -> None:
        payload: dict[str, object] = {
            "topic": self.topic,
            "title": note.title,
            "message": note.message,
            "priority": note.priority_rank(),
            # ntfy's JSON API expects a boolean here; a string such as "yes"
            # is rejected with HTTP 400 "request body must be valid JSON".
            "markdown": True,
        }
        if note.tags:
            payload["tags"] = list(note.tags)
        if note.click:
            payload["click"] = note.click
        if note.attach:
            # ntfy fetches this URL server-side and delivers the file itself,
            # so the real PDF/Excel lands on the phone, not just a link.
            payload["attach"] = note.attach
            if note.attachment_name:
                payload["filename"] = note.attachment_name
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        try:
            self.fetcher.post_json(f"{self.server}/", payload, extra_headers=headers)
        except FetchError as exc:
            raise NotifyError(f"ntfy publish failed: {exc}") from exc


class WebhookNotifier:
    """POST a small JSON document to a webhook URL.

    The payload carries several common keys (``content`` for Discord, ``text``
    for Slack, plus ``title``/``message``) so the same channel works in many
    places without per-service templating.
    """

    name = "webhook"

    def __init__(self, url: str, fetcher: JsonPoster | None = None) -> None:
        self.url = url
        self.fetcher = fetcher or Fetcher(retries=1)

    def send(self, note: Notification) -> None:
        payload = {
            "title": note.title,
            "message": note.message,
            "text": f"{note.title}\n\n{note.message}",
            "content": f"**{note.title}**\n\n{note.message}",
            "url": note.click,
        }
        try:
            self.fetcher.post_json(self.url, payload)
        except FetchError as exc:
            raise NotifyError(f"webhook post failed: {exc}") from exc


class MacOSNotifier:
    """Show a local Notification Centre banner with ``osascript``."""

    name = "macos"
    _SCRIPT = (
        "on run argv\n"
        "  display notification (item 2 of argv) with title (item 1 of argv)\n"
        "end run"
    )

    def send(self, note: Notification) -> None:
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["osascript", "-e", self._SCRIPT, note.title, note.message],
                check=True,
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NotifyError(f"osascript notification failed: {exc}") from exc


class StdoutNotifier:
    """Print notifications to stdout (useful for testing and cron mail)."""

    name = "stdout"

    def send(self, note: Notification) -> None:
        print(f"[{note.title}] {note.message}")


def build_notifiers(config: NotifyConfig) -> list[Notifier]:
    """Instantiate every channel enabled in the configuration."""
    notifiers: list[Notifier] = []
    if config.ntfy_topic:
        notifiers.append(
            NtfyNotifier(config.ntfy_server, config.ntfy_topic, config.ntfy_token)
        )
    if config.webhook_url:
        notifiers.append(WebhookNotifier(config.webhook_url))
    if config.macos_notification:
        notifiers.append(MacOSNotifier())
    if config.stdout:
        notifiers.append(StdoutNotifier())
    return notifiers


def send_all(notifiers: list[Notifier], note: Notification) -> list[str]:
    """Deliver ``note`` on every channel; return a list of error strings.

    A failing channel never prevents the others from being tried, and never
    aborts the check.
    """
    errors: list[str] = []
    for notifier in notifiers:
        try:
            notifier.send(note)
            log.info("notification delivered via %s", notifier.name)
        except NotifyError as exc:
            log.error("notification via %s failed: %s", notifier.name, exc)
            errors.append(f"{notifier.name}: {exc}")
    return errors
