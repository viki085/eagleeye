"""CLEAN step: drop watermarks, running headers/footers and page numbers before chunking.

Works on elements that carry a page position (bbox), i.e. the layout-aware parser's output;
elements without one pass through untouched. Rules (multimodal RAG plan, "Watermarks"):
- rotated or very large short text: a box at least WATERMARK_MIN_HEIGHT points tall that is
  not much wider than it is tall, holding a few words ("CONFIDENTIAL" drawn diagonally);
- a short line repeated in the same spot on most pages (headers, footers, "Page 3",
  "DRAFT" stamps). Digits are ignored when comparing, so page numbers match each other,
  except for headings: "Section 1" and "Section 2" in the same spot are real headings, so a
  heading must repeat word for word;
- removed ALL CAPS strings are also cut out of other text, where a watermark drawn over a
  paragraph bleeds into the middle of its sentences.
Tables are never removed or edited.
"""

import re
from collections import defaultdict
from dataclasses import replace

from ingest_worker.parsing.base import ParsedDocument, ParsedElement

WATERMARK_MIN_HEIGHT = 40.0  # points; body text lines are ~10-15 pt tall
WATERMARK_MAX_WORDS = 6
WATERMARK_MIN_SQUARENESS = 0.5  # height / width; a rotated line's box is nearly square
REPEAT_MAX_CHARS = 80
REPEAT_MIN_PAGES = 3
REPEAT_PAGE_SHARE = 0.6
POSITION_GRID = 20.0  # points; boxes within the same grid cell count as "the same spot"

_DIGITS = re.compile(r"\d+")
_SPACE = re.compile(r"\s+")


def _norm(el: ParsedElement) -> str:
    text = _SPACE.sub(" ", el.text.strip().lower())
    return text if el.heading_level is not None else _DIGITS.sub("#", text)


def _is_rotated_or_huge(el: ParsedElement) -> bool:
    if el.bbox is None or el.kind == "table":
        return False
    left, top, right, bottom = el.bbox
    height, width = abs(top - bottom), abs(right - left)
    return (
        height >= WATERMARK_MIN_HEIGHT
        and width > 0
        and height / width >= WATERMARK_MIN_SQUARENESS
        and len(el.text.split()) <= WATERMARK_MAX_WORDS
    )


def _spot(el: ParsedElement) -> tuple[int, int] | None:
    if el.bbox is None:
        return None
    left, top, right, bottom = el.bbox
    return (round((left + right) / 2 / POSITION_GRID), round((top + bottom) / 2 / POSITION_GRID))


def _repeated_keys(elements: tuple[ParsedElement, ...], page_count: int) -> set[tuple]:
    """(normalised text, spot) pairs found on at least REPEAT_PAGE_SHARE of the pages."""
    if page_count < REPEAT_MIN_PAGES:
        return set()
    pages_by_key: dict[tuple, set[int]] = defaultdict(set)
    for el in elements:
        spot = _spot(el)
        if spot is None or el.page is None or el.kind == "table":
            continue
        if len(el.text.strip()) > REPEAT_MAX_CHARS:
            continue
        pages_by_key[(_norm(el), spot)].add(el.page)
    needed = max(REPEAT_MIN_PAGES, int(page_count * REPEAT_PAGE_SHARE + 0.999))
    return {key for key, pages in pages_by_key.items() if len(pages) >= needed}


def _strip_inline(text: str, stamps: list[re.Pattern[str]]) -> str:
    for pattern in stamps:
        text = pattern.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def clean(doc: ParsedDocument) -> ParsedDocument:
    page_count = doc.page_count or len({e.page for e in doc.elements if e.page is not None})
    repeated = _repeated_keys(doc.elements, page_count)
    kept: list[ParsedElement] = []
    removed: dict[str, None] = {}  # ordered set of the original strings
    for el in doc.elements:
        spot = _spot(el)
        if _is_rotated_or_huge(el) or (spot is not None and (_norm(el), spot) in repeated):
            removed.setdefault(el.text.strip(), None)
            continue
        kept.append(el)

    # an ALL CAPS stamp that bled into paragraphs ("... the CONFIDENTIAL board approved ...")
    stamps = [
        re.compile(rf"(?<!\w){re.escape(s)}(?!\w)")
        for s in removed
        if s.isupper() and len(s) >= 4 and not _DIGITS.search(s)
    ]
    if stamps:
        kept = [
            el if el.kind == "table" else replace(el, text=_strip_inline(el.text, stamps))
            for el in kept
        ]
        kept = [el for el in kept if el.text]
    return replace(doc, elements=tuple(kept), removed=(*doc.removed, *removed))
