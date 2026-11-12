"""DOCX via python-docx. Headings come from paragraph styles ("Heading 1", "Title")."""

import io
import re

import docx

from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing.base import ParsedDocument, ParsedElement

_HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    if style_name.lower() == "title":
        return 1
    match = _HEADING_STYLE.match(style_name.strip())
    return int(match.group(1)) if match else None


class DocxParser:
    def parse(self, data: bytes) -> ParsedDocument:
        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:  # python-docx raises a variety of zip/xml errors
            raise PermanentIngestError("The Word document could not be read.") from exc

        elements: list[ParsedElement] = []
        for para in document.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name if para.style is not None else None
            elements.append(ParsedElement(text, heading_level=_heading_level(style)))
        for table in document.tables:
            rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
            body = "\n".join(r for r in rows if r.strip(" |"))
            if body:
                elements.append(ParsedElement(body))
        return ParsedDocument(tuple(elements))
