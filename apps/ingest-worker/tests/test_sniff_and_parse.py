import importlib.util
import pathlib

import pytest
from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing.pdf import heading_level
from ingest_worker.parsing.registry import parser_for
from ingest_worker.sniff import sniff

_spec = importlib.util.spec_from_file_location(
    "worker_fixtures", pathlib.Path(__file__).with_name("fixtures.py")
)
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)  # type: ignore[union-attr]


def test_sniff_accepts_matching_types() -> None:
    assert sniff("a.pdf", fixtures.make_pdf([["hello"]])) == "pdf"
    assert sniff("a.docx", fixtures.make_docx()) == "docx"
    assert sniff("notes.MD", b"# Title\n\nbody") == "markdown"
    assert sniff("a.txt", "héllo".encode()) == "text"


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("evil.pdf", b"MZ\x90\x00 this is an exe"),
        ("a.docx", b"PK\x03\x04not really a zip"),
        ("a.txt", b"bin\x00ary"),
        ("a.txt", b"\xff\xfe\xfa"),
        ("a.exe", b"%PDF-1.4"),
        ("noext", b"text"),
        ("empty.txt", b""),
    ],
)
def test_sniff_rejects_spoofed_or_unsupported(name: str, data: bytes) -> None:
    with pytest.raises(PermanentIngestError):
        sniff(name, data)


def test_markdown_headings_and_fences() -> None:
    md = b"# Policy\n\nIntro text.\n\n## Returns\n\n```\n# not a heading\n```\n\nBody."
    doc = parser_for("markdown").parse(md)
    headings = [(e.text, e.heading_level) for e in doc.elements if e.heading_level]
    assert headings == [("Policy", 1), ("Returns", 2)]
    assert any("# not a heading" in e.text for e in doc.elements)


def test_text_paragraphs() -> None:
    doc = parser_for("text").parse(b"one\ntwo\n\nthree\r\n")
    assert [e.text for e in doc.elements] == ["one\ntwo", "three"]


def test_docx_headings_and_tables() -> None:
    doc = parser_for("docx").parse(fixtures.make_docx())
    assert ("Leave Policy", 1) in [(e.text, e.heading_level) for e in doc.elements]
    assert ("Carry over", 2) in [(e.text, e.heading_level) for e in doc.elements]
    assert any("G1 | 25" in e.text for e in doc.elements)


def test_pdf_pages_and_headings() -> None:
    body = "The refund window is thirty days from the date of purchase for all items."
    data = fixtures.make_pdf([["RETURNS POLICY", body], ["2.1 Electronics", body]])
    doc = parser_for("pdf").parse(data)
    assert doc.page_count == 2
    assert ("RETURNS POLICY", 1, 1) in [(e.text, e.heading_level, e.page) for e in doc.elements]
    assert any(e.page == 2 and "refund window" in e.text for e in doc.elements)


def test_scanned_pdf_fails_permanently() -> None:
    with pytest.raises(PermanentIngestError, match="OCR"):
        parser_for("pdf").parse(fixtures.make_blank_pdf())


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("RETURNS POLICY", 1),
        ("2.1 Electronics", 2),
        ("3 Shipping", 1),
        ("This is a normal sentence.", None),
        ("lowercase words here", None),
        ("A" * 100, None),
    ],
)
def test_pdf_heading_heuristic(line: str, level: int | None) -> None:
    assert heading_level(line) == level
