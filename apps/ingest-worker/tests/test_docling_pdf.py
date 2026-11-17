"""Docling PDF parsing end to end: tables kept whole, watermarks removed, scans read by OCR.

These run the real Docling models on CPU (downloaded on first use, then cached)."""

import io

import pytest
from fpdf import FPDF
from ingest_worker import pipeline
from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing import docling_pdf
from ingest_worker.parsing.docling_pdf import DoclingPdfParser
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

SENTENCE = "Revenue grew strongly this year across all regions and the board approved a dividend. "


def _report_pdf(pages: int = 3) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(False)
    for n in range(1, pages + 1):
        pdf.add_page()
        pdf.set_font("Helvetica", size=9)
        pdf.set_xy(10, 8)
        pdf.cell(0, 6, "Acme Corp - Annual Report 2025")
        pdf.set_xy(10, 20)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"Section {n} Revenue", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, SENTENCE * 4)
        with pdf.table() as table:
            for row in (
                ("Region", "2024", "2025"),
                ("North", "120", "150"),
                ("South", "90", "110"),
            ):
                cells = table.row()
                for value in row:
                    cells.cell(value)
        with pdf.rotation(45, 105, 150):
            pdf.set_font("Helvetica", "B", 60)
            pdf.set_text_color(200, 200, 200)
            pdf.text(40, 170, "CONFIDENTIAL")
            pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", size=9)
        pdf.set_xy(10, 285)
        pdf.cell(0, 6, f"Page {n}")
    return bytes(pdf.output())


def _scanned_pdf() -> bytes:
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except OSError:
            font = ImageFont.load_default(size=40)
    for i, line in enumerate(
        ["Employment Contract", "The notice period is ninety days.", "Salary is reviewed yearly."]
    ):
        draw.text((100, 150 + i * 90), line, fill="black", font=font)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    pdf = FPDF()
    pdf.add_page()
    pdf.image(io.BytesIO(buf.getvalue()), x=0, y=0, w=210)
    return bytes(pdf.output())


def test_tables_stay_whole_and_watermarks_headers_and_page_numbers_are_gone() -> None:
    parsed = pipeline.parse("pdf", _report_pdf())
    assert parsed.parser == "docling"
    tables = [e for e in parsed.elements if e.kind == "table"]
    assert len(tables) == 3
    assert "North" in tables[0].text and "150" in tables[0].text
    assert "<table" in (tables[0].table_html or "")
    assert tables[0].bbox is not None and tables[0].page == 1
    text = " ".join(e.text for e in parsed.elements)
    assert "CONFIDENTIAL" not in text
    assert "Acme Corp - Annual Report" not in text
    assert "Page 2" not in text
    assert any(e.heading_level and "Section 2" in e.text for e in parsed.elements)


def test_a_scanned_pdf_is_read_with_ocr_instead_of_failing() -> None:
    parsed = pipeline.parse("pdf", _scanned_pdf())
    text = " ".join(e.text for e in parsed.elements).lower()
    assert "notice period" in text
    assert parsed.ocr_pages == (1,)


def test_password_protected_pdfs_are_still_rejected_clearly() -> None:
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(_report_pdf(1))))
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(PermanentIngestError, match="Password-protected"):
        DoclingPdfParser().parse(buf.getvalue())


def test_a_pdf_over_the_page_cap_is_rejected_before_parsing(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(docling_pdf, "converter", lambda: pytest.fail("must not parse"))
    monkeypatch.setattr(docling_pdf, "get_settings", lambda: type("S", (), {"pdf_max_pages": 2})())
    with pytest.raises(PermanentIngestError, match="limit is 2"):
        DoclingPdfParser().parse(_report_pdf(3))


def test_a_docling_failure_falls_back_to_plain_text(monkeypatch) -> None:  # noqa: ANN001
    class Broken:
        def convert(self, *a: object, **k: object) -> None:
            raise RuntimeError("model crashed")

    monkeypatch.setattr(docling_pdf, "converter", lambda: Broken())
    parsed = DoclingPdfParser().parse(_report_pdf(1))
    assert parsed.parser == "pypdf"
    assert "Revenue grew strongly" in " ".join(e.text for e in parsed.elements)
