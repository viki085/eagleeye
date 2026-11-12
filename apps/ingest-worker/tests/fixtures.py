import io

import docx
from fpdf import FPDF


def make_pdf(pages: list[list[str]]) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    for lines in pages:
        pdf.add_page()
        for line in lines:
            pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
    return bytes(pdf.output())


def make_blank_pdf(n_pages: int = 2) -> bytes:
    pdf = FPDF()
    for _ in range(n_pages):
        pdf.add_page()
    return bytes(pdf.output())


def make_docx() -> bytes:
    d = docx.Document()
    d.add_heading("Leave Policy", level=1)
    d.add_paragraph("Employees receive 25 days of annual leave.")
    d.add_heading("Carry over", level=2)
    d.add_paragraph("Up to 5 days may be carried into the next year.")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Grade"
    table.cell(0, 1).text = "Days"
    table.cell(1, 0).text = "G1"
    table.cell(1, 1).text = "25"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
