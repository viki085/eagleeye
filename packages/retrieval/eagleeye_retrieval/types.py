from dataclasses import dataclass, field

ALL_SCOPES: tuple[str, ...] = ("enterprise", "personal")


@dataclass(frozen=True)
class AccessScope:
    """Who is asking and (optionally) which documents / scopes they narrowed to.

    `user_id` always comes from the authenticated run, never from model output.
    """

    user_id: str
    doc_ids: tuple[str, ...] | None = None
    scopes: tuple[str, ...] = ALL_SCOPES

    @property
    def restricts_scope(self) -> bool:
        return set(self.scopes) != set(ALL_SCOPES)

    def includes(self, scope: str) -> bool:
        return scope in self.scopes


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
    element_type: str = "text"  # "text" | "table" (stored in the Qdrant payload)


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
    element_type: str = "text"  # "text" | "table" | "image"
    asset_key: str | None = None  # figures: the stored picture (shown to the answer model)


@dataclass(frozen=True)
class RetrievalResult:
    chunks: tuple[RetrievedChunk, ...] = ()
    low_relevance: bool = True
    queries: tuple[str, ...] = field(default_factory=tuple)
    best_score: float = 0.0
