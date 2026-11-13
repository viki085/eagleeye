"""PDF via pypdf, page by page.

Extracted PDF text has no structure, only lines. Headings are recovered heuristically:
- always: short unpunctuated lines that are ALL CAPS or numbered like "2.1 Returns";
- slide markers ("Slide 3 of 12"): a section break, and the next line is the slide title;
- bullets ("- ", "*", "1."): each bullet starts its own block, so long slides split cleanly;
- Title Case lines ("Health Insurance"): short, unpunctuated, every significant word capitalised.
The last three are options (PdfOptions); the defaults were chosen with the retrieval eval
(evals/retrieval_eval.py, ADR-32).
"""

import io
import logging
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ingest_worker.errors import PermanentIngestError
from ingest_worker.parsing.base import ParsedDocument, ParsedElement

logger = logging.getLogger(__name__)

MIN_CHARS_PER_PAGE = 50
MAX_HEADING_CHARS = 80
TITLE_MAX_WORDS = 8
_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+[A-Z]")
# "Slide 3", "Slide 3 of 12", "SLIDE 137: Title", "Slide 138 - Title" (title on the same line)
_SLIDE_MARKER = re.compile(
    r"^(?:slide|page)\s+\d+(?:\s*(?:of|/)\s*\d+)?"
    r"(?:\s*[:.\-–—]\s*(?P<title>\S.*))?$",
    re.IGNORECASE,
)
# "- x", "* x", "• x", "1. x", and bullet glyphs pypdf extracts as control/private-use chars
_BULLET = re.compile(
    r"^(?:[\x00-\x08\uf0a7\uf0b7\uf0d8]+\s*|[-*\u2022\u25aa\u25cf\u2013]\s+|\d+[.)]\s+)"
)
_SMALL_WORDS = frozenset("a an and as at by for from in into of on or per the to vs with".split())


@dataclass(frozen=True)
class PdfOptions:
    slide_markers: bool = False
    bullets: bool = False
    title_case_headings: bool = False


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


def is_title_case_heading(line: str) -> bool:
    """'Health Insurance' yes; sentences, labels ('Contact: …'), single words and lines that
    start with numbers or amounts no."""
    s = line.strip()
    if not s or len(s) > MAX_HEADING_CHARS or s[-1] in ".,;:!?" or ":" in s:
        return False
    words = s.split()
    if not 2 <= len(words) <= TITLE_MAX_WORDS:
        return False
    significant = [w for w in words if w.lower() not in _SMALL_WORDS]
    return bool(significant) and all(w[0].isalpha() and w[0].isupper() for w in significant)


def page_elements(text: str, page_no: int, options: PdfOptions) -> list[ParsedElement]:
    elements: list[ParsedElement] = []
    buf: list[str] = []
    expect_title = False

    def flush() -> None:
        if buf:
            elements.append(ParsedElement(" ".join(buf), page=page_no))
            buf.clear()

    def heading(line: str, level: int) -> None:
        flush()
        elements.append(ParsedElement(line, page=page_no, heading_level=level))

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        marker = _SLIDE_MARKER.match(line) if options.slide_markers else None
        if marker:
            flush()
            title = (marker.group("title") or "").strip()
            if title:
                heading(title[:MAX_HEADING_CHARS], 1)
            else:
                expect_title = True  # the slide title is on the next line
            continue
        if expect_title:
            expect_title = False
            if len(line) <= MAX_HEADING_CHARS and line[-1] not in ".,;:":
                heading(line, 1)
                continue
        level = heading_level(line)
        if level is None and options.title_case_headings and is_title_case_heading(line):
            level = 1
        if level is not None:
            heading(line, level)
            continue
        if options.bullets and _BULLET.match(line):
            flush()
        buf.append(line)
    flush()
    return elements


# Chosen with the retrieval eval (config C, ADR-32). Title Case headings stayed off: they
# helped Title Case PDFs but did not beat C overall, and can misfire on short wrapped lines.
DEFAULT_OPTIONS = PdfOptions(slide_markers=True, bullets=True)


class PdfParser:
    def __init__(self, options: PdfOptions = DEFAULT_OPTIONS) -> None:
        self.options = options

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
        elements = [
            el
            for i, text in enumerate(pages, start=1)
            for el in page_elements(text, i, self.options)
        ]
        return ParsedDocument(tuple(elements), page_count=page_count)
