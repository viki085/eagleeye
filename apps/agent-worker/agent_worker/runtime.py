"""One shared asyncio loop for the whole worker process.

Celery's thread pool gives concurrency, but async clients (asyncpg pool, redis, and
LiteLLM's process-wide cached HTTP client) are bound to the loop that created them.
Per-thread loops therefore hang when a cached client is reused from another loop.
Instead, a single background thread owns the loop and all clients; Celery threads
submit runs to it and wait. Runs still execute concurrently on that loop.
"""

import asyncio
import json
import threading
from concurrent.futures import Future

import asyncpg
import redis.asyncio as aioredis
from eagleeye_agents.budgets import BudgetLimits
from eagleeye_agents.context import AgentSettings
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_agents.runner import RunnerDeps, execute_run
from eagleeye_agents.sql.gateway_client import HttpGateway
from eagleeye_catalog.repo import CatalogRepo
from eagleeye_catalog.service import CatalogService
from eagleeye_core.config import Settings, get_settings
from eagleeye_core.service_auth import resolve_secret
from eagleeye_llm.embeddings import LiteLLMEmbedder
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from eagleeye_retrieval.service import Retriever
from eagleeye_retrieval.stores.pgvector_store import PgVectorPersonalStore
from eagleeye_retrieval.stores.qdrant_store import QdrantEnterpriseStore
from qdrant_client import AsyncQdrantClient

POOL_MAX_SIZE = 10

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_deps: RunnerDeps | None = None


async def _create_pool(dsn: str) -> asyncpg.Pool:
    async def _init(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    return await asyncpg.create_pool(dsn, min_size=1, max_size=POOL_MAX_SIZE, init=_init)


def agent_settings(s: Settings) -> AgentSettings:
    return AgentSettings(
        limits=BudgetLimits(
            max_steps=s.agent_max_steps,
            max_tool_calls=s.agent_max_tool_calls,
            max_cost_usd=s.agent_max_cost_usd,
            max_seconds=float(s.agent_max_seconds),
        ),
        rag_min_score=s.rag_min_score,
    )


async def _build_deps(s: Settings) -> RunnerDeps:
    pool = await _create_pool(s.database_url)
    redis = aioredis.from_url(s.redis_url, socket_connect_timeout=5)
    llm = LiteLLMGateway(
        s.model_fast,
        s.model_capable,
        s.model_fast_fallback,
        s.model_capable_fallback,
        reasoning_fast=s.reasoning_effort_fast,
        reasoning_capable=s.reasoning_effort_capable,
    )
    qdrant = AsyncQdrantClient(url=s.qdrant_url)
    embedder = LiteLLMEmbedder(s.embed_model, s.embed_dim)
    gateway, catalog = None, None
    if s.enable_sql:
        # The worker never holds warehouse credentials: it signs tokens and calls the gateway.
        gateway = HttpGateway(s.gateway_url, resolve_secret(s.gateway_hmac_secret, s.app_env))
        catalog = CatalogService(CatalogRepo(pool), embedder)
    retriever = Retriever(
        pool=pool,
        llm=llm,
        embedder=embedder,
        enterprise_store=QdrantEnterpriseStore(qdrant, s.qdrant_collection, s.embed_dim),
        personal_store=PgVectorPersonalStore(pool),
        top_k=s.rag_top_k,
        min_score=s.rag_min_score,
    )
    return RunnerDeps(
        pool=pool,
        redis=redis,
        llm=llm,
        retriever=retriever,
        settings=agent_settings(s),
        prompts=load_prompts(),
        model_ids={
            "fast": s.model_fast,
            "capable": s.model_capable,
            "reasoning_fast": s.reasoning_effort_fast,
            "reasoning_capable": s.reasoning_effort_capable,
        },
        gateway=gateway,
        catalog=catalog,
    )


def _ensure_started() -> tuple[asyncio.AbstractEventLoop, RunnerDeps]:
    global _loop, _deps
    with _lock:
        if _loop is None or _deps is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="agent-loop", daemon=True).start()
            _deps = asyncio.run_coroutine_threadsafe(_build_deps(get_settings()), loop).result()
            _loop = loop
        return _loop, _deps


def run_agent(run_id: str) -> None:
    """Called from a Celery thread; blocks that thread until the run finishes."""
    loop, deps = _ensure_started()
    future: Future[None] = asyncio.run_coroutine_threadsafe(execute_run(deps, run_id), loop)
    future.result()
