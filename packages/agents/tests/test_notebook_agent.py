"""Notebook mode: write cells → check → run in one sandbox session → repair one failing cell →
save tables, figures and the notebook; summarise for the planner with grounded numbers."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
from analysis_fakes import TARGETS_ID, FakeExecutor, enable_analysis
from eagleeye_agents.notebook.agent import MAX_REPAIRS, run_notebook_agent
from eagleeye_sandbox.types import (
    MAX_NOTEBOOK_TABLES,
    CellOutput,
    Figure,
    ResultTable,
    SandboxResult,
)
from fakes import CutOff, FakeLLM, make_ctx

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
GOAL = "explore the targets file in depth"


def draft(*cells: tuple[str, str], title: str = "Targets EDA") -> str:
    return json.dumps({"title": title, "cells": [{"purpose": p, "code": c} for p, c in cells]})


def repair(code: str) -> str:
    return json.dumps({"code": code})


CELLS = (
    ("Overview and missing values", "df = datasets['ds_1']\nprint(df.shape)"),
    ("Target by month", "save_table('by_month', df)\nsave_stat('rows', len(df))"),
    ("Distribution", "fig, ax = plt.subplots()\nax.hist(df['target'])"),
)


def table() -> ResultTable:
    buf = pa.BufferOutputStream()
    pq.write_table(pa.table({"month": ["2026-01"], "target": [100.0]}), buf)
    return ResultTable(
        "by_month",
        buf.getvalue().to_pybytes(),
        ({"name": "month", "type": "string"}, {"name": "target", "type": "double"}),
        1,
        False,
    )


def ok_run() -> SandboxResult:
    return SandboxResult(
        "ok",
        tables=(table(),),
        stats={"rows": 3},
        cells=(
            CellOutput(0, stdout="(3, 3)\n"),
            CellOutput(1, tables=("by_month",), stats={"rows": 3}),
            CellOutput(2, figures=("fig_2_1",)),
        ),
        figures=(Figure("fig_2_1", PNG, 2),),
    )


def failed_at(index: int) -> SandboxResult:
    cells = tuple(CellOutput(i) for i in range(index)) + (
        CellOutput(index, error="KeyError: 'targett'"),
    )
    return SandboxResult(
        "error", error=f"Cell {index}: KeyError: 'targett'", cells=cells, failed_cell=index
    )


def setup(llm: FakeLLM, executor: FakeExecutor | None = None):  # noqa: ANN201
    ctx, sink, _ = make_ctx(llm)
    ex = enable_analysis(ctx, executor or FakeExecutor([ok_run()]))
    ctx.notebook_executor = ex
    return ctx, sink, ex


async def test_happy_path_runs_all_cells_once_and_saves_the_notebook() -> None:
    llm = FakeLLM([draft(*CELLS)])
    ctx, _, executor = setup(llm)
    outcome = await run_notebook_agent(ctx, GOAL, [TARGETS_ID], "parent")
    assert outcome.status == "ok", outcome.message
    (task,) = executor.tasks
    assert task.mode == "notebook" and len(task.cells) == 3
    assert task.max_tables == MAX_NOTEBOOK_TABLES and [i.name for i in task.inputs] == ["ds_1"]
    (saved,) = ctx.workspace.notebooks
    assert saved["figures"] == [("fig_2_1", PNG)] and saved["title"] == "Targets EDA"
    manifest = saved["manifest"]
    assert [c["purpose"] for c in manifest["cells"]] == [p for p, _ in CELLS]
    assert manifest["cells"][1]["tables"][0]["title"] == "by_month"
    assert ctx.workspace.saved[0]["source_refs"]["notebook_id"] == saved["notebook_id"]
    payload = outcome.notebook
    assert payload["notebook_id"] == saved["notebook_id"] and payload["figure_count"] == 1
    assert "Target by month" in outcome.summary and '"rows": 3' in outcome.summary
    assert 3.0 in outcome.evidence and 100.0 in outcome.evidence


async def test_a_failing_cell_is_repaired_and_the_notebook_runs_again() -> None:
    llm = FakeLLM([draft(*CELLS), repair("save_table('by_month', df)\nsave_stat('rows', 3)")])
    ctx, _, executor = setup(llm, FakeExecutor([failed_at(1), ok_run()]))
    outcome = await run_notebook_agent(ctx, GOAL, [TARGETS_ID], None)
    assert outcome.status == "ok" and len(executor.tasks) == 2
    repair_prompt = llm.complete_calls[1][1].content
    assert "KeyError: 'targett'" in repair_prompt and "Target by month" in repair_prompt
    assert executor.tasks[1].cells[1] == "save_table('by_month', df)\nsave_stat('rows', 3)"
    assert executor.tasks[1].cells[0] == executor.tasks[0].cells[0]  # other cells untouched


async def test_repairs_are_capped_and_a_partial_notebook_is_kept() -> None:
    llm = FakeLLM([draft(*CELLS)] + [repair("still_broken()")] * MAX_REPAIRS)
    ctx, _, executor = setup(llm, FakeExecutor([failed_at(2)]))
    outcome = await run_notebook_agent(ctx, GOAL, [TARGETS_ID], None)
    assert len(executor.tasks) == 1 + MAX_REPAIRS
    assert outcome.status == "partial" and "Cell 2" in outcome.message
    assert ctx.workspace.notebooks  # the cells that worked are still shown


async def test_a_cell_rejected_by_the_checks_is_repaired_before_running() -> None:
    bad = ("Read a file", "open('/etc/passwd').read()")
    llm = FakeLLM([draft(CELLS[0], bad), repair("print(df.columns.tolist())")])
    ctx, _, executor = setup(llm)
    outcome = await run_notebook_agent(ctx, GOAL, [TARGETS_ID], None)
    assert outcome.status == "ok"
    assert "open" in llm.complete_calls[1][1].content
    assert all("open(" not in c for t in executor.tasks for c in t.cells)


async def test_a_cut_off_notebook_is_rewritten_shorter() -> None:
    llm = FakeLLM(
        [CutOff('{"title": "EDA", "cells": [{"purpose": "x", "code": "a ='), draft(*CELLS)]
    )
    ctx, _, _ = setup(llm)
    outcome = await run_notebook_agent(ctx, GOAL, [TARGETS_ID], None)
    assert outcome.status == "ok"
    assert "cut off" in llm.complete_calls[1][1].content


async def test_too_many_cells_are_trimmed_to_the_limit() -> None:
    from eagleeye_sandbox.types import MAX_NOTEBOOK_CELLS

    many = [(f"Step {i}", f"x{i} = {i}") for i in range(MAX_NOTEBOOK_CELLS + 4)]
    llm = FakeLLM([draft(*many)])
    ctx, _, executor = setup(llm)
    await run_notebook_agent(ctx, GOAL, [TARGETS_ID], None)
    assert len(executor.tasks[0].cells) == MAX_NOTEBOOK_CELLS
