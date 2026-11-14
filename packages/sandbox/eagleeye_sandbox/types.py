from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Mode = Literal["sql", "python", "notebook"]
Status = Literal["ok", "error", "timeout", "oom", "unavailable"]

MAX_RESULT_ROWS = 100_000
MAX_RESULT_TABLES = 3
# notebook mode (company users): several cells, plots captured by the runner
MAX_NOTEBOOK_CELLS = 8
MAX_NOTEBOOK_TABLES = 20
MAX_FIGURES = 12
MAX_FIGURE_BYTES = 400_000


class CodeRejected(Exception):  # noqa: N818 — reads naturally: `except CodeRejected`
    """Static check failed. `user_message` is safe to show and to feed back to the model."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(f"{code}: {user_message}")
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class SandboxInput:
    name: str  # table / dict key the code sees, e.g. "ds_1"
    parquet: bytes
    columns: tuple[dict[str, str], ...] = ()  # [{name, type}] for the SQL check


@dataclass(frozen=True)
class SandboxTask:
    mode: Mode
    code: str
    inputs: tuple[SandboxInput, ...]
    max_rows: int = MAX_RESULT_ROWS
    max_tables: int = MAX_RESULT_TABLES
    cells: tuple[str, ...] = ()  # notebook mode: run in order in one shared namespace


@dataclass(frozen=True)
class ResultTable:
    name: str
    parquet: bytes
    columns: tuple[dict[str, str], ...]
    row_count: int
    truncated: bool


@dataclass(frozen=True)
class Figure:
    name: str  # e.g. "fig_2_1": cell 2, first figure
    png: bytes
    cell: int


@dataclass(frozen=True)
class CellOutput:
    index: int
    stdout: str = ""
    tables: tuple[str, ...] = ()  # names of tables saved by this cell
    stats: dict[str, Any] = field(default_factory=dict)  # stats saved by this cell
    figures: tuple[str, ...] = ()  # names of figures this cell produced
    error: str = ""
    note: str = ""  # e.g. a cap that was reached


@dataclass(frozen=True)
class SandboxResult:
    status: Status
    error: str = ""
    error_type: str = ""
    tables: tuple[ResultTable, ...] = ()
    stats: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    duration_ms: int = 0
    cells: tuple[CellOutput, ...] = ()  # notebook mode
    figures: tuple[Figure, ...] = ()
    failed_cell: int | None = None  # notebook mode: the cell that raised


class AnalysisExecutor(Protocol):
    """Runs one task in isolation. Local: Docker container. Cloud: Lambda (later)."""

    async def available(self) -> bool: ...

    async def run(self, task: SandboxTask) -> SandboxResult: ...
