"""Supervisor ReAct loop (C3 §2.3): capable model with tools, hard budgets, loop detection."""

import asyncio
import json
import logging
from datetime import UTC, datetime

from eagleeye_llm.gateway import ChatMessage, ToolCall
from pydantic import ValidationError

from eagleeye_agents.budgets import LoopVerdict
from eagleeye_agents.context import RunContext
from eagleeye_agents.nodes.answer import conversation
from eagleeye_agents.nodes.guard import Node
from eagleeye_agents.references import planner_note
from eagleeye_agents.sources import neutralise
from eagleeye_agents.state import RunState
from eagleeye_agents.streaming import stream_turn
from eagleeye_agents.tools.base import ToolResult, error_result
from eagleeye_agents.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

LIMIT_NOTE = (
    "A work limit was reached ({reason}). Do not call tools. Answer now using only the "
    "information above, and tell the user briefly that the answer may be incomplete because "
    "a work limit was reached."
)
REPEAT_HINT = (
    "You already made this exact call. Use the earlier result, or try a different query/approach."
)


NOTEBOOK_QUOTA_NOTE = (
    "This is a demo visit and its detailed-analysis (notebook) allowance is used up, so "
    "explore_data is not available. If the user asks for a detailed or exploratory analysis, do "
    "the analysis with analyze_data instead, and end your answer with this sentence: "
    '"This demo visit has used up its detailed analyses (notebook mode), so this is the basic '
    'analysis."'
)


def _system_prompt(ctx: RunContext) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    notes = [n for n in (planner_note(ctx.references),) if n]
    if ctx.notebook_quota_exhausted:
        notes.append(NOTEBOOK_QUOTA_NOTE)
    return f"{ctx.prompts.text('supervisor')}\n\nCurrent time: {now}" + "".join(
        f"\n\n{n}" for n in notes
    )


def make_supervisor_node(ctx: RunContext, registry: ToolRegistry) -> Node:
    async def supervisor_node(state: RunState) -> dict:
        messages = conversation(state, _system_prompt(ctx)) + state.get("sup_messages", [])
        reason = state.get("stop_reason") or ctx.budget.breach(ctx.usage.cost_usd)
        if reason:
            note = ChatMessage("system", LIMIT_NOTE.format(reason=reason.replace("_", " ")))
            await stream_turn(ctx, "final answer (limit reached)", [*messages, note])
            return {"stop_reason": reason, "pending_calls": (), "grounded": True}
        ctx.budget.record_step()
        turn = await stream_turn(ctx, "plan & answer", messages, tools=registry.specs())
        if not turn.tool_calls:
            return {"pending_calls": (), "grounded": True}
        assistant = ChatMessage("assistant", turn.text, tool_calls=turn.tool_calls)
        return {
            "sup_messages": [assistant],
            "pending_calls": turn.tool_calls,
            "llm_step_id": turn.step_id,
            "grounded": True,
        }

    return supervisor_node


def wrap_tool_output(name: str, content: str) -> str:
    return f'<tool_data name="{name}">\n{neutralise(content)}\n</tool_data>'


async def _invoke(
    ctx: RunContext, registry: ToolRegistry, call: ToolCall, step_id: str
) -> tuple[ToolResult, str]:
    tool = registry.get(call.name)
    if tool is None:
        return error_result("unknown_tool", f"unknown tool '{call.name}'"), LoopVerdict.OK
    try:
        raw = json.loads(call.arguments_json or "{}")
        args = tool.args_model.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        return error_result("invalid_args", f"invalid arguments: {str(exc)[:200]}"), LoopVerdict.OK
    verdict = ctx.budget.record_tool_call(call.name, args.model_dump())
    if verdict == LoopVerdict.STOP:
        return error_result("loop", "stopped: the same call was repeated"), verdict
    if verdict == LoopVerdict.REPEAT:
        return ToolResult(True, REPEAT_HINT, "repeated call"), verdict
    try:
        return await asyncio.wait_for(tool.run(args, ctx, step_id), tool.timeout_s), verdict
    except TimeoutError:
        return error_result("timeout", f"{call.name} timed out"), verdict
    except Exception:
        logger.exception("tool %s failed", call.name)
        return error_result("tool_failed", f"{call.name} failed"), verdict


async def _run_call(
    ctx: RunContext, registry: ToolRegistry, call: ToolCall, allowed: bool, parent: str | None
) -> tuple[ChatMessage, str]:
    async with ctx.steps.step("tool", call.name, call.arguments_json, parent) as step:
        if allowed:
            result, verdict = await _invoke(ctx, registry, call, step.id)
        else:
            result, verdict = error_result("budget", "skipped: tool-call limit reached"), "ok"
            step.status = "skipped"
        if not result.ok and step.status == "ok":
            step.status = "error"
        step.output_summary = result.summary
    message = ChatMessage("tool", wrap_tool_output(call.name, result.content), tool_call_id=call.id)
    return message, verdict


def make_tools_node(ctx: RunContext, registry: ToolRegistry) -> Node:
    async def tools_node(state: RunState) -> dict:
        await ctx.cancel.check()
        calls = state.get("pending_calls", ())
        allowance = ctx.budget.remaining_tool_calls()
        parent = state.get("llm_step_id")
        outcomes = await asyncio.gather(
            *(_run_call(ctx, registry, c, i < allowance, parent) for i, c in enumerate(calls))
        )
        update: dict = {"sup_messages": [m for m, _ in outcomes], "pending_calls": ()}
        if any(v == LoopVerdict.STOP for _, v in outcomes):
            update["stop_reason"] = "repeated_tool_calls"
        return update

    return tools_node
