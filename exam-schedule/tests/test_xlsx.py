"""Tests for the dependency-free XLSX reader, using a synthetic workbook.

The fixture mirrors the real SDU workbook: the data lives in an Excel table
named ``XPlan`` on the second sheet, with a header row and a comma-separated
``Udd`` (programme) column.
"""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sdu_exam_watch import xlsx  # noqa: E402

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

HEADER = [
    "EKA",
    "Course title",
    "Internal code",
    "Semester",
    "Ordinary exam",
    "Campus",
    "Form of examination",
    "Examiner",
    "Form of censorship",
    "RE-exam dates",
    "Notifikations",
    "BEMÆRK til SN",
    "Udd",
]
COLS = "BCDEFGHIJKLMN"

SWE = "Kandidat i Software Engineering (MSc)"
ROW_SWE = [
    "T510063102",
    "Introduktion til OOP",
    "SE-OOP",
    "1",
    "20-05-2026",
    "Odense",
    "Written exam",
    "Someone",
    "None",
    "10-08-2026",
    "1",
    "",
    f",,,{SWE},,,",
]
ROW_OTHER = [
    "T170008102",
    "Stabilitet",
    "MK-SS",
    "2",
    "25-05-2026",
    "Odense",
    "Portfolio",
    "Other",
    "None",
    "",
    "2",
    "",
    ",,,Kandidat i mekanik (MSc),,,",
]


def build_workbook(rows, *, with_table=True, title="TEK Exam Schedule Test") -> bytes:
    """Build a minimal .xlsx whose shape matches the real SDU export."""
    shared: list[str] = []

    def index(value: str) -> int:
        if value not in shared:
            shared.append(value)
        return shared.index(value)

    def cell(ref: str, value: str) -> str:
        return f'<c r="{ref}" t="s"><v>{index(value)}</v></c>'

    header_row = "".join(
        cell(f"{c}13", name) for c, name in zip(COLS, HEADER, strict=True)
    )
    data_rows = [
        f'<row r="{n}">'
        + "".join(cell(f"{c}{n}", v) for c, v in zip(COLS, row, strict=True))
        + "</row>"
        for n, row in enumerate(rows, start=14)
    ]
    sheet2 = (
        f'<?xml version="1.0"?><worksheet xmlns="{MAIN_NS}"><sheetData>'
        f'<row r="13">{header_row}</row>{"".join(data_rows)}'
        "</sheetData></worksheet>"
    )
    sheet1 = (
        f'<?xml version="1.0"?><worksheet xmlns="{MAIN_NS}"><sheetData>'
        f'<row r="1">{cell("B1", title)}</row>'
        "</sheetData></worksheet>"
    )
    shared_xml = (
        f'<?xml version="1.0"?><sst xmlns="{MAIN_NS}" count="{len(shared)}" '
        f'uniqueCount="{len(shared)}">'
        + "".join(f"<si><t>{s}</t></si>" for s in shared)
        + "</sst>"
    )
    workbook = (
        f'<?xml version="1.0"?><workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>'
        f'<sheet name="Schedule" sheetId="1" r:id="rId1"/>'
        f'<sheet name="XPlan" sheetId="2" r:id="rId2"/>'
        "</sheets></workbook>"
    )
    workbook_rels = (
        f'<?xml version="1.0"?><Relationships xmlns="{PKG_NS}">'
        f'<Relationship Id="rId1" Type="{REL_NS}/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{REL_NS}/worksheet" '
        'Target="worksheets/sheet2.xml"/>'
        "</Relationships>"
    )
    table = (
        f'<?xml version="1.0"?><table xmlns="{MAIN_NS}" id="1" name="XPlan" '
        f'displayName="XPlan" ref="B13:N{13 + len(rows)}"><tableColumns count="13">'
        + "".join(
            f'<tableColumn id="{i}" name="{name}"/>'
            for i, name in enumerate(HEADER, start=1)
        )
        + "</tableColumns></table>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet1)
        archive.writestr("xl/worksheets/sheet2.xml", sheet2)
        if with_table:
            archive.writestr(
                "xl/worksheets/_rels/sheet2.xml.rels",
                f'<?xml version="1.0"?><Relationships xmlns="{PKG_NS}">'
                f'<Relationship Id="rId1" Type="{REL_NS}/table" '
                'Target="../tables/table1.xml"/>'
                "</Relationships>",
            )
            archive.writestr("xl/tables/table1.xml", table)
    return buffer.getvalue()


class ReadScheduleTests(unittest.TestCase):
    def test_reads_all_rows_and_title(self) -> None:
        schedule = xlsx.read_schedule(build_workbook([ROW_SWE, ROW_OTHER]))
        self.assertEqual(schedule.title, "TEK Exam Schedule Test")
        self.assertEqual(len(schedule.exams), 2)

    def test_filters_by_programme(self) -> None:
        schedule = xlsx.read_schedule(build_workbook([ROW_SWE, ROW_OTHER]), (SWE,))
        self.assertEqual(len(schedule.exams), 1)
        exam = schedule.exams[0]
        self.assertEqual(exam.code, "T510063102")
        self.assertEqual(exam.title, "Introduktion til OOP")
        self.assertEqual(exam.date, "20-05-2026")
        self.assertEqual(exam.campus, "Odense")
        self.assertIn(SWE, exam.programmes)

    def test_programme_match_is_exact_token(self) -> None:
        schedule = xlsx.read_schedule(
            build_workbook([ROW_SWE, ROW_OTHER]), ("mekanik",)
        )
        self.assertEqual([e.code for e in schedule.exams], ["T170008102"])

    def test_header_scan_fallback_without_table(self) -> None:
        # No table part: the reader must fall back to scanning for the header.
        schedule = xlsx.read_schedule(build_workbook([ROW_SWE], with_table=False))
        self.assertEqual(len(schedule.exams), 1)
        self.assertEqual(schedule.exams[0].code, "T510063102")

    def test_bad_zip_raises(self) -> None:
        with self.assertRaises(xlsx.XlsxError):
            xlsx.read_schedule(b"this is not a zip")

    def test_doctype_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><workbook/>',
            )
            archive.writestr("xl/_rels/workbook.xml.rels", "<Relationships/>")
        with self.assertRaises(xlsx.XlsxError):
            xlsx.read_schedule(buffer.getvalue())


class HelperTests(unittest.TestCase):
    def test_excel_serial_to_date(self) -> None:
        self.assertEqual(xlsx.excel_serial_to_date("46119"), "2026-04-07")
        self.assertEqual(xlsx.excel_serial_to_date("not a date"), "not a date")
        self.assertEqual(xlsx.excel_serial_to_date("0"), "0")

    def test_matches_programmes_substring(self) -> None:
        entry = xlsx.ExamEntry(programmes=("Kandidat i Software Engineering (MSc)",))
        self.assertTrue(xlsx.matches_programmes(entry, ("Software Engineering",)))
        self.assertFalse(xlsx.matches_programmes(entry, ("Mekanik",)))


if __name__ == "__main__":
    unittest.main()
