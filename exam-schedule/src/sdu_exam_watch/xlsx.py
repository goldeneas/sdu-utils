"""Minimal, dependency-free reader for the SDU engineering exam-schedule XLSX.

The published spreadsheet is an ordinary ``.xlsx`` (a ZIP of XML). Sheet 1 is a
live ``FILTER()`` view; the authoritative data lives in a proper Excel table
named ``XPlan`` whose columns are::

    EKA | Course title | Internal code | Semester | Ordinary exam | Campus |
    Form of examination | Examiner | Form of censorship | RE-exam dates |
    Notifikations | BEMÆRK til SN | Udd

``Udd`` ("uddannelse" = education/programme) is a comma-separated list of the
programmes a course belongs to, e.g. ``",,,Kandidat i Software Engineering
(MSc),,,Alle eksamener"``. That is what lets us show a student *their* exams.

This module parses the package with the standard library only and streams the
worksheet XML so a ~10 MB sheet never has to be materialised as objects. All
XML parsing goes through :mod:`sdu_exam_watch.xmlsafe` because the workbook is
downloaded from the network.
"""

from __future__ import annotations

import datetime as _dt
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

from . import xmlsafe

log = logging.getLogger(__name__)

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_RNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")
_TABLE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"
)

# Column header -> attribute on ExamEntry. Matching is case-insensitive.
_FIELD_BY_HEADER = {
    "eka": "code",
    "exam code": "code",
    "course title": "title",
    "internal code": "internal_code",
    "semester": "semester",
    "ordinary exam": "date",
    "ordinary exam dates (dd-mm-yyyy)": "date",
    "campus": "campus",
    "form of examination": "form",
    "re-exam dates": "re_exam",
    "re-exam dates (dd-mm-yyyy)": "re_exam",
    "udd": "programmes",
}
# Headers that must be present for a row to be treated as the table header.
_HEADER_ANCHORS = ("eka", "course title")
# Fields whose text may be stored as an Excel serial number instead of a string.
_DATE_FIELDS = frozenset({"date", "re_exam"})


