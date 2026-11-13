"""analyze_data: run DuckDB SQL or Python over the user's data files and result tables (C6)."""

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from eagleeye_agents.analysis.agent import MODE_LABEL, run_analysis_agent
from eagleeye_agents.analysis.types import AnalysisOutcome
from eagleeye_agents.checks.numbers import numbers_in
from eagleeye_agents.tools.base import ToolResult
from eagleeye_agents.tools.query_database import emit_artifact

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext


class AnalyzeArgs(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=1500,
        description="The analysis to perform, precisely, e.g. 'join monthly revenue with the "
        "targets by month and flag months below target'. Include rules or values from documents.",
    )
    inputs: list[str] = Field(
        min_length=1,
        max_length=6,
        description="Ids of the tables to analyse: data file ids from list_datasets and/or "
        "result ids returned by query_database or analyze_data.",
    )


def _table_text(outcome: AnalysisOutcome) -> str:
    parts = []
    for ref, rows in zip(outcome.artifacts, outcome.llm_previews, strict=True):
        header = " | ".join(c["name"] for c in ref.columns)
        body = "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in rows)
        shown = f"first {len(rows)} of {ref.row_count}" if len(rows) < ref.row_count else "all"
        parts.append(
            f"Result id: {ref.artifact_id} — '{ref.title}', {ref.row_count} rows "
            f"(showing {shown})\n{header}\n{body or '(no rows)'}"
        )
    return "\n\n".join(parts)


def outcome_text(outcome: AnalysisOutcome) -> str:
    if outcome.status != "ok":
        prefix = {"clarify": "Clarification needed", "no_access": "Not available"}.get(
            outcome.status, "Analysis failed"
        )
        return f"{prefix}: {outcome.message}"
    lines = [
        f"{MODE_LABEL.get(outcome.mode, outcome.mode)} code:\n{outcome.code}",
        f"Assumptions: {outcome.assumptions or 'none'}",
    ]
    if outcome.stats:
        lines.append("Stats: " + json.dumps(outcome.stats, default=str))
    if outcome.artifacts:
        lines.append(_table_text(outcome))
    lines.append(
        "*** marks personal data hidden from you but visible to the user in the result table."
    )
    return "\n".join(lines)


async def register(ctx: "RunContext", outcome: AnalysisOutcome) -> None:
    for ref, rows in zip(outcome.artifacts, outcome.llm_previews, strict=True):
        ctx.numeric_evidence.extend(numbers_in(v for row in rows for v in row))
        ctx.numeric_evidence.append(float(ref.row_count))
        await emit_artifact(ctx, ref)
    ctx.numeric_evidence.extend(numbers_in(_flatten(outcome.stats)))


def _flatten(value: object) -> list[object]:
    if isinstance(value, dict):
        return [x for v in value.values() for x in _flatten(v)]
    if isinstance(value, list):
        return [x for v in value for x in _flatten(v)]
    return [value]


class AnalyzeDataTool:
    name = "analyze_data"
    description = (
        "Analyse the user's data files and earlier result tables: joins across sources, "
        "group-bys, comparisons, trends, correlations and statistical tests. Writes DuckDB SQL "
        "(or Python when needed), runs it in an isolated sandbox and returns result tables "
        "with ids you can chart. Get database figures with query_database first, then pass "
        "its result id here."
    )
    args_model = AnalyzeArgs
    timeout_s = 150.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        if not isinstance(args, AnalyzeArgs):
            raise TypeError("analyze_data expects AnalyzeArgs")
        outcome = await run_analysis_agent(ctx, args.question, args.inputs, step_id or None)
        await register(ctx, outcome)
        summary = (
            ", ".join(f"{a.row_count} rows" for a in outcome.artifacts) or "stats"
            if outcome.status == "ok"
            else outcome.status
        )
        return ToolResult(outcome.status in ("ok", "clarify"), outcome_text(outcome), summary)
