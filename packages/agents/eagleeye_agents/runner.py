"""One agent run: claim → graph → persist → run.done. Called by the agent worker."""

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

import asyncpg
import redis.asyncio as aioredis
from eagleeye_events import EventSink, cancel_key
from eagleeye_events.names import CHAT_UPDATED, RUN_DONE, RUN_ERROR, RUN_STARTED
from eagleeye_llm.gateway import LLMGateway

from eagleeye_agents import persistence
from eagleeye_agents.context import AgentSettings, RetrieverPort, RunContext
from eagleeye_agents.control import CancelToken
from eagleeye_agents.errors import RunCancelledError
from eagleeye_agents.graph import run_graph
from eagleeye_agents.prompts.loader import Prompts
from eagleeye_agents.state import RunState
from eagleeye_agents.titles import maybe_title

logger = logging.getLogger(__name__)

HEARTBEAT_S = 10
WATCH_INTERVAL_S = 0.5
DEADLINE_GRACE_S = 30.0  # beyond AGENT_MAX_SECONDS: room for the final answer turn
FAILURE_MESSAGE = "Something went wrong answering. Try again."
TIMEOUT_MESSAGE = "This took too long and was stopped. Try again or simplify the question."


@dataclass(frozen=True)
class RunnerDeps:
    pool: asyncpg.Pool
    redis: aioredis.Redis
    llm: LLMGateway
    retriever: RetrieverPort
    settings: AgentSettings
    prompts: Prompts
    model_ids: dict[str, str]


@dataclass(frozen=True)
class Outcome:
    status: str
    route: str | None
    guard: dict | None
    citations: list[dict]
    cancelled: bool = False


async def _heartbeat_loop(pool: asyncpg.Pool, run_id: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        with suppress(Exception):
            await persistence.heartbeat(pool, run_id)


def _parts(ctx: RunContext, outcome: Outcome) -> list[dict]:
    parts: list[dict] = [{"type": "text", "text": ctx.text.value}]
    if outcome.citations:
        parts.append({"type": "citations", "items": outcome.citations})
    parts.append({"type": "steps", "items": [r.compact() for r in ctx.steps.records]})
    parts.append(
        {
            "type": "run",
            "status": outcome.status,
            "route": outcome.route,
            "degraded": ctx.usage.degraded,
        }
    )
    return parts


class RunTimeoutError(Exception):
    """The run exceeded its hard wall-clock deadline (e.g. a provider call hung)."""


async def _supervise(ctx: RunContext, initial: RunState, deadline_s: float) -> RunState:
    """Run the graph as a task and watch it: Stop or the hard deadline cancels it
    immediately, even in the middle of an LLM or tool call."""
    task = asyncio.create_task(run_graph(ctx, initial))
    started = time.monotonic()
    while True:
        done, _ = await asyncio.wait({task}, timeout=WATCH_INTERVAL_S)
        if done:
            return task.result()
        reason: BaseException | None = None
        try:
            await ctx.cancel.check()
        except RunCancelledError as exc:
            reason = exc
        if reason is None and time.monotonic() - started > deadline_s:
            reason = RunTimeoutError(f"run exceeded {deadline_s:.0f}s")
        if reason is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, RunCancelledError):
                await task
            raise reason


async def _execute_graph(ctx: RunContext, initial: RunState) -> Outcome:
    deadline = ctx.settings.limits.max_seconds + DEADLINE_GRACE_S
    try:
        final = await _supervise(ctx, initial, deadline)
    except RunCancelledError:
        return Outcome("CANCELLED", None, None, [], cancelled=True)
    guard = final.get("guard")
    return Outcome(
        final.get("status", "SUCCEEDED"),
        final.get("route"),
        guard.to_dict() if guard is not None else None,
        final.get("citations", []),
    )


