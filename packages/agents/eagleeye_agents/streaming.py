"""One LLM turn streamed to the user, wrapped in an `llm` step."""

from collections.abc import Sequence
from dataclasses import dataclass

from eagleeye_llm.gateway import ChatMessage, Tier, ToolCall, ToolSpec, Usage

from eagleeye_agents.context import RunContext

CANCEL_CHECK_EVERY = 20  # deltas


@dataclass(frozen=True)
class TurnResult:
    text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    step_id: str


async def stream_turn(
    ctx: RunContext,
    name: str,
    messages: list[ChatMessage],
    tier: Tier = "capable",
    tools: Sequence[ToolSpec] | None = None,
    parent_id: str | None = None,
) -> TurnResult:
    await ctx.cancel.check()
    ctx.text.begin_segment()
    pieces: list[str] = []
    usage = Usage()
    calls: tuple[ToolCall, ...] = ()
    async with ctx.steps.step("llm", name, f"{len(messages)} messages", parent_id) as step:
        n = 0
        async for chunk in ctx.llm.stream(
            tier, messages, max_tokens=ctx.settings.answer_max_tokens, tools=tools
        ):
            if chunk.done:
                usage, calls = chunk.usage, chunk.tool_calls
                continue
            pieces.append(chunk.text)
            await ctx.text.emit(chunk.text)
            n += 1
            if n % CANCEL_CHECK_EVERY == 0:
                await ctx.cancel.check()
        ctx.usage.add(usage)
        step.usage = usage
        tool_names = ", ".join(c.name for c in calls)
        step.output_summary = f"calls {tool_names}" if calls else f"{len(''.join(pieces))} chars"
    return TurnResult("".join(pieces), calls, usage, step.id)
