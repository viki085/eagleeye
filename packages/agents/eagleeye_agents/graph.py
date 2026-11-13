"""guard ─┬─ blocked ────────────────────────────────► finalize
          └─ route ─┬─ simple ──► simple ─────────────► finalize
                    ├─ rag / rag_auto ─► rag ─────────► finalize
                    ├─ sql ─► sql (SQL sub-agent) ────► finalize
                    └─ supervisor ⇄ tools ────────────► finalize
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from eagleeye_agents.context import RunContext
from eagleeye_agents.nodes.answer import make_rag_node, make_simple_node
from eagleeye_agents.nodes.finalize import make_finalize_node
from eagleeye_agents.nodes.guard import make_guard_node
from eagleeye_agents.nodes.sql_answer import make_sql_node
from eagleeye_agents.nodes.supervisor import make_supervisor_node, make_tools_node
from eagleeye_agents.state import RunState
from eagleeye_agents.tools.registry import ToolRegistry, default_registry

RECURSION_LIMIT = 60

_ROUTE_TO_NODE = {
    "blocked": "finalize",
    "simple": "simple",
    "rag": "rag",
    "rag_auto": "rag",
    "sql": "sql",
    "supervisor": "supervisor",
}


def _after_guard(state: RunState) -> str:
    return _ROUTE_TO_NODE[state["route"]]


def _after_supervisor(state: RunState) -> str:
    return "tools" if state.get("pending_calls") else "finalize"


def build_graph(ctx: RunContext, registry: ToolRegistry | None = None) -> Any:
    tools = registry or default_registry(include_sql=ctx.sql_available)
    g = StateGraph(RunState)
    g.add_node("guard", make_guard_node(ctx))
    g.add_node("simple", make_simple_node(ctx))
    g.add_node("rag", make_rag_node(ctx))
    g.add_node("sql", make_sql_node(ctx))
    g.add_node("supervisor", make_supervisor_node(ctx, tools))
    g.add_node("tools", make_tools_node(ctx, tools))
    g.add_node("finalize", make_finalize_node(ctx))
    g.add_edge(START, "guard")
    g.add_conditional_edges(
        "guard", _after_guard, ["finalize", "simple", "rag", "sql", "supervisor"]
    )
    g.add_edge("simple", "finalize")
    g.add_edge("rag", "finalize")
    g.add_edge("sql", "finalize")
    g.add_conditional_edges("supervisor", _after_supervisor, ["tools", "finalize"])
    g.add_edge("tools", "supervisor")
    g.add_edge("finalize", END)
    return g.compile()


async def run_graph(
    ctx: RunContext, initial: RunState, registry: ToolRegistry | None = None
) -> RunState:
    graph = build_graph(ctx, registry)
    return await graph.ainvoke(initial, config={"recursion_limit": RECURSION_LIMIT})
