"""Rule-based router over the guard verdict + selection state (C3 §2.2). Pure."""

from typing import Literal

from eagleeye_agents.guard.verdict import GuardVerdict

Route = Literal["blocked", "simple", "rag", "rag_auto", "sql", "supervisor"]


def choose_route(verdict: GuardVerdict, has_selection: bool, sql_available: bool = False) -> Route:
    if not verdict.allowed:
        return "blocked"
    if has_selection:
        return "rag"  # the user narrowed to documents: always answer from them
    if verdict.intent == "chitchat":
        return "simple"
    if verdict.intent == "docs" and verdict.complexity == "simple":
        return "rag"
    if verdict.intent == "sql" and verdict.complexity == "simple" and sql_available:
        return "sql"  # one data question: SQL sub-agent + grounded answer, no planning turn
    if verdict.intent == "other" and verdict.complexity == "simple":
        return "rag_auto"  # ground only if retrieval is relevant, else plain answer
    return "supervisor"
