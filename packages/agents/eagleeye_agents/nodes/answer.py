"""Single-call paths: simple chat (no tools) and the fixed RAG pipeline (C3 §2.2)."""

from eagleeye_llm.gateway import ChatMessage
from eagleeye_retrieval.types import AccessScope, RetrievedChunk

from eagleeye_agents.context import RunContext
from eagleeye_agents.nodes.guard import Node
from eagleeye_agents.sources import format_sources
from eagleeye_agents.state import RunState
from eagleeye_agents.streaming import stream_turn

MAX_HISTORY_MESSAGES = 20

NO_COVERAGE = """<context>
(no relevant passages were found in the user's documents)
</context>
Tell the user their documents don't appear to cover this question, and suggest rephrasing,
selecting different documents, or uploading the right one. Do not answer from general knowledge."""


def conversation(state: RunState, system_prompt: str) -> list[ChatMessage]:
    history = state.get("history", [])[-MAX_HISTORY_MESSAGES:]
    return [ChatMessage("system", system_prompt), *history, ChatMessage("user", state["question"])]


def make_simple_node(ctx: RunContext) -> Node:
    async def simple_node(state: RunState) -> dict:
        await stream_turn(ctx, "answer", conversation(state, ctx.prompts.text("simple")))
        return {"grounded": False}

    return simple_node


async def _retrieve(ctx: RunContext, state: RunState) -> tuple[tuple[RetrievedChunk, ...], bool]:
    doc_ids = tuple(state.get("doc_ids", [])) or None
    async with ctx.steps.step("retrieval", "search documents", state["question"]) as step:
        if doc_ids is None and not await ctx.store.visible_ready_documents(ctx.user_id):
            step.status, step.output_summary = "skipped", "no documents"
            return (), True
        scope = AccessScope(user_id=ctx.user_id, doc_ids=doc_ids)
        result = await ctx.retriever.retrieve(state["question"], state.get("history", []), scope)
        relevance = "low relevance" if result.low_relevance else "relevant"
        step.output_summary = f"{len(result.chunks)} passages · {relevance}"
        return result.chunks, result.low_relevance


def make_rag_node(ctx: RunContext) -> Node:
    async def rag_node(state: RunState) -> dict:
        await ctx.cancel.check()
        chunks, low = await _retrieve(ctx, state)
        explicit = bool(state.get("doc_ids"))
        if state.get("route") == "rag_auto" and (low or not chunks):
            await stream_turn(ctx, "answer", conversation(state, ctx.prompts.text("simple")))
            return {"grounded": False}
        use = chunks if explicit or not low else ()
        context = (
            f"<context>\n{format_sources(ctx.sources.register_all(use))}\n</context>"
            if use
            else NO_COVERAGE
        )
        system = f"{ctx.prompts.text('rag')}\n\n{context}"
        await stream_turn(ctx, "answer", conversation(state, system))
        return {"grounded": True}

    return rag_node
