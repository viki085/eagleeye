"""Guard node: rules → LLM classifier → route. Fails closed (C3 §2.1)."""

from collections.abc import Awaitable, Callable

from eagleeye_events.names import GUARD_RESULT
from eagleeye_llm.gateway import Usage

from eagleeye_agents.context import RunContext
from eagleeye_agents.errors import GuardUnavailableError
from eagleeye_agents.guard.classifier import classify
from eagleeye_agents.guard.rules import check_rules
from eagleeye_agents.guard.verdict import GuardVerdict, unavailable
from eagleeye_agents.router import choose_route
from eagleeye_agents.state import RunState

MAX_LOGGED_INPUT = 2000

Node = Callable[[RunState], Awaitable[dict]]


async def _verdict(ctx: RunContext, state: RunState) -> tuple[GuardVerdict, Usage]:
    question = state["question"]
    hit = check_rules(question, ctx.settings.denied_topics)
    if hit is not None:
        return hit.verdict(), Usage()
    docs = await ctx.store.visible_ready_documents(ctx.user_id)
    try:
        verdict, usage = await classify(
            ctx.llm,
            ctx.prompts.text("guard"),
            question,
            state.get("history", []),
            [d.title for d in docs],
            bool(state.get("doc_ids")),
        )
    except GuardUnavailableError as exc:
        return unavailable(str(exc)), Usage()
    ctx.usage.add(usage)
    return verdict, usage


async def _refuse(ctx: RunContext, verdict: GuardVerdict, question: str) -> None:
    """Neutral reply that never reveals what was detected; full input logged for review."""
    unavailable_ = verdict.source == "error"
    await ctx.text.emit(ctx.prompts.text("unavailable" if unavailable_ else "refusal"))
    await ctx.store.record_security_event(
        ctx.user_id,
        ctx.run_id,
        "guard_unavailable" if unavailable_ else "input_blocked",
        verdict.safe,
        {"rule": verdict.detail, "source": verdict.source, "input": question[:MAX_LOGGED_INPUT]},
    )


def make_guard_node(ctx: RunContext) -> Node:
    async def guard_node(state: RunState) -> dict:
        await ctx.cancel.check()
        question = state["question"]
        async with ctx.steps.step("guard", "safety & intent", question) as step:
            verdict, step.usage = await _verdict(ctx, state)
            route = choose_route(verdict, bool(state.get("doc_ids")), ctx.sql_available)
            step.status = "error" if verdict.source == "error" else "ok"
            step.output_summary = f"{verdict.safe} · {verdict.intent} · {route}"
        await ctx.sink.emit(
            GUARD_RESULT, {"safe": verdict.safe, "intent": verdict.intent, "route": route}
        )
        if route == "blocked":
            await _refuse(ctx, verdict, question)
        return {"guard": verdict, "route": route}

    return guard_node
