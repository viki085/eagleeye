"""Map `[n]` markers in an answer back to the sources that were in context."""

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from eagleeye_retrieval.types import RetrievedChunk

SNIPPET_CHARS = 240
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

    def to_dict(self) -> dict:
        data = asdict(self)
        data["heading_path"] = list(self.heading_path)
        return data


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET_CHARS else flat[: SNIPPET_CHARS - 1].rstrip() + "…"


def cited_numbers(answer: str, n_sources: int) -> list[int]:
    """In-range source numbers in order of first appearance, deduplicated."""
    seen: list[int] = []
    for match in _MARKER.finditer(answer):
        for raw in match.group(1).split(","):
            n = int(raw.strip())
            if 1 <= n <= n_sources and n not in seen:
                seen.append(n)
    return seen


def extract(answer: str, sources: Sequence[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            n=n,
            document_id=sources[n - 1].document_id,
            chunk_id=sources[n - 1].chunk_id,
            title=sources[n - 1].title,
            page=sources[n - 1].page,
            heading_path=sources[n - 1].heading_path,
            scope=sources[n - 1].scope,
            snippet=_snippet(sources[n - 1].content),
        )
        for n in cited_numbers(answer, len(sources))
    ]
