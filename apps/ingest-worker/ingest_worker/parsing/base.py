from dataclasses import dataclass
from typing import Protocol


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
