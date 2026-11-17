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
from typing import Any

import asyncpg
import redis.asyncio as aioredis
from eagleeye_agents.analysis.workspace import PgDataWorkspace
from eagleeye_agents.budgets import BudgetLimits
from eagleeye_agents.context import AgentSettings
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_agents.runner import RunnerDeps, execute_run
from eagleeye_agents.sql.gateway_client import HttpGateway
from eagleeye_catalog.repo import CatalogRepo
from eagleeye_catalog.service import CatalogService
from eagleeye_core.app_cache import AppCache
from eagleeye_core.config import Settings, get_settings
from eagleeye_core.service_auth import resolve_secret
from eagleeye_core.storage import S3ObjectStore, build_object_store
from eagleeye_llm.embeddings import CachingEmbedder
from eagleeye_llm.factory import build_embedder, build_llm
from eagleeye_retrieval.service import Retriever
from eagleeye_retrieval.stores.pgvector_store import PgVectorPersonalStore
from eagleeye_retrieval.stores.qdrant_store import QdrantEnterpriseStore, build_qdrant_client
from eagleeye_sandbox.factory import build_executor

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_deps: RunnerDeps | None = None


async def _create_pool(dsn: str, max_size: int) -> asyncpg.Pool:
    async def _init(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    return await asyncpg.create_pool(dsn, min_size=1, max_size=max_size, init=_init)


def agent_settings(s: Settings) -> AgentSettings:
    return AgentSettings(
        limits=BudgetLimits(
            max_steps=s.agent_max_steps,
            max_tool_calls=s.agent_max_tool_calls,
            max_cost_usd=s.agent_max_cost_usd,
            max_seconds=float(s.agent_max_seconds),
        ),
        rag_min_score=s.rag_min_score,
        analysis_max_seconds=float(s.agent_max_seconds_analysis),
        notebook_max_seconds=float(s.agent_max_seconds_notebook),
        demo_notebook_runs=s.demo_notebook_runs,
    )


def _analysis(s: Settings, pool: asyncpg.Pool) -> tuple[PgDataWorkspace | None, Any]:
    """Data files need only the object stores; analysis also needs the Docker sandbox, which
    is probed per run (so starting Docker later turns analysis on without a restart)."""
    if not s.enable_analysis:
        return None, None
    artifacts = S3ObjectStore.from_settings(s, s.artifacts_bucket)
    workspace = PgDataWorkspace(pool, build_object_store(), artifacts)
    executor = build_executor(s, s.sandbox_mem_mb, s.sandbox_timeout_s)
    return workspace, executor


async def _build_deps(s: Settings) -> RunnerDeps:
    pool = await _create_pool(s.database_url, s.db_pool_max_worker)
    redis = aioredis.from_url(s.redis_url, socket_connect_timeout=5)
    llm = build_llm(s)
    qdrant = build_qdrant_client(s)
    cache = AppCache(redis, s.app_cache_ttl_s, s.app_cache_enabled)
    embedder = build_embedder(s)
    # searches reuse cached query vectors; the catalog keeps the plain embedder
    query_embedder = CachingEmbedder(embedder, cache, s.embed_model) if cache.enabled else embedder
    gateway, catalog = None, None
    if s.enable_sql:
        # The worker never holds warehouse credentials: it signs tokens and calls the gateway.
        gateway = HttpGateway(s.gateway_url, resolve_secret(s.gateway_hmac_secret, s.app_env))
        catalog = CatalogService(CatalogRepo(pool), embedder)
    workspace, executor = _analysis(s, pool)
    notebook_executor = (
        build_executor(s, s.notebook_sandbox_mem_mb, s.notebook_sandbox_timeout_s)
        if executor is not None and s.enable_notebook_mode
        else None
    )
    retriever = Retriever(
        pool=pool,
        llm=llm,
        embedder=query_embedder,
        enterprise_store=QdrantEnterpriseStore(qdrant, s.qdrant_collection, s.embed_dim),
        personal_store=PgVectorPersonalStore(pool),
        top_k=s.rag_top_k,
        min_score=s.rag_min_score,
        cache=cache if cache.enabled else None,
        rerank_candidates=s.rag_rerank_candidates,
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
        workspace=workspace,
        executor=executor,
        notebook_executor=notebook_executor,
        python_analysis=s.enable_python_analysis,
        sandbox_runs_per_hour=s.sandbox_runs_per_hour,
        cache=cache if cache.enabled else None,
        figure_loader=build_object_store().get if s.rag_figures_to_model else None,
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
