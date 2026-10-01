"""Hardened XML helpers for parsing *downloaded* Office documents.

The watch targets are files fetched over the network, so the XML inside an
``.xlsx`` must be treated as untrusted input. Python's stdlib
``xml.etree.ElementTree`` does not resolve *external* entities, but it will
still expand *internal* entities, which enables "billion laughs" style denial
of service. Office documents never legitimately contain a document type
declaration, so the strongest and simplest mitigation is to refuse any part
that declares a DTD or an entity, then parse with the stdlib.

Every ``xml.etree`` call in this project goes through this module, so the
linter exemption below is deliberate, localised and auditable.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET  # noqa: S405  (parsing is guarded, see below)
from collections.abc import Iterator
from typing import IO, Literal

EventType = Literal["start", "end", "comment", "pi", "start-ns", "end-ns"]

# Markup declarations that must never appear in an untrusted Office part.
# Matching is case-insensitive because the check is a cheap deny-list, not a
# parser: false positives are impossible for real XLSX content.
_FORBIDDEN = (b"<!DOCTYPE", b"<!ENTITY")

# A declaration must appear before the root element, so scanning a prefix is
# enough in practice; we scan generously (2 MiB) to tolerate long comment blocks.
_SCAN_LIMIT = 2 * 1024 * 1024


class XmlSecurityError(RuntimeError):
    """Raised when an XML part contains a DTD or entity declaration."""


def _guard(data: bytes) -> bytes:
    """Reject XML that declares a DTD or entity, then return it unchanged."""
    prefix = data[:_SCAN_LIMIT].upper()
    for marker in _FORBIDDEN:
        if marker in prefix:
            raise XmlSecurityError(
                f"refusing XML containing {marker.decode()} "
                "(document type/entity declarations are not allowed)"
            )
    return data


def fromstring(data: bytes) -> ET.Element:
    """Parse a guarded XML document from bytes."""
    return ET.fromstring(_guard(data))  # noqa: S314  (input is guarded above)


def iterparse(
    source: IO[bytes], events: tuple[EventType, ...] = ("end",)
) -> Iterator[tuple[str, ET.Element]]:
    """Stream-parse a guarded XML document from a binary file object."""
    data = _guard(source.read())
    return ET.iterparse(io.BytesIO(data), events=events)  # noqa: S314  (guarded above)
