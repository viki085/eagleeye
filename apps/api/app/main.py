import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from eagleeye_core.config import Settings, get_settings
from eagleeye_core.storage import build_object_store
from eagleeye_llm.embeddings import LiteLLMEmbedder
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from eagleeye_retrieval.service import Retriever
from eagleeye_retrieval.stores.pgvector_store import PgVectorPersonalStore
from eagleeye_retrieval.stores.qdrant_store import QdrantEnterpriseStore
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import AsyncQdrantClient

from app.db import create_pool
from app.errors import install_error_handlers
from app.routers import chats, documents, health, me, runs
from app.services.ingest_queue import CeleryIngestQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def _prepare_storage(app: FastAPI) -> None:
    """Bucket + collection are created idempotently. If either backend is down the API
    still starts (the status page reports it); uploads/retrieval fail cleanly meanwhile."""
    try:
        await app.state.store.ensure_bucket()
    except Exception:
        logger.warning("object store not ready; uploads will fail until it is", exc_info=True)
    try:
        await app.state.enterprise_store.ensure_collection()
    except Exception:
        logger.warning("qdrant not ready; enterprise retrieval degraded", exc_info=True)


def _build_rag(app: FastAPI, settings: Settings) -> None:
    state = app.state
    state.store = build_object_store()
    state.ingest_queue = CeleryIngestQueue(settings.redis_url)
    state.qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    state.enterprise_store = QdrantEnterpriseStore(
        state.qdrant, settings.qdrant_collection, settings.embed_dim
    )
    state.retriever = Retriever(
        pool=state.pool,
        llm=state.llm,
        embedder=LiteLLMEmbedder(settings.embed_model, settings.embed_dim),
        enterprise_store=state.enterprise_store,
        personal_store=PgVectorPersonalStore(state.pool),
        top_k=settings.rag_top_k,
        min_score=settings.rag_min_score,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    export_provider_keys(settings.openai_api_key, settings.anthropic_api_key)
    app.state.pool = await create_pool()
    # socket_timeout=None: redis-py 8 defaults to 5 s, which would kill blocked XREADs
    app.state.redis = aioredis.from_url(
        settings.redis_url, socket_timeout=None, socket_connect_timeout=5
    )
    app.state.llm = LiteLLMGateway(settings.model_fast, settings.model_capable)
    app.state.run_tasks = {}
    _build_rag(app, settings)
    await _prepare_storage(app)
    try:
        yield
    finally:
        await app.state.qdrant.close()
        await app.state.redis.aclose()
        await app.state.pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="EagleEye API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )
    install_error_handlers(app)
    for router in (health.router, me.router, chats.router, runs.router, documents.router):
        app.include_router(router, prefix="/v1")
    return app


app = create_app()
