"""query_database: natural-language question → validated SQL → result table (C5)."""

from typing import TYPE_CHECKING

from eagleeye_events.names import ARTIFACT
from pydantic import BaseModel, Field

from eagleeye_agents.checks.numbers import numbers_in
from eagleeye_agents.sql.agent import run_sql_agent
from eagleeye_agents.sql.preview import format_result
from eagleeye_agents.sql.types import SqlOutcome
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


async def register_artifact(ctx: "RunContext", outcome: SqlOutcome) -> None:
    """Make a successful result visible to the UI and to the final checks."""
    if outcome.artifact is None:
        return
    ctx.artifacts.append(outcome.artifact)
    ctx.numeric_evidence.extend(numbers_in(v for row in outcome.llm_preview for v in row))
    ctx.numeric_evidence.append(float(outcome.artifact.row_count))
    await ctx.sink.emit(ARTIFACT, outcome.artifact.to_dict())


def outcome_text(outcome: SqlOutcome) -> str:
    if outcome.status != "ok" or outcome.artifact is None:
        prefix = {"clarify": "Clarification needed", "no_access": "Not available"}.get(
            outcome.status, "Query failed"
        )
        return f"{prefix}: {outcome.message}"
    a = outcome.artifact
    return format_result(
        a.sql, a.assumptions, a.columns, outcome.llm_preview, a.row_count, a.truncated
    )


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
