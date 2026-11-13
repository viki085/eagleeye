"""The SQL sub-agent loop (C5 §3): ≤ 4 generations, ≤ 3 executions, self-correcting.

Every step nests under `parent_id` so the UI shows catalog → generate → validate → run.
Access is decided by code at three points: catalog (granted tables only), local sqlsafe,
and the gateway (authoritative re-validation).
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from eagleeye_catalog.render import render_context
from eagleeye_catalog.service import SourceAccess
from eagleeye_llm.gateway import ChatMessage
from eagleeye_sqlsafe.errors import SqlRejected
from eagleeye_sqlsafe.validator import validate

from eagleeye_agents.context import RunContext
from eagleeye_agents.sql.preview import masked_preview
from eagleeye_agents.sql.types import UI_PREVIEW_ROWS, ArtifactRef, GatewayResult, SqlOutcome

logger = logging.getLogger(__name__)

MAX_GENERATIONS = 4
MAX_EXECUTIONS = 3
ZERO_ROWS_HINT = (
    "The query returned 0 rows. Check the filter values against the column samples and the "
    "date range of the data. If the filters are right, return the same query unchanged."
)
NO_ACCESS = "You don't have access to a data source that can answer this."
DISABLED = "Database querying is turned off."


@dataclass(frozen=True)
class Draft:
    sql: str
    assumptions: str
    clarification: str
    title: str
    unavailable: str = ""


def parse_draft(raw: str) -> Draft:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return Draft(
        sql=str(data.get("sql") or "").strip(),
        assumptions=str(data.get("assumptions") or "").strip()[:400],
        clarification=str(data.get("clarification") or "").strip()[:400],
        title=str(data.get("title") or "Query result").strip()[:80],
        unavailable=str(data.get("unavailable") or "").strip()[:300],
    )


async def _generate(
    ctx: RunContext, system: str, question: str, feedback: list[str], parent: str | None
) -> Draft | None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    user = f"Today's date: {today}\n\nQuestion: {question}"
    if feedback:
        user += "\n\nPrevious attempts and problems:\n" + "\n".join(f"- {f}" for f in feedback)
    ctx.budget.record_step()
    async with ctx.steps.step("llm", "write SQL", question, parent) as step:
        raw, usage = await ctx.llm.complete(
            "capable",
            [ChatMessage("system", system), ChatMessage("user", user)],
            max_tokens=900,
            json_mode=True,
            temperature=0,
        )
        ctx.usage.add(usage)
        step.usage = usage
        try:
            draft = parse_draft(raw)
        except (ValueError, json.JSONDecodeError):
            step.status, step.output_summary = "error", "invalid JSON"
            return None
        if draft.sql:
            step.output_summary = draft.sql
        elif draft.unavailable:
            step.output_summary = f"not answerable: {draft.unavailable}"
        else:
            step.output_summary = "asks a clarifying question"
    return draft


async def _check(ctx: RunContext, acc: SourceAccess, sql: str, parent: str | None) -> str | None:
    """Local validation (fast feedback). Returns a problem description, or None if valid."""
    async with ctx.steps.step("check", "validate SQL", "", parent) as step:
        try:
            validate(sql, acc.policy)
        except SqlRejected as exc:
            step.status, step.output_summary = "error", f"{exc.code}: {exc.user_message}"
            return f"Validation rejected the query ({exc.code}): {exc.user_message}"
        step.output_summary = "read-only, granted tables only"
    return None


async def _execute(
    ctx: RunContext, acc: SourceAccess, draft: Draft, parent: str | None
) -> GatewayResult:
    async with ctx.steps.step("tool", "run SQL", draft.sql, parent) as step:
        result = await ctx.gateway.execute(
            ctx.user_id, ctx.run_id, acc.source.id, draft.sql, draft.title
        )
        if result.ok:
            trunc = " (truncated)" if result.truncated else ""
            step.output_summary = f"{result.row_count} rows{trunc} · {result.duration_ms} ms"
        else:
            step.status, step.output_summary = "error", f"{result.code}: {result.error}"
    return result


def _pii_names(acc: SourceAccess) -> set[str]:
    return {c.name.lower() for t in acc.tables for c in t.columns if c.pii}


def _success(acc: SourceAccess, draft: Draft, result: GatewayResult, attempts: int) -> SqlOutcome:
    artifact = ArtifactRef(
        artifact_id=result.artifact_id,
        title=draft.title,
        sql=result.sql,
        source=acc.source.name,
        columns=result.columns,
        row_count=result.row_count,
        truncated=result.truncated,
        preview=result.preview[:UI_PREVIEW_ROWS],
        assumptions=draft.assumptions,
    )
    llm_rows = masked_preview(result.columns, result.preview, _pii_names(acc))
    return SqlOutcome("ok", artifact=artifact, llm_preview=llm_rows, attempts=attempts)


async def run_sql_agent(
    ctx: RunContext, question: str, source_name: str | None, parent: str | None
) -> SqlOutcome:
    if not ctx.sql_available or ctx.catalog is None or ctx.gateway is None:
        return SqlOutcome("no_access", DISABLED)
    async with ctx.steps.step("retrieval", "find tables", question, parent) as step:
        acc = await ctx.catalog.resolve_source(ctx.user_role, source_name)
        if acc is None:
            step.status, step.output_summary = "skipped", "no accessible data source"
            return SqlOutcome("no_access", NO_ACCESS)
        schema = await ctx.catalog.schema_context(acc, question)
        step.output_summary = f"{acc.source.name}: {', '.join(t.name for t in schema.tables)}"
    system = f"{ctx.prompts.text('sql_generate')}\n\n{render_context(schema)}"
    return await _loop(ctx, acc, system, question, parent)


async def _loop(
    ctx: RunContext, acc: SourceAccess, system: str, question: str, parent: str | None
) -> SqlOutcome:
    feedback: list[str] = []
    executions, zero_retry_used, last_problem = 0, False, ""
    for attempt in range(1, MAX_GENERATIONS + 1):
        if ctx.budget.breach(ctx.usage.cost_usd):
            break
        draft = await _generate(ctx, system, question, feedback, parent)
        if draft is None:
            feedback.append("Your last reply was not valid JSON. Return only the JSON object.")
            continue
        if draft.unavailable and not draft.sql:
            # The model only saw granted tables, so this can't reveal hidden ones.
            return SqlOutcome("no_access", draft.unavailable, attempts=attempt)
        if draft.clarification and not draft.sql:
            return SqlOutcome("clarify", draft.clarification, attempts=attempt)
        problem = await _check(ctx, acc, draft.sql, parent)
        if problem:
            feedback.append(f"SQL: {draft.sql}\n  Problem: {problem}")
            last_problem = problem
            continue
        if executions >= MAX_EXECUTIONS:
            break
        executions += 1
        result = await _execute(ctx, acc, draft, parent)
        if not result.ok:
            last_problem = result.error
            if not result.retryable:
                return SqlOutcome("failed", result.error, attempts=attempt)
            feedback.append(f"SQL: {draft.sql}\n  Database said: {result.error}")
            continue
        if result.row_count == 0 and not zero_retry_used and executions < MAX_EXECUTIONS:
            zero_retry_used = True
            feedback.append(f"SQL: {draft.sql}\n  {ZERO_ROWS_HINT}")
            continue
        return _success(acc, draft, result, attempt)
    reason = f" Last problem: {last_problem}" if last_problem else ""
    return SqlOutcome(
        "failed", f"I couldn't produce a working query for this.{reason}", attempts=MAX_GENERATIONS
    )
