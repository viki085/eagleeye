from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccessScope:
    """Who is asking and (optionally) which documents they narrowed to."""

    user_id: str
    doc_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    score: float  # cosine similarity, higher is better


@dataclass(frozen=True)
class VectorPoint:
    chunk_id: str
    document_id: str
    chunk_no: int
    vector: list[float]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    title: str
    scope: str
    chunk_no: int
    page: int | None
    heading_path: tuple[str, ...]
    content: str
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    chunks: tuple[RetrievedChunk, ...] = ()
    low_relevance: bool = True
    queries: tuple[str, ...] = field(default_factory=tuple)
    best_score: float = 0.0
