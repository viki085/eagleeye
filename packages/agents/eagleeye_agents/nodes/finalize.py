"""Finalize: grounding check → output filter → citation events → final status."""

from eagleeye_events.names import CITATION

from eagleeye_agents.checks.grounding import check_grounding
from eagleeye_agents.checks.numbers import numbers_in, unverified_figures
from eagleeye_agents.checks.output_filter import filter_output
from eagleeye_agents.context import RunContext
from eagleeye_agents.nodes.guard import Node
from eagleeye_agents.state import RunState

FILTERED_PROMPTS = ("guard", "simple", "rag", "supervisor", "sql_generate", "sql_answer")
UNVERIFIED_NUMBERS = "unverified_numbers"


async def _check_numbers(ctx: RunContext, state: RunState, text: str) -> None:
    """Only when data was queried: every figure should trace back to something the model saw."""
    if not ctx.artifacts:
        return
    async with ctx.steps.step("check", "figures") as step:
        evidence = ctx.numeric_evidence + numbers_in(ctx.sources.texts())
        unmatched = unverified_figures(text, evidence, state.get("question", ""))
        if unmatched:
            step.status = "error"
            step.output_summary = f"{len(unmatched)} not in results: {', '.join(unmatched[:5])}"
            ctx.warnings.append(UNVERIFIED_NUMBERS)
        else:
            step.output_summary = "all figures match the query results"


async def _checked_text(ctx: RunContext, state: RunState) -> tuple[str, bool]:
    """Returns (final text, blocked by output filter)."""
    answer = ctx.text.value
    async with ctx.steps.step("check", "citations") as step:
        grounding = check_grounding(answer, ctx.sources, bool(state.get("grounded")))
        step.output_summary = (
            "uncited answer" if grounding.uncited_grounded else f"{grounding.cited} citations"
        ) + (" · removed invalid markers" if grounding.changed else "")
    async with ctx.steps.step("check", "output filter") as step:
        prompts = [ctx.prompts.text(n) for n in FILTERED_PROMPTS]
        result = filter_output(grounding.text, prompts)
        step.output_summary = ", ".join(result.findings) or "clean"
        if result.blocked:
            step.status = "error"
            await ctx.store.record_security_event(
                ctx.user_id,
                ctx.run_id,
                "output_filtered",
                result.findings[0],
                {"findings": list(result.findings)},
            )
    return result.text, result.blocked


def make_finalize_node(ctx: RunContext) -> Node:
    async def finalize_node(state: RunState) -> dict:
        status = "BUDGET_EXCEEDED" if state.get("stop_reason") else "SUCCEEDED"
        if state.get("route") == "blocked":
            return {"status": status, "citations": []}
        final, blocked = await _checked_text(ctx, state)
        if final != ctx.text.value:
            await ctx.text.replace(final)
        if not blocked:
            await _check_numbers(ctx, state, final)
        citations = [] if blocked else [c.to_dict() for c in ctx.sources.citations_for(final)]
        for citation in citations:
            await ctx.sink.emit(CITATION, citation)
        return {"status": status, "citations": citations}

    return finalize_node
