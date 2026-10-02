"""Notification channels.

The primary channel is `ntfy <https://ntfy.sh>`_: no account, no server, and
on iPhone no developer certificate. Install the free *ntfy* app, subscribe to
a (hard-to-guess) topic name, and this module publishes a plain JSON POST that
lands on the phone.

A stdout channel is also provided so the watcher can be dry-run in a terminal
or wired into cron mail.

Only the standard library is used; the HTTPS POST is done directly so the
project keeps its zero-dependency promise.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .config import NotifyConfig

_PRIORITY_RANK = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5}
_RETRIES = 2
_TIMEOUT = 20


class NotifyError(RuntimeError):
    """Raised when a notification could not be delivered."""


@dataclass(slots=True)
class Notification:
    """A message to deliver on every configured channel."""

    title: str
    message: str
    priority: str = "default"
    tags: tuple[str, ...] = field(default_factory=tuple)
    click: str = ""
    markdown: bool = True

    def priority_rank(self) -> int:
        value = str(self.priority).strip().lower()
        if value in _PRIORITY_RANK:
            return _PRIORITY_RANK[value]
        try:
            rank = int(value)
        except ValueError:
            return 3
        return rank if 1 <= rank <= 5 else 3


class Notifier(Protocol):
    """Anything that can deliver a :class:`Notification`."""

    name: str

    def send(self, note: Notification) -> None:
        """Deliver ``note`` to this channel."""


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> None:
    """POST ``payload`` as JSON, retrying transient network errors."""
    _require_safe_url(url)
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    last_err: Exception | None = None
    for attempt in range(_RETRIES + 1):
        req = urllib.request.Request(
            url, data=body, headers=request_headers, method="POST"
        )  # noqa: S310  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
                resp.read()
            return
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last_err = err
            time.sleep(0.8 * (attempt + 1))
    raise NotifyError(f"POST {url} failed: {last_err}")


def _require_safe_url(url: str) -> None:
    """Only HTTPS (or HTTP on loopback for self-hosted ntfy) is permitted."""
    lowered = url.lower()
    if lowered.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        return
    raise NotifyError(f"refusing to POST to a non-HTTPS URL: {url!r}")


class NtfyNotifier:
    """Publish to an ntfy topic (ntfy.sh or self-hosted)."""

    name = "ntfy"

    def __init__(self, server: str, topic: str, token: str = "") -> None:
        self.server = server.rstrip("/")
        self.topic = topic
        self.token = token

    def send(self, note: Notification) -> None:
        payload: dict[str, object] = {
            "topic": self.topic,
            "title": note.title,
            "message": note.message,
            "priority": note.priority_rank(),
            "markdown": note.markdown,
        }
        if note.tags:
            payload["tags"] = list(note.tags)
        if note.click:
            payload["click"] = note.click
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        _post_json(f"{self.server}/", payload, headers)


class StdoutNotifier:
    """Print notifications to stdout (dry runs, cron mail, tests)."""

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
    if config.stdout:
        notifiers.append(StdoutNotifier())
    return notifiers


def send_all(notifiers: list[Notifier], note: Notification) -> list[str]:
    """Deliver ``note`` on every channel; return a list of error strings."""
    errors: list[str] = []
    for notifier in notifiers:
        try:
            notifier.send(note)
        except NotifyError as err:
            errors.append(f"{notifier.name}: {err}")
    return errors
