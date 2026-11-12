"""PDF via pypdf, page by page. Headings are a heuristic (short, unpunctuated,
ALL CAPS or numbered like "2.1 Returns"); chunking mostly relies on size packing.
"""

import io
import logging
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing.base import ParsedDocument, ParsedElement

logger = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 50
MAX_HEADING_CHARS = 80
_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+[A-Z]")


def heading_level(line: str) -> int | None:
    s = line.strip()
    if not s or len(s) > MAX_HEADING_CHARS or s[-1] in ".,;:":
        return None
    numbered = _NUMBERED.match(s)
    if numbered:
        return min(numbered.group(1).count(".") + 1, 6)
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters):
        return 1
    return None


def _page_elements(text: str, page_no: int) -> list[ParsedElement]:
    elements: list[ParsedElement] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            elements.append(ParsedElement(" ".join(buf), page=page_no))
            buf.clear()

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        level = heading_level(line)
        if level is not None:
            flush()
            elements.append(ParsedElement(line, page=page_no, heading_level=level))
        else:
            buf.append(line)
    flush()
    return elements


class PdfParser:
    def parse(self, data: bytes) -> ParsedDocument:
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise PermanentIngestError("Password-protected PDFs are not supported.")
            pages = [page.extract_text() or "" for page in reader.pages]
        except PdfReadError as exc:
            raise PermanentIngestError("The PDF could not be read.") from exc

        page_count = len(pages)
        total_chars = sum(len(p.strip()) for p in pages)
        if page_count == 0 or total_chars / page_count < MIN_CHARS_PER_PAGE:
            raise PermanentIngestError(
                "No extractable text (scanned PDF — OCR is not supported yet)."
            )
        elements = [el for i, text in enumerate(pages, start=1) for el in _page_elements(text, i)]
        return ParsedDocument(tuple(elements), page_count=page_count)
