"""search_knowledge: hybrid retrieval over the user's documents.

Authorization is never taken from the model: the user comes from the run, and any
document ids the model passes are intersected with what that user can see.
"""

from typing import TYPE_CHECKING, Literal

from eagleeye_retrieval.types import ALL_SCOPES, AccessScope
from pydantic import BaseModel, Field

from eagleeye_agents.sources import format_sources
from eagleeye_agents.tools.base import ToolResult

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="Focused search query.")
    scope: Literal["both", "personal", "enterprise"] = Field(
        default="both",
        description=(
            "Keep 'both' unless the user explicitly limits the search to their own uploads "
            "('personal') or company documents ('enterprise')."
        ),
    )
    doc_ids: list[str] = Field(
        default_factory=list, max_length=20, description="Optional: restrict to these document ids."
    )


class SearchKnowledgeTool:
    name = "search_knowledge"
    description = (
        "Search the user's documents (personal uploads and enterprise documents) and return "
        "the most relevant passages, each numbered [n] for citation."
    )
    args_model = SearchArgs
    timeout_s = 20.0

    async def run(self, args: BaseModel, ctx: "RunContext", step_id: str = "") -> ToolResult:
        if not isinstance(args, SearchArgs):
            raise TypeError("search_knowledge expects SearchArgs")
        doc_ids: tuple[str, ...] | None = None
        if args.doc_ids:
            visible = {d.id for d in await ctx.store.visible_ready_documents(ctx.user_id)}
            allowed = tuple(d for d in args.doc_ids if d in visible)
            if not allowed:
                return ToolResult(
                    True, "None of those documents are available.", "no accessible docs"
                )
            doc_ids = allowed
        scopes = ALL_SCOPES if args.scope == "both" else (args.scope,)
        scope = AccessScope(user_id=ctx.user_id, doc_ids=doc_ids, scopes=scopes)
        result = await ctx.retriever.retrieve(args.query, [], scope, rewrite=False)
        if not result.chunks:
            return ToolResult(True, "No matching passages found.", "0 passages")
        numbered = ctx.sources.register_all(result.chunks)
        note = (
            "Note: low relevance — these passages may not answer the question.\n\n"
            if (result.low_relevance)
            else ""
        )
        refs = ", ".join(f"[{n}]" for n, _ in numbered)
        return ToolResult(True, note + format_sources(numbered), f"{len(numbered)} passages {refs}")
