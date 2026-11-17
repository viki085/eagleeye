import re
from dataclasses import dataclass, replace
from typing import Literal, Protocol

# NUL and other C0 control characters (except tab/newline/CR) show up in text extracted from
# some PDFs (font encodings) and Word files; Postgres text columns reject NUL outright.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# What a parsed block is. Tables are kept whole (text = Markdown, table_html = structure).
ElementKind = Literal["text", "heading", "list", "table", "caption", "footnote"]
BBox = tuple[float, float, float, float]  # left, top, right, bottom in PDF points


@dataclass(frozen=True)
class ParsedElement:
    """One paragraph-ish block. heading_level set (1 = top) when the block is a heading.

    `bbox` (position on the page) and `kind` come from layout-aware parsers (Docling); the
    plain-text parsers leave them at their defaults."""

    text: str
    page: int | None = None
    heading_level: int | None = None
    kind: ElementKind = "text"
    bbox: BBox | None = None
    table_html: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    elements: tuple[ParsedElement, ...]
    page_count: int | None = None
    parser: str = ""  # "docling" | "pypdf" | "docx" | ... (recorded in the parse report)
    removed: tuple[str, ...] = ()  # watermark / header / footer strings dropped by clean()
    ocr_pages: tuple[int, ...] = ()  # pages read by OCR (scanned or image-only)
    low_confidence_pages: tuple[int, ...] = ()  # OCR pages below the confidence threshold

    def report(self) -> dict:
        """documents.parse_report: how the file was read (no document text beyond the
        removed watermark strings, which the eval checks never reach a chunk)."""
        return {
            "parser": self.parser,
            "elements": len(self.elements),
            "tables": sum(1 for e in self.elements if e.kind == "table"),
            "ocr_pages": list(self.ocr_pages),
            "low_confidence_pages": list(self.low_confidence_pages),
            "removed": list(self.removed),
        }


class Parser(Protocol):
    def parse(self, data: bytes) -> ParsedDocument: ...


def clean_text(text: str) -> str:
    """Storable text: no control characters, no lone surrogates (invalid UTF-8)."""
    text = _CONTROL.sub("", text)
    return text.encode("utf-8", "replace").decode("utf-8")


def sanitize(doc: ParsedDocument) -> ParsedDocument:
    """Applied to every parser's output before chunking; drops blocks left empty."""
    cleaned = (
        replace(
            el,
            text=clean_text(el.text),
            table_html=clean_text(el.table_html) if el.table_html else el.table_html,
        )
        for el in doc.elements
    )
    return replace(doc, elements=tuple(el for el in cleaned if el.text.strip()))
