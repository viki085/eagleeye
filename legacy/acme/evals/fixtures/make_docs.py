"""Renders the retrieval-eval corpus (docs_spec.py) to real files + the golden question set.

uv run --package eagleeye-ingest-worker --with fpdf2 python evals/fixtures/make_docs.py

Writes evals/fixtures/retrieval_docs/*.{pdf,docx,md,txt} and evals/retrieval_golden.jsonl.
Every third question is held out ("test") to confirm the chunking choice made on "dev".
"""

import json
import sys
from pathlib import Path

from docx import Document
from fpdf import FPDF

sys.path.insert(0, str(Path(__file__).parent))
from docs_spec import DOCS, FILLER, Doc, all_facts  # noqa: E402

HERE = Path(__file__).parent
OUT_DIR = HERE / "retrieval_docs"
GOLDEN = HERE.parent / "retrieval_golden.jsonl"
NEXT_LINE = {"new_x": "LMARGIN", "new_y": "NEXT"}  # fpdf2 keeps x at the right edge otherwise
EXT = {
    "pdf_slides": "pdf",
    "pdf_numbered": "pdf",
    "pdf_titlecase": "pdf",
    "docx": "docx",
    "md": "md",
    "txt": "txt",
}


def _filler(doc_i: int, sec_i: int, n: int) -> list[str]:
    return [FILLER[(doc_i + sec_i + k) % len(FILLER)] for k in range(n)]


def _paragraph(facts: tuple) -> str:
    return " ".join(f.sentence for f in facts)


def _pdf_document(doc: Doc, doc_i: int) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 9, doc.title, **NEXT_LINE)
    for s_i, sec in enumerate(doc.sections):
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)  # numbered or Title Case, depending on the spec
        pdf.multi_cell(0, 7, sec.heading, **NEXT_LINE)
        pdf.set_font("Helvetica", "", 10)
        for para in [_paragraph(sec.facts), *_filler(doc_i, s_i, sec.filler)]:
            pdf.multi_cell(0, 5, para, **NEXT_LINE)
            pdf.ln(2)
    return bytes(pdf.output())


def _pdf_slides(doc: Doc, doc_i: int) -> bytes:
    """Dense slide export: 3 slides per page, bullets, no blank lines between slides."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    for s_i, sec in enumerate(doc.sections):
        if s_i % 3 == 0:
            pdf.add_page()
            pdf.set_y(12)
        pdf.set_font("Helvetica", "", 8)
        # as real exports print it; not ALL CAPS, so the parser's heading rule misses it
        pdf.cell(0, 4, f"Slide {s_i + 1} of {len(doc.sections)}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, sec.heading, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for fact in sec.facts:
            pdf.multi_cell(0, 5, f"- {fact.sentence}", **NEXT_LINE)
        for para in _filler(doc_i, s_i, sec.filler):
            pdf.multi_cell(0, 5, f"- {para}", **NEXT_LINE)
    return bytes(pdf.output())


def _docx(doc: Doc, doc_i: int) -> bytes:
    d = Document()
    d.add_heading(doc.title, level=0)
    for s_i, sec in enumerate(doc.sections):
        d.add_heading(sec.heading, level=1)
        for para in [_paragraph(sec.facts), *_filler(doc_i, s_i, sec.filler)]:
            d.add_paragraph(para)
    if doc.table:
        table = d.add_table(rows=0, cols=len(doc.table[0]))
        for row in doc.table:
            cells = table.add_row().cells
            for cell, value in zip(cells, row, strict=True):
                cell.text = value
    path = OUT_DIR / f"_{doc.name}.tmp.docx"
    d.save(path)
    data = path.read_bytes()
    path.unlink()
    return data


def _markdown(doc: Doc, doc_i: int) -> bytes:
    lines = [f"# {doc.title}", ""]
    for s_i, sec in enumerate(doc.sections):
        lines += [f"## {sec.heading}", ""]
        for para in [_paragraph(sec.facts), *_filler(doc_i, s_i, sec.filler)]:
            lines += [para, ""]
    return "\n".join(lines).encode()


def _text(doc: Doc, doc_i: int) -> bytes:
    lines = [doc.title, ""]
    for s_i, sec in enumerate(doc.sections):
        lines += [sec.heading, ""]
        for para in [_paragraph(sec.facts), *_filler(doc_i, s_i, sec.filler)]:
            lines += [para, ""]
    return "\n".join(lines).encode()


RENDER = {
    "pdf_numbered": _pdf_document,
    "pdf_titlecase": _pdf_document,
    "pdf_slides": _pdf_slides,
    "docx": _docx,
    "md": _markdown,
    "txt": _text,
}


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for i, doc in enumerate(DOCS):
        (OUT_DIR / f"{doc.name}.{EXT[doc.kind]}").write_bytes(RENDER[doc.kind](doc, i))
    rows = []
    for n, (doc, sec, fact) in enumerate(all_facts(), start=1):
        rows.append(
            {
                "id": f"q{n:03d}",
                "doc": doc.name,
                "kind": doc.kind,
                "section": sec.heading,
                "question": fact.question,
                "span": fact.span,
                "split": "test" if n % 3 == 0 else "dev",
            }
        )
    GOLDEN.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    dev = sum(r["split"] == "dev" for r in rows)
    print(f"{len(DOCS)} documents, {len(rows)} questions ({dev} dev / {len(rows) - dev} test)")


if __name__ == "__main__":
    main()
