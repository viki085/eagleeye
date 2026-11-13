from dataclasses import asdict, dataclass, field
from typing import Any, Literal

UI_PREVIEW_ROWS = 10

OutcomeStatus = Literal["ok", "no_access", "clarify", "failed"]


@dataclass(frozen=True)
class GatewayResult:
    ok: bool
    artifact_id: str = ""
    sql: str = ""
    columns: tuple[dict[str, str], ...] = ()
    row_count: int = 0
    truncated: bool = False
    preview: tuple[tuple[Any, ...], ...] = ()
    duration_ms: int = 0
    code: str = ""
    error: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class ArtifactRef:
    """What the UI card and the persisted message part show."""

    artifact_id: str
    title: str
    sql: str
    source: str
    columns: tuple[dict[str, str], ...]
    row_count: int
    truncated: bool
    preview: tuple[tuple[Any, ...], ...]  # first UI_PREVIEW_ROWS rows (user is authorised)
    assumptions: str = ""
    mode: str = "sql"  # code shown in the card: sql (warehouse) | duckdb | python

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = "table"
        data["columns"] = list(self.columns)
        data["preview"] = [list(r) for r in self.preview]
        return data


@dataclass(frozen=True)
class SqlOutcome:
    status: OutcomeStatus
    message: str = ""  # for no_access / clarify / failed
    artifact: ArtifactRef | None = None
    llm_preview: tuple[tuple[Any, ...], ...] = ()  # masked rows for the model
    attempts: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)
