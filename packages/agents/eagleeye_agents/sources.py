"""Run-level source numbering: each distinct chunk gets one stable [n] across all tool calls."""

import re
from dataclasses import asdict, dataclass

from eagleeye_retrieval.types import RetrievedChunk

SNIPPET_CHARS = 240
PATH_SEP = " › "
_MARKER = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")


@dataclass(frozen=True)
class Citation:
    n: int
    document_id: str
    chunk_id: str
    title: str
    page: int | None
    heading_path: tuple[str, ...]
    scope: str
    snippet: str
    element_type: str = "text"  # "table" | "image": the answer shows the table or figure too

    def to_dict(self) -> dict:
        data = asdict(self)
        data["heading_path"] = list(self.heading_path)
        return data


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET_CHARS else flat[: SNIPPET_CHARS - 1].rstrip() + "…"


# "<" and characters a model may read as "<": fullwidth, small, angle brackets, HTML entities
_OPEN_BRACKET = r"(?:<|&lt;|&#0*60;|&#x0*3c;|\uff1c|\ufe64|\u2329|\u27e8|\u3008)"


def neutralise(text: str, tags: tuple[str, ...] = ("context", "tool_data")) -> str:
    """Stop untrusted text from opening/closing our delimiter tags, including look-alike
    brackets and HTML-escaped tags (indirect prompt injection)."""
    for tag in tags:
        text = re.sub(rf"{_OPEN_BRACKET}\s*(/?)\s*{tag}", rf"‹\1{tag}", text, flags=re.IGNORECASE)
    return text


def source_label(n: int, chunk: RetrievedChunk) -> str:
    label = f"[{n}] {PATH_SEP.join([chunk.title, *chunk.heading_path])}"
    return f"{label} (p. {chunk.page})" if chunk.page else label


def format_sources(numbered: list[tuple[int, RetrievedChunk]]) -> str:
    return "\n\n".join(
        f"{neutralise(source_label(n, c))}\n{neutralise(c.content)}" for n, c in numbered
    )


def cited_numbers(answer: str, valid: set[int]) -> list[int]:
    """Valid source numbers in order of first appearance, deduplicated."""
    seen: list[int] = []
    for match in _MARKER.finditer(answer):
        for raw in match.group(1).split(","):
            n = int(raw.strip())
            if n in valid and n not in seen:
                seen.append(n)
    return seen


def strip_invalid_markers(answer: str, valid: set[int]) -> str:
    def fix(match: re.Match[str]) -> str:
        nums = [int(x.strip()) for x in match.group(1).split(",")]
        kept = [str(n) for n in nums if n in valid]
        return f"[{', '.join(kept)}]" if kept else ""

    return _MARKER.sub(fix, answer)


class SourceRegistry:
    def __init__(self) -> None:
        self._by_chunk: dict[str, int] = {}
        self._chunks: dict[int, RetrievedChunk] = {}

    def register(self, chunk: RetrievedChunk) -> int:
        n = self._by_chunk.get(chunk.chunk_id)
        if n is None:
            n = len(self._chunks) + 1
            self._by_chunk[chunk.chunk_id] = n
            self._chunks[n] = chunk
        return n

    def register_all(self, chunks: tuple[RetrievedChunk, ...]) -> list[tuple[int, RetrievedChunk]]:
        return [(self.register(c), c) for c in chunks]

    @property
    def numbers(self) -> set[int]:
        return set(self._chunks)

    def __len__(self) -> int:
        return len(self._chunks)

    def texts(self) -> list[str]:
        return [c.content for c in self._chunks.values()]

    def scopes(self) -> set[str]:
        """Scopes of every chunk shown to the model in this run (cited or not)."""
        return {c.scope for c in self._chunks.values()}

    def citations_for(self, answer: str) -> list[Citation]:
        out: list[Citation] = []
        for n in cited_numbers(answer, self.numbers):
            c = self._chunks[n]
            out.append(
                Citation(
                    n,
                    c.document_id,
                    c.chunk_id,
                    c.title,
                    c.page,
                    c.heading_path,
                    c.scope,
                    _snippet(c.content),
                    c.element_type,
                )
            )
        return out
