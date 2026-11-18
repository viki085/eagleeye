"""make_chart: chart intent → Vega-Lite spec built in code from a table the user owns (C6 §5).

The model chooses columns and a chart type; every plotted number and the summary sentence
come from the data. A wrong intent returns the reason so the model can fix it once; after
that it should answer with the table.
"""

import uuid
from typing import TYPE_CHECKING

from eagleeye_charts.build import build_chart
from eagleeye_charts.intent import ChartError, ChartIntent
from eagleeye_events.names import CHART
from pydantic import BaseModel, Field

from eagleeye_agents.tools.base import ToolResult, error_result

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext

MAX_CHARTS = 4
MAX_CHART_FAILURES = 2


class ChartArgs(ChartIntent):
    source_id: str = Field(
        max_length=64,
        description="Result id from query_database / analyze_data, or a data file id.",
    )


class MakeChartTool:
    name = "make_chart"
    description = (
        "Draw a chart from a result table or data file. You pick the chart type and columns; "
        "the data is plotted by code (never type numbers yourself). Use when the user asks "
        "for a chart or when a trend or comparison is the answer. Max 4 per answer."
    )
    args_model = ChartArgs
    timeout_s = 30.0

    def __init__(self) -> None:
        self._failures = 0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        if not isinstance(args, ChartArgs):
            raise TypeError("make_chart expects ChartArgs")
        if len(ctx.charts) >= MAX_CHARTS:
            return error_result("chart_limit", f"At most {MAX_CHARTS} charts per answer.")
        if self._failures >= MAX_CHART_FAILURES:
            return error_result(
                "chart_failed", "Charting failed twice; answer with the result table instead."
            )
        source = await ctx.workspace.load(ctx.user_id, args.source_id) if ctx.workspace else None
        if source is None:
            return error_result("no_source", "That table isn't available. Use a result id.")
        intent = ChartIntent.model_validate(args.model_dump(exclude={"source_id"}))
        try:
            chart = build_chart(source.parquet, list(source.columns), intent)
        except ChartError as exc:
            self._failures += 1
            return error_result("invalid_chart", exc.user_message)
        payload = {
            "chart_id": str(uuid.uuid4()),
            "title": intent.title,
            "spec": chart.spec,
            "summary": chart.summary,
            "source_id": source.ref_id,
        }
        ctx.charts.append(payload)
        ctx.numeric_evidence.extend(chart.values)
        await ctx.sink.emit(CHART, payload)
        content = (
            f"Chart '{intent.title}' is shown to the user below your answer (call it 'the chart'; "
            "never 'above', and no placeholder text for it). "
            f"Computed from the data: {chart.summary}"
        )
        return ToolResult(True, content, f"{intent.type} chart")
