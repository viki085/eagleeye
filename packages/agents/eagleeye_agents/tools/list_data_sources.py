from typing import TYPE_CHECKING

from pydantic import BaseModel

from eagleeye_agents.tools.base import ToolResult

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext


class NoArgs(BaseModel):
    pass


class ListDataSourcesTool:
    name = "list_data_sources"
    description = "List the business databases this user can query, with their tables."
    args_model = NoArgs
    timeout_s = 10.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        if ctx.catalog is None:
            return ToolResult(True, "No data sources are available.", "0 sources")
        sources = await ctx.catalog.accessible_sources(ctx.user_role)
        if not sources:
            return ToolResult(True, "No data sources are available to this user.", "0 sources")
        lines = []
        for acc in sources:
            tables = "; ".join(
                f"{t.key} — {t.description}" if t.description else t.key for t in acc.tables
            )
            lines.append(f"- {acc.source.name}: {acc.source.description}\n  Tables: {tables}")
        return ToolResult(True, "\n".join(lines), f"{len(sources)} sources")
