import re
from dataclasses import dataclass, replace
from typing import Protocol

# NUL and other C0 control characters (except tab/newline/CR) show up in text extracted from
# some PDFs (font encodings) and Word files; Postgres text columns reject NUL outright.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class ParsedElement:
    """One paragraph-ish block. heading_level set (1 = top) when the block is a heading."""

    text: str
    page: int | None = None
    heading_level: int | None = None


@dataclass(frozen=True)
class ParsedDocument:
    elements: tuple[ParsedElement, ...]
    page_count: int | None = None


class Parser(Protocol):
    def parse(self, data: bytes) -> ParsedDocument: ...


def clean_text(text: str) -> str:
    """Storable text: no control characters, no lone surrogates (invalid UTF-8)."""
    text = _CONTROL.sub("", text)
    return text.encode("utf-8", "replace").decode("utf-8")


def sanitize(doc: ParsedDocument) -> ParsedDocument:
    """Applied to every parser's output before chunking; drops blocks left empty."""
    cleaned = (replace(el, text=clean_text(el.text)) for el in doc.elements)
    return replace(doc, elements=tuple(el for el in cleaned if el.text.strip()))
