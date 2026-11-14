from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Tier = Literal["fast", "capable"]
Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ToolSpec:
    """A function the model may call. `parameters` is a JSON Schema object."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model_id: str = ""
    degraded: bool = False  # answered by a fallback model
    cached_tokens: int = 0  # part of tokens_in served from the provider's prompt cache


@dataclass(frozen=True)
class StreamChunk:
    """One streamed delta. `done=True` carries final usage + any tool calls, no text."""

    text: str = ""
    done: bool = False
    usage: Usage = field(default_factory=Usage)
    model_id: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


class LLMGateway(Protocol):
    """Port: business logic depends on this, never on a provider SDK."""

    def stream(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        max_tokens: int = 2048,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamChunk]: ...

    async def complete(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        max_tokens: int = 1024,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> tuple[str, Usage]: ...
