"""A tiny, dependency-free HTTP client with retries and explicit redirects.

Built on :mod:`http.client` rather than ``urllib.request`` on purpose:

* only ``http``/``https`` URLs are ever opened (no ``file:`` handler can leak
  local files through a mistyped config value),
* redirects are followed with a bounded, well-defined policy,
* HEAD and GET share one code path, and
* the response size is capped so a bad URL cannot exhaust memory.
"""

from __future__ import annotations

import gzip
import http.client
import json
import logging
import ssl
import time
import urllib.parse
import zlib
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "sdu-exam-watch/1.0 (polite exam-schedule watcher)"

# Status codes worth retrying: transient server / rate-limit problems.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# Status codes that ask the client to look somewhere else.
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 10


class FetchError(RuntimeError):
    """Raised when a request cannot be completed after all retries."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class Response:
    """The subset of an HTTP response the watcher cares about."""

    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str, default: str | None = None) -> str | None:
        """Case-insensitive header lookup."""
        return self.headers.get(name.lower(), default)


def _error_detail(body: bytes, limit: int = 300) -> str:
    """Return a short, printable snippet of an error response body.

    Servers such as ntfy explain *why* a request failed in the body (for
    example an invalid field). Including it turns an opaque ``HTTP 400`` into
    something actionable, e.g.
    ``HTTP 400 for https://ntfy.sh/: request body must be valid JSON``.
    """
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit] + "…"
    return f": {text}"


class Fetcher:
    """Small HTTP client wrapper with retry, backoff and redirect handling.

    Parameters
    ----------
    timeout:
        Per-request socket timeout in seconds.
    user_agent:
        ``User-Agent`` header. Being explicit keeps us polite and traceable.
    retries:
        Number of *additional* attempts after the first one fails.
    backoff:
        Base delay between retries; attempt ``n`` waits ``backoff * 2**n``.
    max_bytes:
        Hard cap on a downloaded body.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
        retries: int = 3,
        backoff: float = 2.0,
        max_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.retries = max(0, retries)
        self.backoff = backoff
        self.max_bytes = max_bytes
        self._ssl_context = ssl.create_default_context()

    # -- public API ---------------------------------------------------------

    def get(self, url: str, *, extra_headers: dict[str, str] | None = None) -> Response:
        """Fetch ``url`` with GET, returning status, headers and body."""
        return self._request("GET", url, extra_headers)

    def post_json(
        self,
        url: str,
        payload: dict,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> Response:
        """POST ``payload`` as a JSON body (used for notifications)."""
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        body = json.dumps(payload).encode("utf-8")
        return self._request("POST", url, headers, body=body)

    def head(self, url: str) -> Response | None:
        """Fetch headers with HEAD.

        Returns ``None`` when the server does not support HEAD (405/501) so the
        caller can fall back to a GET.
        """
        try:
            return self._request("HEAD", url, None)
        except FetchError as exc:
            if exc.status in (405, 501):
                log.debug("HEAD not supported for %s (%s)", url, exc)
                return None
            raise

    # -- internals ----------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        extra_headers: dict[str, str] | None,
        body: bytes | None = None,
    ) -> Response:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Connection": "close",
        }
        if extra_headers:
            headers.update(extra_headers)

        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._with_redirects(method, url, headers, body)
            except FetchError as exc:
                last_exc = exc
                if exc.status not in RETRY_STATUS or attempt == self.retries:
                    raise
                log.warning(
                    "HTTP %s for %s (attempt %d/%d), retrying",
                    exc.status,
                    url,
                    attempt + 1,
                    self.retries + 1,
                )
            except (OSError, http.client.HTTPException) as exc:
                last_exc = exc
                if attempt == self.retries:
                    raise FetchError(f"{type(exc).__name__} for {url}: {exc}") from exc
                log.warning(
                    "%s for %s (attempt %d/%d), retrying",
                    type(exc).__name__,
                    url,
                    attempt + 1,
                    self.retries + 1,
                )
            time.sleep(self.backoff * (2**attempt))

        raise FetchError(f"unreachable: {last_exc}")  # pragma: no cover

    def _with_redirects(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> Response:
        current_method = method
        current_url = url
        current_body = body
        for _ in range(MAX_REDIRECTS + 1):
            response = self._request_once(
                current_method, current_url, headers, current_body
            )
            if response.status not in REDIRECT_STATUS:
                return response

            location = response.header("location")
            if not location:
                return response

            moved_to = urllib.parse.urljoin(current_url, location)
            log.debug("redirect %s -> %s", current_url, moved_to)
            # 303 always becomes GET; a 301/302 after POST also becomes GET, per
            # long-standing browser behaviour (and RFC 9110).
            if response.status == 303 or current_method == "POST":
                current_method = "GET"
                current_body = None
            current_url = moved_to

        raise FetchError(f"too many redirects starting at {url}")

    def _request_once(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> Response:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise FetchError(f"refusing non-HTTP(S) URL scheme {scheme!r}: {url}")

        host = parsed.hostname
        if not host:
            raise FetchError(f"URL has no host: {url}")
        port = parsed.port or (443 if scheme == "https" else 80)
        # Rebuild an origin-form request target; http.client handles Host.
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))

        if scheme == "https":
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                host, port, timeout=self.timeout, context=self._ssl_context
            )
        else:
            connection = http.client.HTTPConnection(host, port, timeout=self.timeout)

        try:
            connection.request(method, path, body=body, headers=headers)
            raw = connection.getresponse()
            response_headers = {k.lower(): v for k, v in raw.getheaders()}
            body = b"" if method == "HEAD" else self._read_capped(raw, url)
            status = raw.status
        finally:
            connection.close()

        response = Response(url=url, status=status, headers=response_headers, body=body)
        if status in RETRY_STATUS:
            raise FetchError(
                f"HTTP {status} for {url}{_error_detail(body)}", status=status
            )
        if status >= 400:
            raise FetchError(
                f"HTTP {status} for {url}{_error_detail(body)}", status=status
            )
        return response

    def _read_capped(self, raw: http.client.HTTPResponse, url: str) -> bytes:
        body = raw.read(self.max_bytes + 1)
        if len(body) > self.max_bytes:
            raise FetchError(
                f"response body for {url} exceeds {self.max_bytes} bytes; refusing to load"
            )
        encoding = (raw.getheader("Content-Encoding") or "").lower()
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            body = zlib.decompress(body)
        return body
