from typing import TYPE_CHECKING

from pydantic import BaseModel

from eagleeye_agents.sources import neutralise
from eagleeye_agents.tools.base import ToolResult

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext


class NoArgs(BaseModel):
    pass


class ListDocumentsTool:
    name = "list_documents"
    description = "List the documents available to the user (title, scope, size, id)."
    args_model = NoArgs
    timeout_s = 10.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        docs = await ctx.store.visible_ready_documents(ctx.user_id)
        if not docs:
            return ToolResult(True, "The user has no documents yet.", "0 documents")
        lines = []
        for d in docs:
            size = f"{d.page_count} pages, " if d.page_count else ""
            lines.append(
                f"- {neutralise(d.title)} ({d.scope}, {size}{d.chunk_count or 0} chunks) id={d.id}"
            )
        return ToolResult(True, "\n".join(lines), f"{len(docs)} documents")
