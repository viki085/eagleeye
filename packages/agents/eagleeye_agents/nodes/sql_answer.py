"""Direct `sql` route: SQL sub-agent, then one answer turn grounded in the result."""

from eagleeye_llm.gateway import ChatMessage

from eagleeye_agents.context import RunContext
from eagleeye_agents.nodes.answer import MAX_HISTORY_MESSAGES
from eagleeye_agents.nodes.guard import Node
from eagleeye_agents.nodes.supervisor import wrap_tool_output
from eagleeye_agents.sql.agent import run_sql_agent
from eagleeye_agents.state import RunState
from eagleeye_agents.streaming import stream_turn
from eagleeye_agents.tools.query_database import outcome_text, register_artifact


def make_sql_node(ctx: RunContext) -> Node:
    async def sql_node(state: RunState) -> dict:
        await ctx.cancel.check()
        question = state["question"]
        async with ctx.steps.step("tool", "query_database", question) as step:
            outcome = await run_sql_agent(ctx, question, None, step.id)
            await register_artifact(ctx, outcome)
            step.status = "ok" if outcome.status in ("ok", "clarify") else "error"
            step.output_summary = (
                f"{outcome.artifact.row_count} rows" if outcome.artifact else outcome.status
            )
        if outcome.status != "ok":
            # clarify / no access / failure: a plain, deterministic reply (no figures to invent)
            await ctx.text.emit(outcome.message)
            return {"grounded": False}
        history = state.get("history", [])[-MAX_HISTORY_MESSAGES:]
        messages = [
            ChatMessage("system", ctx.prompts.text("sql_answer")),
            *history,
            ChatMessage(
                "user",
                f"{question}\n\n{wrap_tool_output('query_database', outcome_text(outcome))}",
            ),
        ]
        await stream_turn(ctx, "answer", messages)
        return {"grounded": False}

    return sql_node
