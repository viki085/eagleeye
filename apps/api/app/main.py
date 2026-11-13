import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from eagleeye_catalog.repo import CatalogRepo
from eagleeye_catalog.service import CatalogService
from eagleeye_core.config import get_settings
from eagleeye_core.storage import S3ObjectStore, build_object_store
from eagleeye_retrieval.stores.qdrant_store import QdrantEnterpriseStore
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import AsyncQdrantClient

from app.db import create_pool
from app.errors import install_error_handlers
from app.routers import artifacts, chats, documents, health, me, runs, sources
from app.services.task_queue import CeleryTaskQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def _prepare_storage(app: FastAPI) -> None:
    """Bucket + collection are created idempotently. If either backend is down the API
    still starts (the status page reports it); uploads/deletes fail cleanly meanwhile."""
    try:
        await app.state.store.ensure_bucket()
    except Exception:
        logger.warning("object store not ready; uploads will fail until it is", exc_info=True)
    try:
        await app.state.enterprise_store.ensure_collection()
    except Exception:
        logger.warning("qdrant not ready; enterprise documents degraded", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The API authenticates, admits runs, enqueues and streams; agents run in the
    agent worker (Phase 3), ingestion in the ingest worker."""
    settings = get_settings()
    state = app.state
    state.pool = await create_pool()
    # socket_timeout=None: redis-py 8 defaults to 5 s, which would kill blocked XREADs
    state.redis = aioredis.from_url(
        settings.redis_url, socket_timeout=None, socket_connect_timeout=5
    )
    state.task_queue = CeleryTaskQueue(settings.redis_url)
    state.store = build_object_store()
    state.qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    state.enterprise_store = QdrantEnterpriseStore(
        state.qdrant, settings.qdrant_collection, settings.embed_dim
    )
    # Phase 4: catalog metadata (no warehouse credentials here) + result-table reader
    state.catalog = CatalogService(CatalogRepo(state.pool))
    state.artifact_store = S3ObjectStore(
        settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key,
        settings.artifacts_bucket,
    )
    await _prepare_storage(app)
    try:
        yield
    finally:
        await state.qdrant.close()
        await state.redis.aclose()
        await state.pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="EagleEye API", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )
    install_error_handlers(app)
    for router in (
        health.router, me.router, chats.router, runs.router, documents.router,
        sources.router, artifacts.router,
    ):
        app.include_router(router, prefix="/v1")
    return app


app = create_app()
