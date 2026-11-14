"""query_database: natural-language question → validated SQL → result table (C5)."""

from typing import TYPE_CHECKING

from eagleeye_events.names import ARTIFACT
from pydantic import BaseModel, Field

from eagleeye_agents.checks.numbers import numbers_in
from eagleeye_agents.sql.agent import run_sql_agent
from eagleeye_agents.sql.preview import format_result
from eagleeye_agents.sql.types import ArtifactRef, SqlOutcome
from eagleeye_agents.tools.base import ToolResult

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext


class QueryArgs(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=1000,
        description=(
            "One precise question about business data, e.g. 'net revenue by month in 2025'."
        ),
    )
    source: str | None = Field(
        default=None,
        max_length=100,
        description="Data source name from list_data_sources; omit when there is only one.",
    )


async def emit_artifact(ctx: "RunContext", artifact: ArtifactRef) -> None:
    ctx.artifacts.append(artifact)
    await ctx.sink.emit(ARTIFACT, artifact.to_dict())


async def register_artifact(ctx: "RunContext", outcome: SqlOutcome) -> None:
    """Make a successful result visible to the UI and to the final checks."""
    if outcome.artifact is None:
        return
    ctx.numeric_evidence.extend(numbers_in(v for row in outcome.llm_preview for v in row))
    ctx.numeric_evidence.append(float(outcome.artifact.row_count))
    # the query's own constants are facts the answer may restate ("within 24 hours", "> 50 TEU")
    ctx.numeric_evidence.extend(numbers_in([outcome.artifact.sql, outcome.artifact.assumptions]))
    await emit_artifact(ctx, outcome.artifact)


def outcome_text(outcome: SqlOutcome) -> str:
    if outcome.status != "ok" or outcome.artifact is None:
        if outcome.status == "unanswerable":
            return (
                f"Not answerable from the database as asked: {outcome.message}\n"
                "If the question depends on values from a data file, a document or an earlier "
                "result (names, ids, dates), ask again listing those values explicitly, or "
                "fetch the matching rows and join them with analyze_data."
            )
        prefix = {"clarify": "Clarification needed", "no_access": "Not available"}.get(
            outcome.status, "Query failed"
        )
        return f"{prefix}: {outcome.message}"
    a = outcome.artifact
    text = format_result(
        a.sql, a.assumptions, a.columns, outcome.llm_preview, a.row_count, a.truncated
    )
    # the id lets the supervisor pass this result to analyze_data / make_chart
    return f"Result id: {a.artifact_id} — '{a.title}'\n{text}"


class QueryDatabaseTool:
    name = "query_database"
    description = (
        "Answer a question from the company's business database (sales, orders, customers, "
        "products, shipments, returns). Writes, validates and runs a read-only SQL query and "
        "returns the result rows. One focused question per call."
    )
    args_model = QueryArgs
    timeout_s = 90.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        if not isinstance(args, QueryArgs):
            raise TypeError("query_database expects QueryArgs")
        outcome = await run_sql_agent(ctx, args.question, args.source, step_id or None)
        await register_artifact(ctx, outcome)
        summary = f"{outcome.artifact.row_count} rows" if outcome.artifact else outcome.status
        return ToolResult(outcome.status in ("ok", "clarify"), outcome_text(outcome), summary)
