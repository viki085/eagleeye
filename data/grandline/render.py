"""Render a Markdown document body to PDF, slide PDF, DOCX, Markdown or plain text.

Every rendered document carries the same corporate frame: company name, document number,
classification, version, effective date and owner, plus page numbers in PDFs.
"""

import io
import re
from dataclasses import dataclass

from docx import Document
from docx.shared import Pt
from fpdf import FPDF

COMPANY = "Grand Line Shipping Company"
NEXT = {"new_x": "LMARGIN", "new_y": "NEXT"}
LATIN1 = str.maketrans({
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "•": "-", "…": "...", " ": " ", "≤": "<=", "≥": ">=", "→": "->",
    "×": "x", "−": "-", " ": " ", " ": " ", "‑": "-", "±": "+/-",
})


@dataclass(frozen=True)
class Meta:
    doc_number: str
    title: str
    classification: str  # Internal | Confidential | Restricted | Public
    version: str
    effective: str
    owner: str


@dataclass(frozen=True)
class Block:
    kind: str  # h1 h2 h3 p bullet number table
    text: str = ""
    rows: tuple[tuple[str, ...], ...] = ()


def parse(md: str) -> list[Block]:
    blocks: list[Block] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = tuple(c.strip() for c in lines[i].strip().strip("|").split("|"))
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(Block("table", rows=tuple(rows)))
            continue
        m = re.match(r"(#{1,3})\s+(.*)", line)
        if m:
            blocks.append(Block(f"h{len(m.group(1))}", m.group(2).strip()))
        elif re.match(r"\s*[-*]\s+", line):
            blocks.append(Block("bullet", re.sub(r"^\s*[-*]\s+", "", line)))
        elif re.match(r"\s*\d+[.)]\s+", line):
            blocks.append(Block("number", line.strip()))
        else:
            para = [line.strip()]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(
                    r"(#{1,3}\s|\s*[-*]\s|\s*\d+[.)]\s|\|)", lines[i + 1]):
                i += 1
                para.append(lines[i].strip())
            blocks.append(Block("p", " ".join(para)))
        i += 1
    return blocks


