"""Step tree: every guard / LLM / tool / check emits step.started + step.finished
(with parent_id) for the UI and is kept for `run_steps` persistence."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from eagleeye_events.names import STEP_FINISHED, STEP_STARTED
from eagleeye_llm.gateway import Usage

from eagleeye_agents.errors import RunCancelledError

logger = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 200


class Sink(Protocol):
    async def emit(self, event: str, data: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class StepRecord:
    id: str
    parent_id: str | None
    seq: int
    kind: str
    name: str
    input_summary: str
    status: str
    output_summary: str
    duration_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float

    def compact(self) -> dict[str, Any]:
        """Shape persisted in the message `steps` part (survives reload)."""
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "name": self.name,
            "input_summary": self.input_summary,
            "status": self.status,
            "output_summary": self.output_summary,
            "duration_ms": self.duration_ms,
        }


@dataclass
class StepHandle:
    """Mutable while the step runs; frozen into a StepRecord when it finishes."""

    id: str
    output_summary: str = ""
    status: str = "ok"
    usage: Usage = field(default_factory=Usage)


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_SUMMARY_CHARS else flat[: MAX_SUMMARY_CHARS - 1] + "…"


class StepRecorder:
    def __init__(self, sink: Sink, clock: Callable[[], float] = time.monotonic) -> None:
        self._sink = sink
        self._clock = clock
        self._records: list[StepRecord] = []
        self._seq = 0

    @property
    def records(self) -> tuple[StepRecord, ...]:
        return tuple(sorted(self._records, key=lambda r: r.seq))

    @asynccontextmanager
    async def step(
        self, kind: str, name: str, input_summary: str = "", parent_id: str | None = None
    ) -> AsyncIterator[StepHandle]:
        handle = StepHandle(id=str(uuid.uuid4()))
        seq = self._seq
        self._seq += 1
        started = self._clock()
        summary = _clip(input_summary)
        await self._sink.emit(
            STEP_STARTED,
            {
                "step_id": handle.id,
                "parent_id": parent_id,
                "kind": kind,
                "name": name,
                "input_summary": summary,
            },
        )
        try:
            yield handle
        except (RunCancelledError, asyncio.CancelledError):
            handle.status = "skipped"
            handle.output_summary = "stopped"
            raise
        except BaseException:
            handle.status = "error"
            handle.output_summary = handle.output_summary or "failed"
            raise
        finally:
            await self._finish(handle, seq, kind, name, summary, parent_id, started)

    async def _finish(
        self,
        h: StepHandle,
        seq: int,
        kind: str,
        name: str,
        summary: str,
        parent_id: str | None,
        started: float,
    ) -> None:
        record = StepRecord(
            id=h.id,
            parent_id=parent_id,
            seq=seq,
            kind=kind,
            name=name,
            input_summary=summary,
            status=h.status,
            output_summary=_clip(h.output_summary),
            duration_ms=int((self._clock() - started) * 1000),
            tokens_in=h.usage.tokens_in,
            tokens_out=h.usage.tokens_out,
            cost_usd=h.usage.cost_usd,
        )
        self._records.append(record)
        try:
            await self._sink.emit(
                STEP_FINISHED,
                {
                    "step_id": record.id,
                    "status": record.status,
                    "output_summary": record.output_summary,
                    "duration_ms": record.duration_ms,
                    "tokens": record.tokens_in + record.tokens_out,
                    "cost": record.cost_usd,
                },
            )
        except Exception:  # never mask the step's own outcome
            logger.warning("could not emit step.finished for %s", record.id, exc_info=True)
