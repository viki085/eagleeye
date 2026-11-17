"""CHUNKING stage: structure-aware packing (C4 §3.3).

- Headings build a stack → every chunk carries `heading_path`.
- A section that fits in `max_chars` is one chunk; longer sections are packed to
  `soft_chars` at paragraph → sentence → word boundaries, with `overlap` chars of
  carry-over only *inside* that section.
- Sections under `min_chars` are merged into the following section when the
  result still fits; the merged path is the common prefix and the dropped heading
  titles are kept inline as text.
- A table is never mixed with text: it is its own chunk (element_type "table"), and a
  table longer than `max_chars` is split by rows with its header row repeated in every
  part, so each part still says which column a number belongs to.
"""

import hashlib
import re
from dataclasses import dataclass
from itertools import takewhile

from ingest_worker.parsing.base import BBox, ParsedElement

# Chosen with the retrieval eval (config C, ADR-32): budgeted recall 0.86 vs 0.80 for the old
# 2400/3000 setting. The worker reads these from settings (CHUNK_* env vars).
MAX_CHARS = 1600
SOFT_CHARS = 1200
MIN_CHARS = 400
OVERLAP_CHARS = 200
MAX_HEADING_CHARS = 200
PATH_SEP = " › "
PARA_SEP = "\n\n"

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    chunk_no: int
    content: str
    heading_path: tuple[str, ...]
    page: int | None
    chunk_hash: str
    element_type: str = "text"  # "text" | "table" | "image"
    bbox: BBox | None = None  # tables and figures: position on the page
    table_html: str | None = None  # tables: the whole table's structure
    asset_key: str | None = None  # figures: the stored picture


@dataclass(frozen=True)
class _Block:
    text: str
    page: int | None
    bbox: BBox | None = None
    table_html: str | None = None
    asset_key: str | None = None
    kind: str = "text"


@dataclass(frozen=True)
class _Section:
    path: tuple[str, ...]
    blocks: tuple[_Block, ...]
    table: bool = False

    @property
    def size(self) -> int:
        return sum(len(b.text) for b in self.blocks) + len(PARA_SEP) * max(len(self.blocks) - 1, 0)


def _sections(elements: list[ParsedElement] | tuple[ParsedElement, ...]) -> list[_Section]:
    sections: list[_Section] = []
    stack: tuple[tuple[int, str], ...] = ()
    blocks: list[_Block] = []

    def path() -> tuple[str, ...]:
        return tuple(title for _, title in stack)

    for el in elements:
        text = el.text.strip()
        if not text:
            continue
        if el.heading_level is not None:
            if blocks:
                sections.append(_Section(path(), tuple(blocks)))
                blocks = []
            kept = tuple(s for s in stack if s[0] < el.heading_level)
            stack = (*kept, (el.heading_level, text[:MAX_HEADING_CHARS]))
        elif el.kind in ("table", "image"):  # each its own chunk, never mixed with text
            if blocks:
                sections.append(_Section(path(), tuple(blocks)))
                blocks = []
            block = _Block(text, el.page, el.bbox, el.table_html, el.asset_key, el.kind)
            sections.append(_Section(path(), (block,), table=True))
        else:
            blocks.append(_Block(text, el.page))
    if blocks:
        sections.append(_Section(path(), tuple(blocks)))
    return sections