async def _persist(deps: RunnerDeps, ctx: RunContext, outcome: Outcome) -> str:
    message_id = await persistence.insert_assistant_message(
        deps.pool,
        ctx.chat_id,
        ctx.run_id,
        _parts(ctx, outcome),
        ctx.usage.tokens_in,
        ctx.usage.tokens_out,
    )
    await persistence.insert_steps(deps.pool, ctx.run_id, ctx.steps.records)
    await persistence.insert_usage(deps.pool, ctx.user_id, ctx.run_id, ctx.usage.entries)
    await persistence.finish_run(
        deps.pool,
        ctx.run_id,
        status=outcome.status,
        route=outcome.route,
        guard=outcome.guard,
        degraded=ctx.usage.degraded,
        cost_usd=ctx.usage.cost_usd,
        usage={"tokens_in": ctx.usage.tokens_in, "tokens_out": ctx.usage.tokens_out},
    )
    return message_id


def _build_context(deps: RunnerDeps, run: asyncpg.Record, sink: EventSink) -> RunContext:
    run_id = str(run["id"])

    async def cancel_requested() -> bool:
        return bool(await deps.redis.exists(cancel_key(run_id)))

    return RunContext.create(
        run_id=run_id,
        chat_id=str(run["chat_id"]),
        user_id=str(run["user_id"]),
        llm=deps.llm,
        retriever=deps.retriever,
        store=persistence.PgRunStore(deps.pool),
        sink=sink,
        cancel=CancelToken(cancel_requested),
        prompts=deps.prompts,
        settings=deps.settings,
    )


async def _fail(
    deps: RunnerDeps, ctx: RunContext, sink: EventSink, timed_out: bool = False
) -> None:
    logger.exception("run %s failed", ctx.run_id)
    code, message = ("TIMEOUT", TIMEOUT_MESSAGE) if timed_out else ("RUN_ERROR", FAILURE_MESSAGE)
    with suppress(Exception):
        await persistence.insert_steps(deps.pool, ctx.run_id, ctx.steps.records)
        await persistence.insert_usage(deps.pool, ctx.user_id, ctx.run_id, ctx.usage.entries)
    await persistence.finish_run(
        deps.pool,
        ctx.run_id,
        status="FAILED",
        route=None,
        guard=None,
        degraded=ctx.usage.degraded,
        cost_usd=ctx.usage.cost_usd,
        usage={},
        error_code=code,
    )
    await sink.emit(RUN_ERROR, {"code": code, "user_message": message})


async def execute_run(
    deps: RunnerDeps, run_id: str, sink_factory: Callable[[str], EventSink] | None = None
) -> None:
    run = await persistence.load_run(deps.pool, run_id)
    if run is None or not await persistence.claim_run(
        deps.pool, run_id, deps.model_ids, deps.prompts.versions()
    ):
        logger.info("run %s missing or already claimed; skipping", run_id)
        return
    sink = (sink_factory or (lambda rid: EventSink(deps.redis, rid)))(run_id)
    ctx = _build_context(deps, run, sink)
    beat = asyncio.create_task(_heartbeat_loop(deps.pool, run_id))
    try:
        await sink.emit(RUN_STARTED, {"run_id": run_id})
        question, history = await persistence.load_conversation(deps.pool, ctx.chat_id, run_id)
        doc_ids = [str(d) for d in (run["params"] or {}).get("doc_ids", [])]
        initial: RunState = {"question": question, "history": history, "doc_ids": doc_ids}
        outcome = await _execute_graph(ctx, initial)
        # Title before persisting so its tokens/cost are included in the usage ledger.
        title = await maybe_title(
            deps.pool, deps.llm, ctx.chat_id, ctx.user_id, question, history, ctx.usage
        )
        message_id = await _persist(deps, ctx, outcome)
        if title is not None:
            await sink.emit(CHAT_UPDATED, {"chat_id": ctx.chat_id, "title": title})
        await sink.emit(
            RUN_DONE,
            {
                "message_id": message_id,
                "status": outcome.status,
                "degraded": ctx.usage.degraded,
                "cancelled": outcome.cancelled,
                "usage": {
                    "in": ctx.usage.tokens_in,
                    "out": ctx.usage.tokens_out,
                    "cost": ctx.usage.cost_usd,
                },
            },
        )
    except RunTimeoutError:
        await _fail(deps, ctx, sink, timed_out=True)
    except Exception:
        await _fail(deps, ctx, sink)
    finally:
        beat.cancel()
        with suppress(Exception):
            await deps.redis.delete(cancel_key(run_id))
