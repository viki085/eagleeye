"""Answer cache (ADR-21): reuse a whole answer to a repeated company-document question.

Only safe cases are cached:
- lookup only for the first message of a chat with no documents ticked (so the answer does not
  depend on earlier turns or a personal selection), on a route that can answer from documents;
- store only answers that cite company documents and nothing else: no personal chunk was shown
  to the model, no database or data-file results, no charts, no warnings, no fallback model.

The key holds the normalised question, the user's role, whether the user has personal documents
(if so the key is theirs alone), and a version stamp of the company library, so adding,
removing or re-indexing any company document retires every cached answer. Entries expire with
the cache TTL (24 h by default).
"""

import re
from typing import Any

import asyncpg
from eagleeye_events.names import CITATION

from eagleeye_agents.context import RunContext
from eagleeye_agents.nodes.guard import Node
from eagleeye_agents.state import RunState

CACHEABLE_ROUTES = frozenset({"rag", "rag_auto", "supervisor"})
_SPACES = re.compile(r"\s+")


def normalise(question: str) -> str:
    """Case, spacing and trailing punctuation don't change the question."""
    return _SPACES.sub(" ", question).strip().rstrip("?!. ").lower()


def can_look_up(state: RunState) -> bool:
    return not state.get("history") and not state.get("doc_ids")


async def answer_key(
    pool: asyncpg.Pool,
    user_id: str,
    role: str,
    question: str,
    prompt_versions: dict[str, Any],
    model_ids: dict[str, str],
) -> tuple:
    corpus = await pool.fetchrow(
        "SELECT count(*) AS n, max(updated_at) AS changed FROM documents "
        "WHERE scope = 'enterprise' AND status = 'READY'"
    )
    has_personal = await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM documents WHERE scope = 'personal' AND owner_id = $1::uuid "
        "AND status = 'READY')",
        user_id,
    )
    changed = corpus["changed"].isoformat() if corpus["changed"] else ""
    return (
        normalise(question),
        role,
        user_id if has_personal else "-",
        int(corpus["n"]),
        changed,
        sorted(prompt_versions.items()),
        sorted(model_ids.items()),
    )


def can_store(ctx: RunContext, route: str | None, status: str, citations: list[dict]) -> bool:
    return (
        ctx.answer_key is not None
        and route in CACHEABLE_ROUTES
        and status == "SUCCEEDED"
        and bool(citations)
        and all(c.get("scope") == "enterprise" for c in citations)
        and ctx.sources.scopes() == {"enterprise"}
        and not ctx.artifacts
        and not ctx.charts
        and not ctx.warnings
        and not ctx.usage.degraded
    )


def make_answer_cache_node(ctx: RunContext) -> Node:
    """Between the guard and the answering nodes: replays a cached answer, or does nothing."""

    async def answer_cache_node(state: RunState) -> dict:
        if ctx.cache is None or ctx.answer_key is None:
            return {}
        async with ctx.steps.step("cache", "reuse answer", state["question"]) as step:
            hit = await ctx.cache.get("answer", ctx.answer_key)
            valid = hit is not None and isinstance(hit.get("text"), str) and hit.get("citations")
            step.output_summary = "reused a recent answer" if valid else "no recent answer"
        if not valid:
            return {}
        await ctx.text.emit(hit["text"])
        for citation in hit["citations"]:
            await ctx.sink.emit(CITATION, citation)
        return {"cache_hit": True, "status": "SUCCEEDED", "citations": list(hit["citations"])}

    return answer_cache_node
