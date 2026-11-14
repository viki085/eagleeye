"""list_datasets / get_dataset_profile: what data files the user has, and their EDA profile."""

from typing import TYPE_CHECKING

from eagleeye_datasets.render import profile_digest, schema_line
from pydantic import BaseModel, Field

from eagleeye_agents.checks.numbers import numbers_in
from eagleeye_agents.tools.base import ToolResult, error_result

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext

MAX_LISTED = 30


class NoArgs(BaseModel):
    pass


class ProfileArgs(BaseModel):
    dataset_id: str = Field(max_length=64, description="Data file id from list_datasets.")


class ListDatasetsTool:
    name = "list_datasets"
    description = (
        "List the user's uploaded data files (CSV/Excel) ready for analysis, with ids, columns "
        "and size, plus result tables already produced in this answer."
    )
    args_model = NoArgs
    timeout_s = 15.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        files = await ctx.workspace.list_datasets(ctx.user_id) if ctx.workspace else []
        lines = ["DATA FILES"] if files else ["No data files uploaded."]
        for d in files[:MAX_LISTED]:
            lines.append(
                f"- id {d.id}: '{d.title}' ({d.row_count:,} rows) — {schema_line(d.columns)}"
                + (f"\n  {d.summary}" if d.summary else "")
            )
        if ctx.artifacts:
            lines.append("RESULT TABLES IN THIS ANSWER")
            lines += [
                f"- id {a.artifact_id}: '{a.title}' ({a.row_count} rows) — "
                + ", ".join(c["name"] for c in a.columns)
                for a in ctx.artifacts
            ]
        return ToolResult(True, "\n".join(lines), f"{len(files)} data files")


class GetDatasetProfileTool:
    name = "get_dataset_profile"
    description = (
        "Get the automatic profile (EDA) of an uploaded data file: per-column types, missing "
        "values, distributions, top values, correlations and data-quality warnings. Use it "
        "first for 'explore / describe / run EDA on my file' questions."
    )
    args_model = ProfileArgs
    timeout_s = 15.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        if not isinstance(args, ProfileArgs):
            raise TypeError("get_dataset_profile expects ProfileArgs")
        item = await ctx.workspace.load(ctx.user_id, args.dataset_id) if ctx.workspace else None
        if item is None or item.kind != "dataset":
            return error_result("not_found", "That data file isn't available. Use list_datasets.")
        text = profile_digest(item.title, item.profile, with_sample=True)
        stats = [
            v
            for c in item.profile.get("columns", [])
            for k in ("min", "max", "mean", "median", "std", "null_pct", "distinct")
            if isinstance(v := c.get(k), (int, float))
        ]
        ctx.numeric_evidence.extend(float(v) for v in stats)
        ctx.numeric_evidence.append(float(item.row_count))
        # every number the model was shown counts: correlations, top-value counts, warnings
        ctx.numeric_evidence.extend(numbers_in([text]))
        return ToolResult(True, text, f"profile of {item.title}")