def _plain(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`", lambda m: next(g for g in m.groups() if g), text)


def _latin(text: str) -> str:
    return _plain(text).translate(LATIN1).encode("latin-1", "replace").decode("latin-1")


class _Pdf(FPDF):
    def __init__(self, meta: Meta, landscape: bool = False) -> None:
        super().__init__(orientation="L" if landscape else "P")
        self.meta = meta
        self.alias_nb_pages()
        self.set_auto_page_break(auto=not landscape, margin=18)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(20, 60, 110)
        self.cell(0, 4, COMPANY.upper(), new_x="RIGHT", new_y="TOP")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 4, f"{self.meta.doc_number}  |  {self.meta.classification}", align="R", **NEXT)
        self.ln(3)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(110, 110, 110)
        self.cell(0, 4, _latin(f"{self.meta.title} - version {self.meta.version} - "
                               f"effective {self.meta.effective}"), new_x="RIGHT", new_y="TOP")
        self.cell(0, 4, f"Page {self.page_no()} of {{nb}}", align="R")


def _meta_table(pdf: FPDF, meta: Meta) -> None:
    pdf.set_font("Helvetica", "", 9)
    for k, v in (("Document number", meta.doc_number), ("Classification", meta.classification),
                 ("Version", meta.version), ("Effective date", meta.effective),
                 ("Document owner", meta.owner)):
        pdf.cell(40, 5, k, border=1)
        pdf.cell(0, 5, _latin(v), border=1, **NEXT)
    pdf.ln(4)


def _pdf_table(pdf: FPDF, rows: tuple[tuple[str, ...], ...]) -> None:
    if not rows:
        return
    cols = max(len(r) for r in rows)
    width = (pdf.w - pdf.l_margin - pdf.r_margin) / cols
    for r_i, row in enumerate(rows):
        pdf.set_font("Helvetica", "B" if r_i == 0 else "", 8)
        height = 5 * max(1, max(len(_latin(c)) // max(int(width / 1.7), 1) + 1 for c in row))
        if pdf.get_y() + height > pdf.h - 20:
            pdf.add_page()
        y = pdf.get_y()
        for c_i in range(cols):
            text = _latin(row[c_i]) if c_i < len(row) else ""
            pdf.set_xy(pdf.l_margin + c_i * width, y)
            pdf.multi_cell(width, 5, text, border=1, max_line_height=5)
        pdf.set_y(y + height)
    pdf.ln(2)


def to_pdf(meta: Meta, md: str) -> bytes:
    pdf = _Pdf(meta)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 17)
    pdf.multi_cell(0, 9, _latin(meta.title), **NEXT)
    pdf.ln(2)
    _meta_table(pdf, meta)
    for b in parse(md):
        if b.kind == "h1" and _latin(b.text) == _latin(meta.title):
            continue
        if b.kind in ("h1", "h2", "h3"):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", {"h1": 14, "h2": 12, "h3": 10.5}[b.kind])
            pdf.multi_cell(0, 6.5, _latin(b.text), **NEXT)
        elif b.kind == "table":
            pdf.set_font("Helvetica", "", 8)
            _pdf_table(pdf, b.rows)
        else:
            pdf.set_font("Helvetica", "", 10)
            prefix = "- " if b.kind == "bullet" else ""
            pdf.set_x(pdf.l_margin + (5 if b.kind in ("bullet", "number") else 0))
            pdf.multi_cell(0, 5, _latin(prefix + b.text), **NEXT)
            pdf.ln(1.5)
    return bytes(pdf.output())


def to_slides(meta: Meta, md: str) -> bytes:
    """One slide per '##' section, landscape, title plus bullets (and tables)."""
    pdf = _Pdf(meta, landscape=True)
    slides: list[tuple[str, list[Block]]] = []
    for b in parse(md):
        if b.kind in ("h1", "h2"):
            slides.append((b.text, []))
        elif slides:
            slides[-1][1].append(b)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 26)
    pdf.ln(40)
    pdf.multi_cell(0, 12, _latin(meta.title), align="C", **NEXT)
    pdf.set_font("Helvetica", "", 13)
    pdf.multi_cell(0, 8, _latin(f"{COMPANY} - {meta.effective} - {meta.classification}"), align="C", **NEXT)
    for n, (title, body) in enumerate(slides, start=1):
        pdf.add_page()
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 4, f"Slide {n + 1}", **NEXT)
        pdf.set_font("Helvetica", "B", 18)
        pdf.multi_cell(0, 9, _latin(title), **NEXT)
        pdf.ln(3)
        for b in body:
            if b.kind == "table":
                _pdf_table(pdf, b.rows)
                continue
            pdf.set_font("Helvetica", "B" if b.kind == "h3" else "", 12)
            text = b.text if b.kind in ("h3", "number") else f"- {b.text}"
            if pdf.get_y() > pdf.h - 20:
                break
            pdf.multi_cell(0, 6.5, _latin(text), **NEXT)
            pdf.ln(1)
    return bytes(pdf.output())


def to_docx(meta: Meta, md: str) -> bytes:
    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(10.5)
    section = d.sections[0]
    section.header.paragraphs[0].text = f"{COMPANY}    {meta.doc_number}    {meta.classification}"
    section.footer.paragraphs[0].text = f"{meta.title} - version {meta.version} - effective {meta.effective}"
    d.add_heading(meta.title, level=0)
    t = d.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in (("Document number", meta.doc_number), ("Classification", meta.classification),
                 ("Version", meta.version), ("Effective date", meta.effective),
                 ("Document owner", meta.owner)):
        cells = t.add_row().cells
        cells[0].text, cells[1].text = k, v
    for b in parse(md):
        if b.kind == "h1" and b.text.strip() == meta.title:
            continue
        if b.kind in ("h1", "h2", "h3"):
            d.add_heading(_plain(b.text), level=int(b.kind[1]))
        elif b.kind == "bullet":
            d.add_paragraph(_plain(b.text), style="List Bullet")
        elif b.kind == "number":
            d.add_paragraph(_plain(re.sub(r"^\d+[.)]\s+", "", b.text)), style="List Number")
        elif b.kind == "table" and b.rows:
            cols = max(len(r) for r in b.rows)
            table = d.add_table(rows=0, cols=cols)
            table.style = "Table Grid"
            for row in b.rows:
                cells = table.add_row().cells
                for c_i in range(cols):
                    cells[c_i].text = _plain(row[c_i]) if c_i < len(row) else ""
        else:
            d.add_paragraph(_plain(b.text))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_markdown(meta: Meta, md: str) -> bytes:
    head = (f"# {meta.title}\n\n**{COMPANY}** | Document {meta.doc_number} | "
            f"{meta.classification} | Version {meta.version} | Effective {meta.effective} | "
            f"Owner: {meta.owner}\n\n")
    body = re.sub(rf"^#\s+{re.escape(meta.title)}\s*\n", "", md.strip())
    return (head + body + "\n").encode("utf-8")


def to_text(meta: Meta, md: str) -> bytes:
    out = [meta.title.upper(), f"{COMPANY} - {meta.doc_number} - {meta.classification} - "
           f"version {meta.version} - effective {meta.effective}", ""]
    for b in parse(md):
        if b.kind == "table":
            out += ["  ".join(r) for r in b.rows] + [""]
        elif b.kind in ("h1", "h2", "h3"):
            out += ["", _plain(b.text).upper() if b.kind != "h3" else _plain(b.text), ""]
        else:
            out.append(("  - " if b.kind == "bullet" else "") + _plain(b.text))
    return "\n".join(out).encode("utf-8")


RENDERERS = {"pdf": to_pdf, "slides": to_slides, "docx": to_docx, "md": to_markdown, "txt": to_text}
EXTENSION = {"pdf": "pdf", "slides": "pdf", "docx": "docx", "md": "md", "txt": "txt"}