@dataclass(slots=True)
class ExamEntry:
    """One exam row from the schedule."""

    code: str = ""
    title: str = ""
    internal_code: str = ""
    semester: str = ""
    date: str = ""
    campus: str = ""
    form: str = ""
    re_exam: str = ""
    programmes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "internal_code": self.internal_code,
            "semester": self.semester,
            "date": self.date,
            "campus": self.campus,
            "form": self.form,
            "re_exam": self.re_exam,
            "programmes": list(self.programmes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExamEntry:
        raw_programmes = data.get("programmes") or []
        programmes: tuple[str, ...] = ()
        if isinstance(raw_programmes, (list, tuple)):
            programmes = tuple(str(item) for item in raw_programmes)
        return cls(
            code=str(data.get("code", "")),
            title=str(data.get("title", "")),
            internal_code=str(data.get("internal_code", "")),
            semester=str(data.get("semester", "")),
            date=str(data.get("date", "")),
            campus=str(data.get("campus", "")),
            form=str(data.get("form", "")),
            re_exam=str(data.get("re_exam", "")),
            programmes=programmes,
        )


@dataclass(slots=True)
class Schedule:
    """Everything we extract from one spreadsheet."""

    title: str = ""
    exams: list[ExamEntry] = field(default_factory=list)


class XlsxError(RuntimeError):
    """Raised when the workbook cannot be understood at all."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_schedule(data: bytes, programmes: tuple[str, ...] = ()) -> Schedule:
    """Read an exam-schedule workbook.

    Parameters
    ----------
    data:
        Raw ``.xlsx`` bytes.
    programmes:
        Programme names to keep (matched against the ``Udd`` list). An empty
        tuple keeps every exam.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError(f"not a valid .xlsx package: {exc}") from exc

    try:
        shared = _read_shared_strings(archive)
        title = _read_workbook_title(archive, shared)
        exams = _read_table_rows(archive, shared)
        if not exams:
            # Layout changed or the workbook uses a narrow view; fall back to a
            # header scan across every worksheet.
            exams = _read_by_header_scan(archive, shared)
    except (xmlsafe.XmlSecurityError, KeyError, ValueError) as exc:
        raise XlsxError(f"could not read workbook: {exc}") from exc

    if programmes:
        exams = [entry for entry in exams if _matches_programmes(entry, programmes)]

    return Schedule(title=title, exams=exams)


def matches_programmes(entry: ExamEntry, programmes: tuple[str, ...]) -> bool:
    """Whether ``entry`` belongs to any of the given programme names."""
    return _matches_programmes(entry, programmes)


# ---------------------------------------------------------------------------
# Package plumbing
# ---------------------------------------------------------------------------


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    strings: list[str] = []
    with archive.open("xl/sharedStrings.xml") as handle:
        for _, elem in xmlsafe.iterparse(handle):
            if elem.tag == _NS + "si":
                strings.append(_element_text(elem))
                elem.clear()
    return strings


def _read_workbook_title(archive: zipfile.ZipFile, shared: list[str]) -> str:
    """Return the first non-empty string cell of the first worksheet."""
    try:
        first_sheet = _worksheet_paths(archive)[0][1]
    except (KeyError, IndexError):
        return ""
    with archive.open(first_sheet) as handle:
        for _, elem in xmlsafe.iterparse(handle):
            if elem.tag != _NS + "row":
                continue
            for value in _row_values(elem, shared).values():
                text = value.strip()
                if text and not text.isdigit():
                    elem.clear()
                    return text
            number = _parse_int(elem.get("r")) or 0
            elem.clear()
            if number >= 4:  # the title lives in the first rows; stop early
                break
    return ""


def _worksheet_paths(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return ``(sheet_name, zip_path)`` pairs in workbook order."""
    workbook = xmlsafe.fromstring(archive.read("xl/workbook.xml"))
    rels = xmlsafe.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target_by_id = {
        rel.get("Id"): rel.get("Target", "")
        for rel in rels.findall(_PKG_RNS + "Relationship")
    }
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall(f"{_NS}sheets/{_NS}sheet"):
        target = target_by_id.get(sheet.get(_RNS + "id"), "")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target.lstrip("./")
        sheets.append((sheet.get("name", ""), path))
    return sheets


def _sheet_rels_path(sheet_path: str) -> str:
    directory, _, name = sheet_path.rpartition("/")
    return f"{directory}/_rels/{name}.rels"


def _tables_for_sheet(archive: zipfile.ZipFile, sheet_path: str) -> list[str]:
    rels_path = _sheet_rels_path(sheet_path)
    if rels_path not in archive.namelist():
        return []
    rels = xmlsafe.fromstring(archive.read(rels_path))
    tables = []
    for rel in rels.findall(_PKG_RNS + "Relationship"):
        if rel.get("Type") == _TABLE_REL_TYPE:
            target = rel.get("Target", "")
            tables.append("xl/" + target.replace("../", "").lstrip("./"))
    return tables


# ---------------------------------------------------------------------------
# Table-based extraction (the normal path)
# ---------------------------------------------------------------------------


def _read_table_rows(archive: zipfile.ZipFile, shared: list[str]) -> list[ExamEntry]:
    """Find the ``XPlan``-style table and read its rows."""
    for sheet_name, sheet_path in _worksheet_paths(archive):
        for table_path in _tables_for_sheet(archive, sheet_path):
            try:
                table = xmlsafe.fromstring(archive.read(table_path))
            except KeyError:
                continue
            columns = [
                col.get("name", "")
                for col in table.findall(f"{_NS}tableColumns/{_NS}tableColumn")
            ]
            headers = [_normalise_header(name) for name in columns]
            if not all(anchor in headers for anchor in _HEADER_ANCHORS):
                continue
            start_col, start_row, end_col, end_row = _parse_range(table.get("ref", ""))
            if start_col is None:
                continue
            log.debug(
                "reading table %s on sheet %s (%s)",
                table.get("name"), sheet_name, table.get("ref", ""),
            )
            return _collect_rows(
                archive,
                sheet_path,
                shared,
                header_row=start_row,
                first_col=start_col,
                last_col=end_col,
                last_row=end_row,
                headers_by_col=dict(
                    zip(_column_range(start_col, end_col), headers, strict=True)
                ),
            )
    return []


def _collect_rows(
    archive: zipfile.ZipFile,
    sheet_path: str,
    shared: list[str],
    *,
    header_row: int,
    first_col: int,
    last_col: int,
    last_row: int | None,
    headers_by_col: dict[int, str],
) -> list[ExamEntry]:
    """Stream ``sheet_path`` collecting rows after ``header_row``."""
    field_by_col = {
        col: _FIELD_BY_HEADER[header]
        for col, header in headers_by_col.items()
        if header in _FIELD_BY_HEADER and first_col <= col <= last_col
    }
    if not field_by_col:
        return []

    entries: list[ExamEntry] = []
    with archive.open(sheet_path) as handle:
        for _, row in xmlsafe.iterparse(handle):
            if row.tag != _NS + "row":
                continue
            number = _parse_int(row.get("r")) or 0
            if number <= header_row:
                row.clear()
                continue
            if last_row is not None and number > last_row:
                row.clear()
                break
            entry = _entry_from_row(_row_values(row, shared), field_by_col)
            if entry is not None:
                entries.append(entry)
            row.clear()
    return entries


def _entry_from_row(
    values: dict[int, str], field_by_col: dict[int, str]
) -> ExamEntry | None:
    """Build an :class:`ExamEntry` from one data row, or ``None`` if empty."""
    entry = ExamEntry()
    seen = False
    for col, attribute in field_by_col.items():
        raw = values.get(col, "").strip()
        if not raw:
            continue
        if attribute == "programmes":
            entry.programmes = _split_programmes(raw)
        elif attribute in _DATE_FIELDS:
            setattr(entry, attribute, excel_serial_to_date(raw))
        else:
            setattr(entry, attribute, raw)
        seen = True
    return entry if seen else None


# ---------------------------------------------------------------------------
# Fallback: header scan across every sheet
# ---------------------------------------------------------------------------


def _read_by_header_scan(archive: zipfile.ZipFile, shared: list[str]) -> list[ExamEntry]:
    for _, sheet_path in _worksheet_paths(archive):
        header_row: int | None = None
        field_by_col: dict[int, str] = {}
        entries: list[ExamEntry] = []
        with archive.open(sheet_path) as handle:
            for _, row in xmlsafe.iterparse(handle):
                if row.tag != _NS + "row":
                    continue
                values = _row_values(row, shared)
                if header_row is None:
                    normalised = {c: _normalise_header(v) for c, v in values.items()}
                    if all(anchor in normalised.values() for anchor in _HEADER_ANCHORS):
                        header_row = _parse_int(row.get("r")) or 0
                        field_by_col = {
                            c: _FIELD_BY_HEADER[h]
                            for c, h in normalised.items()
                            if h in _FIELD_BY_HEADER
                        }
                    row.clear()
                    continue
                entry = _entry_from_row(values, field_by_col)
                if entry is not None:
                    entries.append(entry)
                row.clear()
        if entries:
            return entries
    return []


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _element_text(elem: Any) -> str:
    """Concatenate all ``<t>`` descendants (handles rich-text runs)."""
    return "".join(node.text or "" for node in elem.iter(_NS + "t"))


def _row_values(row: Any, shared: list[str]) -> dict[int, str]:
    """Map column index (0-based) -> cell text for one ``<row>``."""
    values: dict[int, str] = {}
    for cell in row:
        if cell.tag != _NS + "c":
            continue
        match = _CELL_REF_RE.match(cell.get("r", ""))
        if not match:
            continue
        raw = _cell_text(cell, shared)
        if raw is not None and raw.strip():
            values[_column_index(match.group(1))] = raw
    return values


def _cell_text(cell: Any, shared: list[str]) -> str | None:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(_NS + "is")
        return _element_text(inline) if inline is not None else None
    value = cell.find(_NS + "v")
    if value is None or value.text is None:
        return None
    if cell_type == "s":
        index = _parse_int(value.text)
        if index is None or not 0 <= index < len(shared):
            return None
        return shared[index]
    return value.text


def _normalise_header(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _column_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _column_range(first: int, last: int) -> list[int]:
    return list(range(first, last + 1))


def _parse_range(ref: str) -> tuple[int | None, int, int, int | None]:
    """Parse an Excel range like ``B13:N386`` into column/row indices."""
    if ":" not in ref:
        return None, 0, 0, None
    left, right = ref.split(":", 1)
    left_match = _CELL_REF_RE.match(left.strip())
    right_match = _CELL_REF_RE.match(right.strip())
    if not left_match or not right_match:
        return None, 0, 0, None
    return (
        _column_index(left_match.group(1)),
        _parse_int(left_match.group(2)) or 0,
        _column_index(right_match.group(1)),
        _parse_int(right_match.group(2)) or 0,
    )


def _split_programmes(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _matches_programmes(entry: ExamEntry, programmes: tuple[str, ...]) -> bool:
    """True when any ``Udd`` token exactly equals, or contains, a wanted name."""
    wanted = [name.strip().casefold() for name in programmes if name.strip()]
    if not wanted:
        return True
    available = [name.casefold() for name in entry.programmes]
    if any(name in available for name in wanted):
        return True
    # Substring fallback for partially-specified names ("Software Engineering").
    return any(name in token for name in wanted for token in available)


def excel_serial_to_date(value: str) -> str:
    """Convert an Excel serial date (e.g. ``46119``) to ``YYYY-MM-DD``.

    Returns the input unchanged when it is not a plausible serial number.
    """
    text = value.strip()
    serial = _parse_int(text)
    if serial is None or not 1 <= serial <= 80000:
        return value
    base = _dt.date(1899, 12, 30)
    return (base + _dt.timedelta(days=serial)).isoformat()


def _parse_int(value: Any) -> int | None:
    """Parse an integer, returning ``None`` instead of raising."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
