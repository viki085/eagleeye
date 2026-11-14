"""explore_data: an analyst-style exploratory notebook (pandas + plots) over a data file.

Offered only in notebook mode (company users; never the shared demo account). The notebook
(cells, code, tables, figures) is shown to the user; the planner summarises it.
"""

from typing import TYPE_CHECKING

from eagleeye_events.names import NOTEBOOK
from pydantic import BaseModel, Field

from eagleeye_agents.notebook.agent import run_notebook_agent
from eagleeye_agents.tools.base import ToolResult, error_result

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext

MAX_NOTEBOOKS_PER_ANSWER = 1


class ExploreArgs(BaseModel):
    goal: str = Field(
        min_length=3,
        max_length=800,
        description="What to explore, in the user's words plus anything they care about, e.g. "
        "'detailed EDA of the passenger list, focusing on what explains survival'.",
    )
    inputs: list[str] = Field(
        min_length=1,
        max_length=2,
        description="Data file ids from list_datasets (or result ids) to explore; usually one.",
    )


class ExploreDataTool:
    name = "explore_data"
    description = (
        "Write and run an exploratory-analysis NOTEBOOK (pandas, matplotlib/seaborn plots) over "
        "one or two data files, like a data analyst would in Jupyter: overview, missing values, "
        "distributions, categories, correlations and the most interesting patterns. The user "
        "sees every cell with its code, tables and plots, and can download it as .ipynb. Use it "
        "for broad requests ('detailed EDA', 'explore this file in depth'); use analyze_data for "
        "specific questions. One notebook per answer."
    )
    args_model = ExploreArgs
    timeout_s = 420.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        if not isinstance(args, ExploreArgs):
            raise TypeError("explore_data expects ExploreArgs")
        if not ctx.notebook_available:
            return error_result("not_available", "Notebook analysis is not available here.")
        if len(ctx.notebooks) >= MAX_NOTEBOOKS_PER_ANSWER:
            return error_result("limit", "Only one notebook per answer; summarise the one shown.")
        outcome = await run_notebook_agent(ctx, args.goal, args.inputs, step_id or None)
        if outcome.notebook is None:
            return ToolResult(False, f"Notebook failed: {outcome.message}", outcome.status)
        ctx.notebooks.append(outcome.notebook)
        ctx.numeric_evidence.extend(outcome.evidence)
        await ctx.sink.emit(NOTEBOOK, outcome.notebook)
        cells = len(outcome.notebook["cells"])
        return ToolResult(True, outcome.summary, f"notebook: {cells} cells")
