"""LangGraph state. Nodes return partial updates; `sup_messages` accumulates."""

import operator
from typing import Annotated, TypedDict

from eagleeye_llm.gateway import ChatMessage, ToolCall

from eagleeye_agents.guard.verdict import GuardVerdict


class RunState(TypedDict, total=False):
    question: str
    history: list[ChatMessage]  # prior turns, oldest first, excluding `question`
    doc_ids: list[str]  # documents the user selected in the UI (already authorised)
    guard: GuardVerdict
    route: str
    grounded: bool  # the answer was expected to cite sources
    sup_messages: Annotated[list[ChatMessage], operator.add]
    pending_calls: tuple[ToolCall, ...]
    llm_step_id: str
    stop_reason: str  # budget breach reason → status BUDGET_EXCEEDED
    status: str
    citations: list[dict]
    cache_hit: bool  # the answer was replayed from the answer cache
