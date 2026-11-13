"""Fakes for the analysis sub-agent and chart tool: owner-scoped workspace, scripted sandbox."""

import io
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from eagleeye_agents.analysis.types import LoadedInput
from eagleeye_sandbox.types import ResultTable, SandboxResult, SandboxTask

REVENUE_ID = "11111111-1111-1111-1111-111111111111"
TARGETS_ID = "22222222-2222-2222-2222-222222222222"
FOREIGN_ID = "33333333-3333-3333-3333-333333333333"


def parquet(table: dict) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table(table), buf)
    return buf.getvalue()


def columns_of(data: bytes) -> tuple[dict[str, str], ...]:
    return tuple({"name": f.name, "type": str(f.type)} for f in pq.read_schema(io.BytesIO(data)))


MONTHS = [date(2026, m, 1) for m in (1, 2, 3)]
REVENUE = parquet({"month": MONTHS, "revenue": [100.0, 80.0, 130.0]})
TARGETS = parquet({"month": MONTHS, "target": [90.0, 100.0, 120.0], "owner_email": ["a@x.com"] * 3})
RESULT = parquet(
    {
        "month": MONTHS,
        "revenue": [100.0, 80.0, 130.0],
        "target": [90.0, 100.0, 120.0],
        "below_target": [False, True, False],
        "owner_email": ["a@x.com"] * 3,
    }
)


def analysis_draft(
    code: str = "SELECT r.month, r.revenue, t.target, r.revenue < t.target AS below_target "
    "FROM ds_1 r JOIN ds_2 t ON r.month = t.month ORDER BY r.month",
    mode: str = "sql",
    **kw: str,
) -> str:
    return json.dumps(
        {
            "mode": mode,
            "code": code,
            "assumptions": "joined on month",
            "title": "Revenue vs target",
            "clarification": "",
            "unavailable": "",
            **kw,
        }
    )


def ok_table(data: bytes = RESULT, name: str = "result") -> SandboxResult:
    count = pq.read_metadata(io.BytesIO(data)).num_rows
    return SandboxResult(
        "ok", tables=(ResultTable(name, data, columns_of(data), count, False),), duration_ms=900
    )


@dataclass
class FakeExecutor:
    results: list[SandboxResult] = field(default_factory=lambda: [ok_table()])
    tasks: list[SandboxTask] = field(default_factory=list)
    up: bool = True

    async def available(self) -> bool:
        return self.up

    async def run(self, task: SandboxTask) -> SandboxResult:
        self.tasks.append(task)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


@dataclass
class FakeWorkspace:
    owner: str = "u1"
    saved: list[dict[str, Any]] = field(default_factory=list)
    logged: list[dict[str, Any]] = field(default_factory=list)
    runs_last_hour: int = 0

    def _items(self) -> dict[str, LoadedInput]:
        return {
            REVENUE_ID: LoadedInput(
                REVENUE_ID, "result", "Monthly revenue", REVENUE, columns_of(REVENUE), 3
            ),
            TARGETS_ID: LoadedInput(
                TARGETS_ID,
                "dataset",
                "targets",
                TARGETS,
                columns_of(TARGETS),
                3,
                frozenset({"owner_email"}),
                {"row_count": 3, "column_count": 3, "duplicate_rows": 0, "columns": []},
            ),
        }

    async def list_datasets(self, user_id: str) -> list:
        return []

    async def load(self, user_id: str, ref_id: str) -> LoadedInput | None:
        if user_id != self.owner:
            return None
        return self._items().get(ref_id)  # FOREIGN_ID: someone else's → None

    async def save_result(self, **kw: Any) -> str:
        self.saved.append(kw)
        return f"art-{len(self.saved)}"

    async def sandbox_runs_last_hour(self, user_id: str) -> int:
        return self.runs_last_hour

    async def log_sandbox_run(self, **kw: Any) -> None:
        self.logged.append(kw)


def enable_analysis(
    ctx: Any, executor: FakeExecutor | None = None, workspace: FakeWorkspace | None = None
) -> FakeExecutor:
    ctx.executor = executor or FakeExecutor()
    ctx.workspace = workspace or FakeWorkspace()
    ctx.analysis_available = True
    return ctx.executor
