from dataclasses import dataclass, field
from typing import Any, Literal

from eagleeye_agents.sql.types import ArtifactRef

AnalysisStatus = Literal["ok", "no_access", "clarify", "failed"]
InputKind = Literal["dataset", "result"]


@dataclass(frozen=True)
class LoadedInput:
    """A table the user owns: an uploaded data file or an earlier result table."""

    ref_id: str
    kind: InputKind
    title: str
    parquet: bytes
    columns: tuple[dict[str, str], ...]
    row_count: int
    pii_columns: frozenset[str] = frozenset()  # lower-case names hidden from the model
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisOutcome:
    status: AnalysisStatus
    message: str = ""  # for no_access / clarify / failed
    artifacts: tuple[ArtifactRef, ...] = ()
    llm_previews: tuple[tuple[tuple[Any, ...], ...], ...] = ()  # masked rows per artifact
    stats: dict[str, Any] = field(default_factory=dict)
    mode: str = ""
    code: str = ""
    assumptions: str = ""
    attempts: int = 0
