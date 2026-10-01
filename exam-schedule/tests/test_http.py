"""Tests for the HTTP client's safety and error reporting (no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sdu_exam_watch.http import Fetcher, FetchError, _error_detail  # noqa: E402


class SchemeTests(unittest.TestCase):
    def test_rejects_non_http_schemes(self) -> None:
        fetcher = Fetcher(retries=0)
        for url in ("file:///etc/passwd", "ftp://example.org/x", "data:text/plain,hi"):
            with self.subTest(url=url), self.assertRaises(FetchError):
                fetcher._request_once("GET", url, {})  # noqa: SLF001

    def test_rejects_missing_host(self) -> None:
        with self.assertRaises(FetchError):
            Fetcher(retries=0)._request_once("GET", "https:///nohost", {})  # noqa: SLF001

    def test_rejects_empty_url(self) -> None:
        with self.assertRaises(FetchError):
            Fetcher(retries=0)._request_once("GET", "http://", {})  # noqa: SLF001


class ErrorDetailTests(unittest.TestCase):
    """The 4xx body is where servers explain what went wrong."""

    def test_includes_body_snippet(self) -> None:
        # The exact response ntfy returns when a JSON field has the wrong type.
        body = b'{"code":40024,"http":400,"error":"request body must be valid JSON"}'
        detail = _error_detail(body)
        self.assertTrue(detail.startswith(": "))
        self.assertIn("request body must be valid JSON", detail)

    def test_empty_body_yields_no_detail(self) -> None:
        self.assertEqual(_error_detail(b""), "")
        self.assertEqual(_error_detail(b"   \n  "), "")

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(_error_detail(b"line one\n  line two"), ": line one line two")

    def test_truncates_long_bodies(self) -> None:
        detail = _error_detail(b"x" * 5000)
        self.assertTrue(detail.endswith("…"))
        self.assertLess(len(detail), 320)


if __name__ == "__main__":
    unittest.main()
