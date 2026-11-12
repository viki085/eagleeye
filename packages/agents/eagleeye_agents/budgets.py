"""Hard run budgets + loop detection (C3 §2.3). Pure apart from the injected clock."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BudgetLimits:
    max_steps: int = 14  # supervisor LLM turns
    max_tool_calls: int = 12
    max_cost_usd: float = 0.25
    max_seconds: float = 120.0


class LoopVerdict:
    OK = "ok"
    REPEAT = "repeat"  # same call twice → replace result with a hint
    STOP = "stop"  # same call three times → terminate like a budget breach


def call_signature(name: str, arguments: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(arguments, sort_keys=True, separators=(',', ':'))}"


class BudgetTracker:
    def __init__(self, limits: BudgetLimits, clock: Callable[[], float] = time.monotonic) -> None:
        self._limits = limits
        self._clock = clock
        self._started = clock()
        self._steps = 0
        self._tool_calls = 0
        self._signatures: dict[str, int] = {}
        self._loop_stop = False

    @property
    def tool_calls(self) -> int:
        return self._tool_calls

    def record_step(self) -> None:
        self._steps += 1

    def remaining_tool_calls(self) -> int:
        return max(self._limits.max_tool_calls - self._tool_calls, 0)

    def record_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        self._tool_calls += 1
        sig = call_signature(name, arguments)
        count = self._signatures.get(sig, 0) + 1
        self._signatures[sig] = count
        if count >= 3:
            self._loop_stop = True
            return LoopVerdict.STOP
        return LoopVerdict.REPEAT if count == 2 else LoopVerdict.OK

    def breach(self, cost_usd: float) -> str | None:
        """Reason the run must stop before the next LLM call, or None."""
        if self._loop_stop:
            return "repeated_tool_calls"
        if self._steps >= self._limits.max_steps:
            return "max_steps"
        if self._tool_calls >= self._limits.max_tool_calls:
            return "max_tool_calls"
        if cost_usd >= self._limits.max_cost_usd:
            return "max_cost"
        if self._clock() - self._started >= self._limits.max_seconds:
            return "max_seconds"
        return None
