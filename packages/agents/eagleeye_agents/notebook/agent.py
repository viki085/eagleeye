"""The notebook agent (docs/notebook-eda-plan.md): one model call writes an analyst-style
notebook, every cell is checked, all cells run in ONE sandbox session, and a failing cell is
rewritten on its own (at most MAX_REPAIRS times). Tables, figures and the notebook are saved
for the user; the planner gets a masked text summary whose numbers count as evidence.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from eagleeye_llm.gateway import ChatMessage
from eagleeye_sandbox.types import MAX_NOTEBOOK_TABLES, SandboxResult, SandboxTask

from eagleeye_agents.analysis.agent import _load_inputs as load_inputs
from eagleeye_agents.analysis.inputs import describe, pii_for_results, sandbox_inputs
from eagleeye_agents.analysis.types import LoadedInput
from eagleeye_agents.context import RunContext
from eagleeye_agents.notebook.draft import (
    NotebookDraft,
    first_rejected,
    parse_notebook,
    parse_repair,
)
from eagleeye_agents.notebook.save import save_notebook

MAX_WRITE_ATTEMPTS = 2
MAX_REPAIRS = 2  # so at most 3 sandbox runs per notebook
NOTEBOOK_MAX_TOKENS = 7000
REPAIR_MAX_TOKENS = 2500
UNAVAILABLE = "Notebook analysis is not available right now."
NO_INPUTS = "None of the given inputs are available to you. Use list_datasets to see them."
QUOTA = "The hourly analysis limit has been reached. Try again later."
CUT_OFF = (
    "Your last reply was cut off at the length limit before the JSON was complete. Write a "
    "shorter notebook: fewer cells (5-6), compact code, no long printouts."
)
BAD_JSON = "Your last reply was not valid JSON. Return only the JSON object."

NotebookStatus = Literal["ok", "partial", "failed", "no_access"]


@dataclass(frozen=True)
class NotebookOutcome:
    status: NotebookStatus
    message: str = ""
    notebook: dict[str, Any] | None = None  # the event / message-part payload
    summary: str = ""  # what the planner reads (personal data masked)
    evidence: list[float] = field(default_factory=list)


Parse = Callable[[str], tuple[Any, str]]  # raw reply -> (value, step summary); raises if unusable


async def _complete(
    ctx: RunContext,
    name: str,
    system: str,
    user: str,
    max_tokens: int,
    parent: str | None,
    parse: Parse,
) -> tuple[Any | None, bool]:
    """(parsed value or None, cut_off) for one model call. Parsing happens inside the step, so
    the step list shows what the call produced (or why it was unusable)."""
    async with ctx.steps.step("llm", name, user[:200], parent) as step:
        raw, usage = await ctx.llm.complete(
            "capable",
            [ChatMessage("system", system), ChatMessage("user", user)],
            max_tokens=max_tokens,
            json_mode=True,
            temperature=0,
        )
        ctx.usage.add(usage)
        step.usage = usage
        cut_off = usage.tokens_out >= max_tokens
        try:
            value, step.output_summary = parse(raw)
        except (ValueError, json.JSONDecodeError):
            step.status = "error"
            step.output_summary = "cut off: too long" if cut_off else "invalid JSON"
            return None, cut_off
        return value, cut_off


def _parse_draft(raw: str) -> tuple[NotebookDraft, str]:
    draft = parse_notebook(raw)
    return draft, f"{len(draft.cells)} cells: {draft.title}"


async def _write(
    ctx: RunContext, system: str, goal: str, parent: str | None
) -> NotebookDraft | None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    feedback: list[str] = []
    for _ in range(MAX_WRITE_ATTEMPTS):
        if ctx.budget.breach(ctx.usage.cost_usd):
            return None
        user = f"Today's date: {today}\n\nGoal: {goal}"
        if feedback:
            user += "\n\nPrevious attempt: " + feedback[-1]
        draft, cut_off = await _complete(
            ctx, "write notebook", system, user, NOTEBOOK_MAX_TOKENS, parent, _parse_draft
        )
        if draft is not None:
            return draft
        feedback.append(CUT_OFF if cut_off else BAD_JSON)
    return None


async def _repair(
    ctx: RunContext,
    draft: NotebookDraft,
    index: int,
    problem: str,
    parent: str | None,
) -> NotebookDraft:
    """Rewrites one cell; the draft is returned unchanged if the rewrite is unusable."""
    if ctx.budget.breach(ctx.usage.cost_usd):
        return draft
    earlier = "\n\n".join(
        f"# Cell {i}: {c.purpose}\n{c.code}" for i, c in enumerate(draft.cells[:index])
    )
    cell = draft.cells[index]
    user = (
        f"Earlier cells (already run, their variables exist):\n{earlier or '(none)'}\n\n"
        f"Cell {index} to fix — {cell.purpose}:\n{cell.code}\n\nProblem: {problem}"
    )
    code, _ = await _complete(
        ctx,
        "fix notebook cell",
        ctx.prompts.text("notebook_repair"),
        user,
        REPAIR_MAX_TOKENS,
        parent,
        lambda raw: (parse_repair(raw), f"cell {index + 1} rewritten"),
    )
    return draft if code is None else draft.with_cell(index, code)


async def _execute(
    ctx: RunContext, draft: NotebookDraft, named: list[tuple[str, LoadedInput]], parent: str | None
) -> SandboxResult:
    code = "\n\n".join(f"# Cell {i}: {c.purpose}\n{c.code}" for i, c in enumerate(draft.cells))
    async with ctx.steps.step("tool", "run notebook", f"{len(draft.cells)} cells", parent) as step:
        task = SandboxTask(
            "notebook",
            "",
            sandbox_inputs(named),
            max_tables=MAX_NOTEBOOK_TABLES,
            cells=tuple(c.code for c in draft.cells),
        )
        result = await ctx.notebook_executor.run(task)
        await ctx.workspace.log_sandbox_run(
            run_id=ctx.run_id,
            user_id=ctx.user_id,
            mode="python",
            code=code,
            status="ok"
            if result.status == "ok"
            else ("timeout" if result.status == "timeout" else "error"),
            duration_ms=result.duration_ms,
            error=result.error or None,
        )
        ctx.python_runs += 1
        if result.status == "ok":
            step.output_summary = (
                f"{len(result.cells)} cells · {len(result.figures)} figures · "
                f"{len(result.tables)} tables · {result.duration_ms} ms"
            )
        else:
            step.status, step.output_summary = "error", f"{result.status}: {result.error}"
    return result


async def _run_with_repairs(
    ctx: RunContext, draft: NotebookDraft, named: list[tuple[str, LoadedInput]], parent: str | None
) -> tuple[NotebookDraft, SandboxResult | None, str]:
    """(final draft, last run result or None, problem). Repairs both rejected and failing cells."""
    repairs = 0
    result: SandboxResult | None = None
    while True:
        rejected = first_rejected(draft)
        if rejected is not None:
            if repairs >= MAX_REPAIRS:
                return draft, result, f"Cell {rejected[0]}: {rejected[1]}"
            repairs += 1
            draft = await _repair(ctx, draft, rejected[0], rejected[1], parent)
            continue
        if await ctx.workspace.sandbox_runs_last_hour(ctx.user_id) >= ctx.sandbox_runs_per_hour:
            return draft, None, QUOTA
        result = await _execute(ctx, draft, named, parent)
        if result.status == "ok":
            return draft, result, ""
        if result.failed_cell is None or repairs >= MAX_REPAIRS:
            return draft, result, result.error
        repairs += 1
        error = result.cells[-1].error if result.cells else result.error
        draft = await _repair(ctx, draft, result.failed_cell, error, parent)


async def run_notebook_agent(
    ctx: RunContext, goal: str, input_ids: list[str], parent: str | None
) -> NotebookOutcome:
    if ctx.notebook_executor is None or ctx.workspace is None:
        return NotebookOutcome("no_access", UNAVAILABLE)
    named = await load_inputs(ctx, input_ids, parent)
    if not named:
        return NotebookOutcome("no_access", NO_INPUTS)
    tables = "\n\n".join(describe(n, i) for n, i in named)
    system = f"{ctx.prompts.text('notebook_generate')}\n\nINPUT TABLES\n{tables}"
    draft = await _write(ctx, system, goal, parent)
    if draft is None:
        return NotebookOutcome("failed", "The notebook could not be written. Try a narrower goal.")
    draft, result, problem = await _run_with_repairs(ctx, draft, named, parent)
    if result is None or not result.cells:
        return NotebookOutcome("failed", problem or UNAVAILABLE)
    saved = await save_notebook(
        ctx, str(uuid.uuid4()), draft, result, named, pii_for_results(named)
    )
    status: NotebookStatus = "ok" if result.status == "ok" else "partial"
    summary = saved.summary
    if status == "partial":
        summary = f"The notebook stopped early: {problem}\n" + summary
    return NotebookOutcome(status, problem, saved.payload, summary, saved.evidence)
