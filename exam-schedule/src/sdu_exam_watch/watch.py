"""The core watch logic: discover artifacts, fingerprint them and diff.

A *target* is a web page (the SDU programme exam-schedule page). Each check:

1. fetches the page and extracts the schedule links matching the target's
   ``link_pattern`` (normally the PDF and XLSX downloads),
2. fingerprints every linked file using its ``ETag``/``Last-Modified``/
   ``Content-Length`` headers, downloading and hashing it only when the server
   exposes no validators or ``hash_files`` is enabled,
3. diffs the fingerprints against the previous run.

Everything is written to be side-effect free so it can be unit tested without
touching the network.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from . import xlsx
from .config import Settings, Target
from .http import FetchError

log = logging.getLogger(__name__)

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm", ".xls")
_IGNORED_SCHEMES = ("mailto:", "javascript:", "tel:", "data:")


class HttpResponse(Protocol):
    """The response surface the watcher relies on (see :class:`http.Response`)."""

    body: bytes
    url: str

    def header(self, name: str, default: str | None = None) -> str | None:
        """Case-insensitive header lookup."""


class HttpGetter(Protocol):
    """Anything that can GET a URL (satisfied by :class:`http.Fetcher`)."""

    def get(
        self, url: str, *, extra_headers: dict[str, str] | None = None
    ) -> HttpResponse:
        """Fetch ``url`` and return its response."""
        ...


class HttpFetcher(HttpGetter, Protocol):
    """A getter that can also issue HEAD requests."""

    def head(self, url: str) -> HttpResponse | None:
        """Fetch headers, or ``None`` when HEAD is unsupported."""


@dataclass(slots=True)
class Artifact:
    """A single downloadable file discovered on a target page."""

    url: str
    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None
    sha256: str | None = None

    def fingerprint(self) -> str:
        """A stable string that changes whenever the file changes."""
        return "|".join(
            (
                self.etag or "",
                self.last_modified or "",
                "" if self.content_length is None else str(self.content_length),
                self.sha256 or "",
            )
        )

    def is_spreadsheet(self) -> bool:
        path = urlsplit(self.url).path.lower()
        return path.endswith(_SPREADSHEET_SUFFIXES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_length": self.content_length,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, url: str, data: dict[str, Any]) -> Artifact:
        length = data.get("content_length")
        if isinstance(length, int):
            content_length: int | None = length
        else:
            content_length = _safe_int(length if isinstance(length, str) else None)
        return cls(
            url=url,
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            content_length=content_length,
            sha256=data.get("sha256"),
        )


@dataclass(slots=True)
class CheckResult:
    """Outcome of checking one target."""

    target: Target
    page_url: str
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    bodies: dict[str, bytes] = field(default_factory=dict)
    baseline: bool = False
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def extract_artifact_urls(page: str, base_url: str, pattern: str) -> list[str]:
    """Return absolute, de-duplicated links on ``page`` matching ``pattern``."""
    regex = re.compile(pattern, re.IGNORECASE)
    seen: set[str] = set()
    urls: list[str] = []
    for raw in _HREF_RE.findall(page):
        candidate = html.unescape(raw).strip()
        if not candidate or candidate.lower().startswith(_IGNORED_SCHEMES):
            continue
        absolute = urljoin(base_url, candidate)
        if not absolute.lower().startswith(("http://", "https://")):
            continue
        # Compare without the fragment so ``#download`` variants collapse.
        key = absolute.split("#", 1)[0]
        if not regex.search(key) or key in seen:
            continue
        seen.add(key)
        urls.append(key)
    return urls


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def fetch_artifact(
    fetcher: HttpFetcher, url: str, settings: Settings
) -> tuple[Artifact, bytes | None]:
    """Fingerprint ``url``.

    Uses a cheap HEAD request when the server exposes validators; otherwise
    (or when hashing is requested) downloads the file and hashes it.
    """
    head = fetcher.head(url)
    if head is not None and not settings.hash_files:
        # Cheap path: the server gave us at least one validator to compare on.
        validators = [
            head.header(name) for name in ("etag", "last-modified", "content-length")
        ]
        if any(validators):
            return (
                Artifact(
                    url=url,
                    etag=head.header("etag"),
                    last_modified=head.header("last-modified"),
                    content_length=_safe_int(head.header("content-length")),
                ),
                None,
            )

    response = fetcher.get(url)
    body = response.body
    return (
        Artifact(
            url=url,
            etag=response.header("etag"),
            last_modified=response.header("last-modified"),
            content_length=len(body) or _safe_int(response.header("content-length")),
            sha256=hashlib.sha256(body).hexdigest(),
        ),
        body,
    )


def check_target(
    target: Target,
    settings: Settings,
    fetcher: HttpFetcher,
    previous: dict[str, dict[str, Any]] | None = None,
) -> CheckResult:
    """Check one target and diff it against ``previous`` fingerprints."""
    previous = previous or {}
    page = fetcher.get(target.url)
    page_html = page.body.decode("utf-8", errors="replace")
    urls = extract_artifact_urls(page_html, page.url, target.link_pattern)

    result = CheckResult(target=target, page_url=page.url, baseline=not previous)
    for url in urls:
        try:
            artifact, body = fetch_artifact(fetcher, url, settings)
        except FetchError as exc:
            log.warning("could not fingerprint %s: %s", url, exc)
            result.errors.append(f"{url}: {exc}")
            continue
        result.artifacts[url] = artifact
        if body is not None:
            result.bodies[url] = body

    result.added, result.removed, result.changed = diff_artifacts(
        previous, result.artifacts
    )
    return result


def diff_artifacts(
    previous: dict[str, dict[str, Any]], current: dict[str, Artifact]
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(added, removed, changed)`` URL lists."""
    previous_urls = set(previous)
    current_urls = set(current)
    added = sorted(current_urls - previous_urls)
    removed = sorted(previous_urls - current_urls)
    changed = sorted(
        url
        for url in current_urls & previous_urls
        if Artifact.from_dict(url, previous[url]).fingerprint()
        != current[url].fingerprint()
    )
    return added, removed, changed


