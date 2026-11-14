"""Saving a finished notebook: tables as normal result tables, figures as PNGs, the manifest as
a notebook artifact. Also builds the planner's summary, with personal data masked."""

import io
import json
from dataclasses import dataclass
from typing import Any

import pyarrow.parquet as pq
from eagleeye_datasets.values import jsonable
from eagleeye_sandbox.types import CellOutput, ResultTable, SandboxResult

from eagleeye_agents.analysis.types import LoadedInput
from eagleeye_agents.checks.numbers import numbers_in
from eagleeye_agents.context import RunContext
from eagleeye_agents.notebook.draft import NotebookDraft
from eagleeye_agents.sql.preview import masked_preview
from eagleeye_agents.sql.types import UI_PREVIEW_ROWS

MODEL_PREVIEW_ROWS = 10
MAX_STDOUT_FOR_MODEL = 600
MAX_SUMMARY_CHARS = 9000


@dataclass(frozen=True)
class Saved:
    payload: dict[str, Any]
    summary: str
    evidence: list[float]


def _rows(table: ResultTable, n: int) -> list[list[Any]]:
    data = pq.read_table(io.BytesIO(table.parquet)).slice(0, n).to_pylist()
    return [[jsonable(v) for v in r.values()] for r in data]


async def _save_tables(
    ctx: RunContext,
    notebook_id: str,
    draft: NotebookDraft,
    result: SandboxResult,
    named: list[tuple[str, LoadedInput]],
) -> dict[str, dict[str, Any]]:
    """name -> {artifact_id, title, row_count, columns, preview}; preview is the user view."""
    inputs = [{"name": n, "id": i.ref_id, "title": i.title} for n, i in named]
    saved: dict[str, dict[str, Any]] = {}
    for table in result.tables:
        artifact_id = await ctx.workspace.save_result(
            user_id=ctx.user_id,
            run_id=ctx.run_id,
            title=f"{draft.title} — {table.name.replace('_', ' ')}",
            parquet=table.parquet,
            columns=list(table.columns),
            row_count=table.row_count,
            truncated=table.truncated,
            source_refs={"mode": "notebook", "notebook_id": notebook_id, "inputs": inputs},
        )
        saved[table.name] = {
            "artifact_id": artifact_id,
            "title": table.name,
            "row_count": table.row_count,
            "columns": list(table.columns),
            "preview": _rows(table, UI_PREVIEW_ROWS),
        }
    return saved


def _cell(i: int, draft: NotebookDraft, out: CellOutput | None, tables: dict) -> dict[str, Any]:
    cell = draft.cells[i]
    if out is None:
        return {
            "index": i,
            "purpose": cell.purpose,
            "code": cell.code,
            "status": "not run",
            "stdout": "",
            "error": "",
            "note": "",
            "stats": {},
            "figures": [],
            "tables": [],
        }
    return {
        "index": i,
        "purpose": cell.purpose,
        "code": cell.code,
        "status": "error" if out.error else "ok",
        "stdout": out.stdout,
        "error": out.error,
        "note": out.note,
        "stats": out.stats,
        "figures": list(out.figures),
        "tables": [tables[n] for n in out.tables if n in tables],
    }


def _summary(
    draft: NotebookDraft,
    result: SandboxResult,
    cells: list[dict[str, Any]],
    hidden: set[str],
) -> tuple[str, list[float]]:
    by_name = {t.name: t for t in result.tables}
    lines = [
        f"Notebook '{draft.title}' is shown to the user under your answer: "
        f"{len(cells)} cells with their code, tables and {len(result.figures)} figures. "
        "Summarise the findings for the user; quote numbers only from the outputs below. "
        "*** marks personal data hidden from you but visible to the user."
    ]
    evidence: list[float] = []
    for c in cells:
        lines.append(f"\n## Cell {c['index']}: {c['purpose']} ({c['status']})")
        if c["stdout"]:
            out = c["stdout"][:MAX_STDOUT_FOR_MODEL]
            lines.append("Output:\n" + out)
            evidence.extend(numbers_in([out]))
        if c["stats"]:
            lines.append("Stats: " + json.dumps(c["stats"], default=str))
            evidence.extend(numbers_in(_flatten(c["stats"])))
        for t in c["tables"]:
            table = by_name[t["title"]]
            rows = masked_preview(table.columns, _rows(table, MODEL_PREVIEW_ROWS), hidden)
            header = " | ".join(col["name"] for col in table.columns)
            body = "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in rows)
            lines.append(f"Table {t['title']} ({table.row_count} rows):\n{header}\n{body}")
            evidence.extend(numbers_in(v for r in rows for v in r))
            evidence.append(float(table.row_count))
        if c["figures"]:
            lines.append(f"Figures: {len(c['figures'])} (shown to the user)")
        if c["error"]:
            lines.append(f"Error: {c['error']}")
        if c["note"]:
            lines.append(f"Note: {c['note']}")
    return "\n".join(lines)[:MAX_SUMMARY_CHARS], evidence


def _flatten(value: object) -> list[object]:
    if isinstance(value, dict):
        return [x for v in value.values() for x in _flatten(v)]
    if isinstance(value, list):
        return [x for v in value for x in _flatten(v)]
    return [value]


async def save_notebook(
    ctx: RunContext,
    notebook_id: str,
    draft: NotebookDraft,
    result: SandboxResult,
    named: list[tuple[str, LoadedInput]],
    hidden: set[str],
) -> Saved:
    tables = await _save_tables(ctx, notebook_id, draft, result, named)
    outputs = {c.index: c for c in result.cells}
    cells = [_cell(i, draft, outputs.get(i), tables) for i in range(len(draft.cells))]
    manifest = {
        "notebook_id": notebook_id,
        "title": draft.title,
        "inputs": [{"name": n, "title": i.title} for n, i in named],
        "cells": cells,
    }
    await ctx.workspace.save_notebook(
        notebook_id=notebook_id,
        user_id=ctx.user_id,
        run_id=ctx.run_id,
        title=draft.title,
        manifest=manifest,
        figures=[(f.name, f.png) for f in result.figures],
    )
    summary, evidence = _summary(draft, result, cells, hidden)
    payload = {**manifest, "figure_count": len(result.figures), "status": result.status}
    return Saved(payload, summary, evidence)