def _common_prefix(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(x for x, _ in takewhile(lambda p: p[0] == p[1], zip(a, b, strict=False)))


def _with_inline_title(section: _Section, prefix: tuple[str, ...]) -> tuple[_Block, ...]:
    extra = section.path[len(prefix) :]
    if not extra:
        return section.blocks
    first_page = section.blocks[0].page if section.blocks else None
    return (_Block(PATH_SEP.join(extra), first_page), *section.blocks)


def _related(a: tuple[str, ...], b: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    """Only merge within one topic: a shared parent heading, or a doc with no headings.
    Never merge across top-level sections (e.g. "Returns" + "Shipping" in one chunk)."""
    return bool(prefix) or (not a and not b)


def _merge_tiny(sections: list[_Section], min_chars: int, max_chars: int) -> list[_Section]:
    out: list[_Section] = []
    carry: _Section | None = None
    for sec in sections:
        if sec.table:  # tables are never merged with text
            if carry is not None:
                out.append(carry)
                carry = None
            out.append(sec)
            continue
        if carry is not None:
            prefix = _common_prefix(carry.path, sec.path)
            merged = _Section(
                prefix, _with_inline_title(carry, prefix) + _with_inline_title(sec, prefix)
            )
            if _related(carry.path, sec.path, prefix) and merged.size <= max_chars:
                sec = merged
            else:
                out.append(carry)
            carry = None
        if sec.size < min_chars:
            carry = sec
        else:
            out.append(sec)
    if carry is not None:
        out.append(carry)
    return out


def _hard_split(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit)
        cut = cut if cut > limit // 2 else limit
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def _pieces(text: str, limit: int) -> list[str]:
    """Split one block to pieces ≤ limit at sentence, then word boundaries."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    buf = ""
    for sentence in _SENTENCE_END.split(text):
        for part in _hard_split(sentence, limit):
            candidate = f"{buf} {part}" if buf else part
            if len(candidate) <= limit:
                buf = candidate
            else:
                pieces.append(buf)
                buf = part
    if buf:
        pieces.append(buf)
    return pieces


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap * 2:
        return ""
    window = text[-overlap:]
    space = window.find(" ")
    return window[space + 1 :] if space >= 0 else window


def _pack(sec: _Section, soft: int, max_chars: int, overlap: int) -> list[tuple[str, int | None]]:
    if sec.size <= max_chars:
        return [(PARA_SEP.join(b.text for b in sec.blocks), sec.blocks[0].page)]

    units = [(p, b.page) for b in sec.blocks for p in _pieces(b.text, soft)]
    packed: list[tuple[str, int | None]] = []
    buf: list[str] = []
    page: int | None = None
    for text, pg in units:
        projected = sum(len(x) for x in buf) + len(PARA_SEP) * len(buf) + len(text)
        if buf and projected > soft:
            packed.append((PARA_SEP.join(buf), page))
            tail = _tail(packed[-1][0], overlap)
            buf = [tail] if tail else []
            page = None
        if page is None:
            page = pg
        buf.append(text)
    if buf:
        packed.append((PARA_SEP.join(buf), page))
    return packed


def _table_parts(markdown: str, max_chars: int) -> list[str]:
    """A Markdown table as parts of at most ~max_chars, each starting with the header row."""
    if len(markdown) <= max_chars:
        return [markdown]
    lines = markdown.splitlines()
    has_header = len(lines) > 2 and set(lines[1].replace("|", "").strip()) <= set("-: ")
    header = lines[:2] if has_header else []
    rows = lines[2:] if has_header else lines
    head = "\n".join(header)
    budget = max(max_chars - len(head) - 1, max_chars // 2)
    parts: list[str] = []
    buf: list[str] = []
    for row in rows:
        for piece in _hard_split(row, budget) if len(row) > budget else [row]:
            if buf and sum(len(r) + 1 for r in buf) + len(piece) > budget:
                parts.append("\n".join([*header, *buf]))
                buf = []
            buf.append(piece)
    if buf:
        parts.append("\n".join([*header, *buf]))
    return parts


def _hash(path: tuple[str, ...], content: str) -> str:
    return hashlib.sha256(f"{PATH_SEP.join(path)}\n{content}".encode()).hexdigest()


def chunk(
    elements: list[ParsedElement] | tuple[ParsedElement, ...],
    max_chars: int = MAX_CHARS,
    soft_chars: int = SOFT_CHARS,
    min_chars: int = MIN_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[Chunk]:
    if not soft_chars + overlap + len(PARA_SEP) <= max_chars:
        raise ValueError("soft_chars + overlap must fit within max_chars")
    sections = _merge_tiny(_sections(elements), min_chars, max_chars)
    chunks: list[Chunk] = []
    for sec in sections:
        if sec.table:
            t = sec.blocks[0]
            parts = (
                _table_parts(t.text, max_chars) if t.kind == "table" else _pieces(t.text, max_chars)
            )
            for content in parts:
                chunks.append(
                    Chunk(
                        len(chunks),
                        content,
                        sec.path,
                        t.page,
                        _hash(sec.path, content),
                        element_type=t.kind,
                        bbox=t.bbox,
                        table_html=t.table_html,
                        asset_key=t.asset_key,
                    )
                )
            continue
        for content, page in _pack(sec, soft_chars, max_chars, overlap):
            chunks.append(Chunk(len(chunks), content, sec.path, page, _hash(sec.path, content)))
    return chunks