# ---------------------------------------------------------------------------
# Schedule summaries
# ---------------------------------------------------------------------------


def load_summary(
    fetcher: HttpGetter, result: CheckResult, settings: Settings
) -> xlsx.Schedule | None:
    """Download and parse the changed spreadsheet, filtered to the programme.

    Returns ``None`` (never raises) when there is nothing to summarise or the
    workbook cannot be read, so a summary failure can never suppress the
    underlying "schedule changed" notification.
    """
    if not result.target.summary:
        return None
    candidates = [
        url
        for url in (*result.added, *result.changed)
        if result.artifacts.get(url, Artifact(url)).is_spreadsheet()
    ]
    if not candidates:
        # No change to point at (e.g. ``--force-notify``): fall back to every
        # spreadsheet currently published so the notification still shows exams.
        candidates = [
            url for url, artifact in result.artifacts.items() if artifact.is_spreadsheet()
        ]
    for url in candidates:
        body = result.bodies.get(url)
        try:
            if body is None:
                body = fetcher.get(url).body
            schedule = xlsx.read_schedule(body, result.target.programmes)
        except (FetchError, xlsx.XlsxError) as exc:
            log.warning("could not summarise %s: %s", url, exc)
            continue
        if schedule.title or schedule.exams:
            return schedule
    return None


def format_summary(schedule: xlsx.Schedule, limit: int) -> str:
    """Render up to ``limit`` exams as a bullet list."""
    lines: list[str] = []
    for entry in schedule.exams[:limit]:
        when = _pretty_date(entry.date) or "date TBA"
        what = entry.title or entry.code or "exam"
        lines.append(f"• {when} — {what}")
    remaining = len(schedule.exams) - limit
    if remaining > 0:
        lines.append(f"…and {remaining} more")
    return "\n".join(lines)


def _pretty_date(value: str) -> str:
    """Normalise published date text to ISO.

    Single dates (``20-05-2026``) and ranges (``08-06-2026 - 26-06-2026``) are
    converted to ``YYYY-MM-DD`` (ranges joined with ``→``). Anything that does
    not look like a Danish date is echoed unchanged.
    """
    text = (value or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in text.split(" - ")]
    converted = [_iso_date(part) for part in parts]
    if any(item is None for item in converted):
        return text
    return " → ".join(item for item in converted if item is not None)


def _iso_date(text: str) -> str | None:
    """Convert ``dd-mm-yyyy`` to ``yyyy-mm-dd``, or ``None`` if not a date."""
    match = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", text)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
