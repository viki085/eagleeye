"""The analysis sub-agent (C6 §3–4): ≤ 3 generations, ≤ 3 sandbox executions per call.

Steps nest under the tool call: load inputs → write code → check code → run in sandbox.
Inputs are owner-checked by the workspace; code runs only in the sandbox container.
"""

import io
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pyarrow.parquet as pq
from eagleeye_datasets.values import jsonable
from eagleeye_llm.gateway import ChatMessage
from eagleeye_sandbox.checks_python import check_python
from eagleeye_sandbox.checks_sql import check_sql
from eagleeye_sandbox.types import CodeRejected, SandboxResult, SandboxTask

from eagleeye_agents.analysis.inputs import (
    MAX_INPUTS,
    describe,
    pii_for_results,
    sandbox_inputs,
)
from eagleeye_agents.analysis.types import AnalysisOutcome, LoadedInput
from eagleeye_agents.context import RunContext
from eagleeye_agents.sql.preview import masked_preview
from eagleeye_agents.sql.types import UI_PREVIEW_ROWS, ArtifactRef

logger = logging.getLogger(__name__)

# Code-writing attempts per analyze_data call. They have their own cap and don't count toward
# the planner's steps, so one hard analysis can't use up the whole answer (cost and time limits
# still apply to every attempt).
MAX_GENERATIONS = 3
MAX_EXECUTIONS = 3
# Room for a complete script inside the JSON reply (code is escaped, so it costs more tokens).
# A reply that uses the whole allowance was cut off mid-way.
CODE_MAX_TOKENS = 4000
MAX_PYTHON_RUNS_PER_RUN = 3
MAX_STATS_FOR_MODEL = 40
DISABLED = "Data analysis is not available right now."
QUOTA = "The hourly analysis limit has been reached. Try again later."
NO_INPUTS = "None of the given inputs are available to you. Use list_datasets to see them."
PYTHON_OFF = "Python analysis is turned off; write DuckDB SQL instead."
CUT_OFF = (
    "Your last reply was cut off at the length limit before the JSON was complete: the code was "
    "too long. Write a shorter script that covers the most important part of the task (fewer "
    "steps, at most 3 small tables), and say in assumptions what was left out."
)
BAD_JSON = "Your last reply was not valid JSON. Return only the JSON object."
RETRY_HINT = {
    "timeout": "It took too long: aggregate earlier, filter, or sample the data.",
    "oom": "It ran out of memory: aggregate earlier or work on fewer columns.",
}
MODE_LABEL = {"sql": "DuckDB SQL", "python": "Python"}


@dataclass(frozen=True)
class Draft:
    mode: str
    code: str
    assumptions: str
    title: str
    clarification: str = ""
    unavailable: str = ""


def parse_draft(raw: str) -> Draft:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    mode = str(data.get("mode") or "sql").strip().lower()
    return Draft(
        mode="python" if mode == "python" else "sql",
        code=str(data.get("code") or "").strip(),
        assumptions=str(data.get("assumptions") or "").strip()[:500],
        title=str(data.get("title") or "Analysis result").strip()[:80],
        clarification=str(data.get("clarification") or "").strip()[:400],
        unavailable=str(data.get("unavailable") or "").strip()[:300],
    )


async def _load_inputs(
    ctx: RunContext, ids: list[str], parent: str | None
) -> list[tuple[str, LoadedInput]]:
    async with ctx.steps.step("retrieval", "load inputs", ", ".join(ids), parent) as step:
        named: list[tuple[str, LoadedInput]] = []
        seen: set[str] = set()
        for ref in ids[:MAX_INPUTS]:
            item = await ctx.workspace.load(ctx.user_id, ref)
            if item is None or item.ref_id in seen:
                continue
            seen.add(item.ref_id)
            named.append((f"ds_{len(named) + 1}", item))
        step.output_summary = (
            ", ".join(f"{n} = {i.title} ({i.row_count:,} rows)" for n, i in named)
            or "no accessible inputs"
        )
        if not named:
            step.status = "skipped"
    return named


