"""The runner's input spec and result parsing, shared by every executor (Docker, Lambda).

The runner writes result.json plus one file per table (.parquet) and figure (.png). An
executor only supplies a way to read those files; everything here treats them as untrusted:
file names are reduced to their basename, sizes are capped, PNGs are checked by signature.
"""

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from eagleeye_sandbox.types import (
    MAX_FIGURE_BYTES,
    MAX_FIGURES,
    CellOutput,
    Figure,
    ResultTable,
    SandboxResult,
    SandboxTask,
)

MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MAX_ERROR_CHARS = 800
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FAILED = "The analysis sandbox could not run this task."
TOO_LARGE = "The result is too large; aggregate or filter it."

ReadFile = Callable[[str], bytes | None]  # basename -> bytes, or None when missing


def task_spec(task: SandboxTask, inputs: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "mode": task.mode,
        "code": task.code,
        "cells": list(task.cells),
        "inputs": inputs,
        "max_rows": task.max_rows,
        "max_tables": task.max_tables,
        "max_figures": MAX_FIGURES,
        "max_figure_bytes": MAX_FIGURE_BYTES,
    }


def _basename(value: object) -> str:
    return PurePosixPath(str(value).replace("\\", "/")).name


class _Budget:
    def __init__(self) -> None:
        self.used = 0

    def take(self, data: bytes) -> bool:
        self.used += len(data)
        return self.used <= MAX_OUTPUT_BYTES


def _tables(body: dict, read: ReadFile, budget: _Budget) -> tuple[ResultTable, ...] | None:
    out: list[ResultTable] = []
    for item in body.get("tables", []):
        data = read(_basename(item.get("file", "")))
        if data is None:
            continue
        if not budget.take(data):
            return None
        out.append(
            ResultTable(
                name=str(item["name"]),
                parquet=data,
                columns=tuple(item.get("columns", [])),
                row_count=int(item.get("rows", 0)),
                truncated=bool(item.get("truncated")),
            )
        )
    return tuple(out)


def _figures(body: dict, read: ReadFile, budget: _Budget) -> tuple[Figure, ...] | None:
    out: list[Figure] = []
    for item in body.get("figures", [])[:MAX_FIGURES]:
        data = read(_basename(item.get("file", "")))
        if data is None or len(data) > MAX_FIGURE_BYTES or not data.startswith(PNG_SIGNATURE):
            continue  # only real PNGs within the cap are kept
        if not budget.take(data):
            return None
        out.append(Figure(str(item["name"]), data, int(item.get("cell", 0))))
    return tuple(out)


def _cells(body: dict) -> tuple[CellOutput, ...]:
    return tuple(
        CellOutput(
            index=int(c.get("index", i)),
            stdout=str(c.get("stdout", "")),
            tables=tuple(str(t) for t in c.get("tables", [])),
            stats=dict(c.get("stats", {})),
            figures=tuple(str(f) for f in c.get("figures", [])),
            error=str(c.get("error", ""))[:MAX_ERROR_CHARS],
            note=str(c.get("note", "")),
        )
        for i, c in enumerate(body.get("cells", []))
    )


def parse_result(body: dict, read: ReadFile, duration_ms: int) -> SandboxResult:
    """result.json (already decoded) + the output files -> SandboxResult."""
    budget = _Budget()
    tables = _tables(body, read, budget)
    figures = _figures(body, read, budget)
    if tables is None or figures is None:
        return SandboxResult("error", error=TOO_LARGE, duration_ms=duration_ms)
    failed = body.get("failed_cell")
    ok = body.get("status") == "ok"
    return SandboxResult(
        "ok" if ok else "error",
        error="" if ok else str(body.get("error", "The analysis failed."))[:MAX_ERROR_CHARS],
        error_type="" if ok else str(body.get("error_type", "")),
        tables=tables,
        stats=dict(body.get("stats", {})),
        stdout=str(body.get("stdout", "")),
        duration_ms=duration_ms,
        cells=_cells(body),
        figures=figures,
        failed_cell=int(failed) if isinstance(failed, int) else None,
    )
