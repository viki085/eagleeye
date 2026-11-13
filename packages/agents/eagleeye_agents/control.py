"""Run control: cancellation, usage metering, and the user-visible text channel."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from eagleeye_events.names import TEXT_DELTA, TEXT_REPLACE
from eagleeye_llm.gateway import Usage

from eagleeye_agents.errors import RunCancelledError
from eagleeye_agents.steps import Sink

CANCEL_POLL_S = 0.5
SEGMENT_SEP = "\n\n"


class CancelToken:
    """Polls an async flag source (Redis key) at most every CANCEL_POLL_S."""

    def __init__(
        self,
        is_set: Callable[[], Awaitable[bool]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._is_set = is_set
        self._clock = clock
        self._last_poll = float("-inf")
        self._cancelled = False

    async def check(self) -> None:
        if not self._cancelled and self._clock() - self._last_poll >= CANCEL_POLL_S:
            self._last_poll = self._clock()
            self._cancelled = await self._is_set()
        if self._cancelled:
            raise RunCancelledError


@dataclass(frozen=True)
class UsageEntry:
    model_id: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


class UsageMeter:
    def __init__(self) -> None:
        self._entries: list[UsageEntry] = []
        self._degraded = False

    def add(self, usage: Usage) -> None:
        if not usage.model_id and not usage.tokens_in and not usage.tokens_out:
            return
        self._entries.append(
            UsageEntry(
                usage.model_id or "unknown", usage.tokens_in, usage.tokens_out, usage.cost_usd
            )
        )
        self._degraded = self._degraded or usage.degraded

    @property
    def entries(self) -> tuple[UsageEntry, ...]:
        return tuple(self._entries)

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def cost_usd(self) -> float:
        return round(sum(e.cost_usd for e in self._entries), 6)

    @property
    def tokens_in(self) -> int:
        return sum(e.tokens_in for e in self._entries)

    @property
    def tokens_out(self) -> int:
        return sum(e.tokens_out for e in self._entries)


class TextChannel:
    """Everything streamed to the user; the persisted answer is exactly this text,
    so the client's fold and the stored message always agree."""

    def __init__(self, sink: Sink) -> None:
        self._sink = sink
        self._pieces: list[str] = []
        self._new_segment = False
        self.first_emit_at: datetime | None = None  # time-to-first-token for the admin console

    @property
    def value(self) -> str:
        return "".join(self._pieces)

    def begin_segment(self) -> None:
        """Next text starts a new paragraph (e.g. a later supervisor turn)."""
        self._new_segment = True

    async def emit(self, text: str) -> None:
        if not text:
            return
        if self._new_segment and self._pieces:
            text = SEGMENT_SEP + text.lstrip()
        self._new_segment = False
        if self.first_emit_at is None:
            self.first_emit_at = datetime.now(UTC)
        self._pieces.append(text)
        await self._sink.emit(TEXT_DELTA, {"text": text})

    async def replace(self, text: str) -> None:
        self._pieces = [text]
        await self._sink.emit(TEXT_REPLACE, {"text": text})