async def _generate(
    ctx: RunContext, system: str, question: str, feedback: list[str], parent: str | None
) -> tuple[Draft | None, bool]:
    """(draft, cut_off): no draft when the reply isn't usable; cut_off when it hit the limit."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    user = f"Today's date: {today}\n\nTask: {question}"
    if feedback:
        user += "\n\nPrevious attempts and problems:\n" + "\n".join(f"- {f}" for f in feedback)
    async with ctx.steps.step("llm", "write analysis code", question, parent) as step:
        raw, usage = await ctx.llm.complete(
            "capable",
            [ChatMessage("system", system), ChatMessage("user", user)],
            max_tokens=CODE_MAX_TOKENS,
            json_mode=True,
            temperature=0,
        )
        ctx.usage.add(usage)
        step.usage = usage
        try:
            draft = parse_draft(raw)
        except (ValueError, json.JSONDecodeError):
            cut_off = usage.tokens_out >= CODE_MAX_TOKENS
            step.status = "error"
            step.output_summary = "cut off: code too long" if cut_off else "invalid JSON"
            return None, cut_off
        step.output_summary = (
            f"{MODE_LABEL[draft.mode]}: {draft.code}"
            if draft.code
            else f"not answerable: {draft.unavailable}"
            if draft.unavailable
            else "asks a clarifying question"
        )
    return draft, False


async def _check(
    ctx: RunContext, draft: Draft, named: list[tuple[str, LoadedInput]], parent: str | None
) -> tuple[str, str | None]:
    """(code to run, problem). Static checks are a convenience; the container is the control."""
    async with ctx.steps.step("check", "check code", MODE_LABEL[draft.mode], parent) as step:
        try:
            if draft.mode == "python":
                if not ctx.python_analysis:
                    raise CodeRejected("PYTHON_DISABLED", PYTHON_OFF)
                code = check_python(draft.code)
            else:
                code = check_sql(draft.code, sandbox_inputs(named))
        except CodeRejected as exc:
            step.status, step.output_summary = "error", f"{exc.code}: {exc.user_message}"
            return draft.code, f"The check rejected the code ({exc.code}): {exc.user_message}"
        step.output_summary = "inputs only, no files or network"
    return code, None


async def _execute(
    ctx: RunContext, mode: str, code: str, named: list[tuple[str, LoadedInput]], parent: str | None
) -> SandboxResult:
    async with ctx.steps.step("tool", "run in sandbox", code, parent) as step:
        task = SandboxTask(mode, code, sandbox_inputs(named))  # type: ignore[arg-type]
        result = await ctx.executor.run(task)
        await ctx.workspace.log_sandbox_run(
            run_id=ctx.run_id,
            user_id=ctx.user_id,
            mode=mode,
            code=code,
            status="ok"
            if result.status == "ok"
            else ("timeout" if result.status == "timeout" else "error"),
            duration_ms=result.duration_ms,
            error=result.error or None,
        )
        if result.status == "ok":
            rows = ", ".join(f"{t.name}: {t.row_count} rows" for t in result.tables)
            stats = f"{len(result.stats)} stats" if result.stats else ""
            step.output_summary = " · ".join(
                x for x in (rows, stats, f"{result.duration_ms} ms") if x
            )
        else:
            step.status, step.output_summary = "error", f"{result.status}: {result.error}"
    return result


async def _save(
    ctx: RunContext,
    draft: Draft,
    code: str,
    result: SandboxResult,
    named: list[tuple[str, LoadedInput]],
) -> tuple[tuple[ArtifactRef, ...], tuple[tuple[tuple[Any, ...], ...], ...]]:
    refs: list[ArtifactRef] = []
    previews: list[tuple[tuple[Any, ...], ...]] = []
    hidden = pii_for_results(named)
    inputs = [{"name": n, "id": i.ref_id, "title": i.title} for n, i in named]
    multi = len(result.tables) > 1
    for table in result.tables:
        title = f"{draft.title} — {table.name.replace('_', ' ')}" if multi else draft.title
        artifact_id = await ctx.workspace.save_result(
            user_id=ctx.user_id,
            run_id=ctx.run_id,
            title=title,
            parquet=table.parquet,
            columns=list(table.columns),
            row_count=table.row_count,
            truncated=table.truncated,
            source_refs={
                "mode": "duckdb" if draft.mode == "sql" else "python",
                "code": code,
                "inputs": inputs,
            },
        )
        rows = [
            [jsonable(v) for v in r.values()]
            for r in pq.read_table(io.BytesIO(table.parquet)).slice(0, 50).to_pylist()
        ]
        refs.append(
            ArtifactRef(
                artifact_id=artifact_id,
                title=title,
                sql=code,
                source="analysis of " + ", ".join(i.title for _, i in named),
                columns=table.columns,
                row_count=table.row_count,
                truncated=table.truncated,
                preview=tuple(tuple(r) for r in rows[:UI_PREVIEW_ROWS]),
                assumptions=draft.assumptions,
                mode="duckdb" if draft.mode == "sql" else "python",
            )
        )
        previews.append(masked_preview(table.columns, rows, hidden))
    return tuple(refs), tuple(previews)


async def run_analysis_agent(
    ctx: RunContext, question: str, input_ids: list[str], parent: str | None
) -> AnalysisOutcome:
    if not ctx.analysis_available or ctx.executor is None or ctx.workspace is None:
        return AnalysisOutcome("no_access", DISABLED)
    named = await _load_inputs(ctx, input_ids, parent)
    if not named:
        return AnalysisOutcome("no_access", NO_INPUTS)
    tables = "\n\n".join(describe(n, i) for n, i in named)
    python_note = "" if ctx.python_analysis else "\n\nPython mode is DISABLED: use DuckDB SQL only."
    system = f"{ctx.prompts.text('analysis_generate')}{python_note}\n\nINPUT TABLES\n{tables}"
    return await _loop(ctx, system, question, named, parent)


async def _loop(
    ctx: RunContext,
    system: str,
    question: str,
    named: list[tuple[str, LoadedInput]],
    parent: str | None,
) -> AnalysisOutcome:
    feedback: list[str] = []
    executions, last_problem = 0, ""
    for attempt in range(1, MAX_GENERATIONS + 1):
        if ctx.budget.breach(ctx.usage.cost_usd):
            break
        draft, cut_off = await _generate(ctx, system, question, feedback, parent)
        if draft is None:
            feedback.append(CUT_OFF if cut_off else BAD_JSON)
            last_problem = "the code was too long" if cut_off else "the reply was not valid JSON"
            continue
        if draft.unavailable and not draft.code:
            return AnalysisOutcome("no_access", draft.unavailable, attempts=attempt)
        if draft.clarification and not draft.code:
            return AnalysisOutcome("clarify", draft.clarification, attempts=attempt)
        code, problem = await _check(ctx, draft, named, parent)
        if problem:
            feedback.append(f"{MODE_LABEL[draft.mode]} code:\n{draft.code}\n  Problem: {problem}")
            last_problem = problem
            continue
        if executions >= MAX_EXECUTIONS:
            break
        if draft.mode == "python" and ctx.python_runs >= MAX_PYTHON_RUNS_PER_RUN:
            feedback.append("The Python run limit for this answer is reached; use DuckDB SQL.")
            continue
        if await ctx.workspace.sandbox_runs_last_hour(ctx.user_id) >= ctx.sandbox_runs_per_hour:
            return AnalysisOutcome("failed", QUOTA, attempts=attempt)
        executions += 1
        ctx.python_runs += draft.mode == "python"
        result = await _execute(ctx, draft.mode, code, named, parent)
        if result.status == "unavailable":
            return AnalysisOutcome("failed", result.error or DISABLED, attempts=attempt)
        if result.status != "ok":
            last_problem = result.error
            hint = RETRY_HINT.get(result.status, "Fix the code using this error.")
            feedback.append(
                f"{MODE_LABEL[draft.mode]} code:\n{code}\n  Error: {result.error}\n  {hint}"
            )
            continue
        if not result.tables and not result.stats:
            last_problem = "the code produced no result table and no stats"
            feedback.append(f"Code:\n{code}\n  Problem: {last_problem}. Call save_table/save_stat.")
            continue
        refs, previews = await _save(ctx, draft, code, result, named)
        stats = dict(list(result.stats.items())[:MAX_STATS_FOR_MODEL])
        return AnalysisOutcome(
            "ok",
            artifacts=refs,
            llm_previews=previews,
            stats=stats,
            mode=draft.mode,
            code=code,
            assumptions=draft.assumptions,
            attempts=attempt,
        )
    reason = f" Last problem: {last_problem}" if last_problem else ""
    return AnalysisOutcome(
        "failed", f"I couldn't complete this analysis.{reason}", attempts=MAX_GENERATIONS
    )
