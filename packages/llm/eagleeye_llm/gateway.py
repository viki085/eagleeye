from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

Tier = Literal["fast", "capable"]


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class StreamChunk:
    """One streamed delta. `done=True` carries final usage, no text."""

    text: str = ""
    done: bool = False
    usage: Usage = field(default_factory=Usage)
    model_id: str = ""


class LLMGateway(Protocol):
    """Port: business logic depends on this, never on a provider SDK."""

    def stream(
        self, tier: Tier, messages: list[ChatMessage], max_tokens: int = 2048
    ) -> AsyncIterator[StreamChunk]: ...

    async def complete(
        self, tier: Tier, messages: list[ChatMessage], max_tokens: int = 1024
    ) -> tuple[str, Usage]: ...
