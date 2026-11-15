import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from eagleeye_catalog.repo import CatalogRepo
from eagleeye_catalog.service import CatalogService
from eagleeye_core.config import get_settings
from eagleeye_core.logs import configure_logging
from eagleeye_core.storage import S3ObjectStore, build_object_store
from eagleeye_retrieval.stores.qdrant_store import QdrantEnterpriseStore, build_qdrant_client
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import auth
from app.activity import ActivityMiddleware
from app.db import create_pool
from app.demo import reset_loop
from app.errors import install_error_handlers
from app.request_context import RequestIdLogFilter, RequestIdMiddleware
from app.routers import (
    admin,
    admin_users,
    artifacts,
    chats,
    datasets,
    demo,
    documents,
    health,
    me,
    notebooks,
    runs,
    sources,
)
from app.security import (
    JsonBodyLimitMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.services import queue_metric
from app.services.clerk_admin import ClerkAdmin
from app.services.task_queue import CeleryTaskQueue

configure_logging(get_settings(), "api", [RequestIdLogFilter()])
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
    if settings.loadtest_token_public_key:  # build now: refuse or announce it at boot
        auth.get_verifier()
    state = app.state
    state.pool = await create_pool()
    # socket_timeout=None: redis-py 8 defaults to 5 s, which would kill blocked XREADs
    state.redis = aioredis.from_url(
        settings.redis_url, socket_timeout=None, socket_connect_timeout=5
    )
    state.task_queue = CeleryTaskQueue(settings.redis_url)
    state.clerk_admin = ClerkAdmin(  # admin user management
        settings.clerk_secret_key, settings.clerk_organization_id
    )
    state.store = build_object_store()
    state.qdrant = build_qdrant_client(settings)
    state.enterprise_store = QdrantEnterpriseStore(
        state.qdrant, settings.qdrant_collection, settings.embed_dim
    )
    # Phase 4: catalog metadata (no warehouse credentials here) + result-table reader
    state.catalog = CatalogService(CatalogRepo(state.pool))
    state.artifact_store = S3ObjectStore.from_settings(settings, settings.artifacts_bucket)
    await _prepare_storage(app)
    background = [asyncio.create_task(reset_loop.run_forever(state, settings))]
    if settings.queue_metric_enabled:  # scale mode: agent-worker autoscaling signal
        import boto3

        cloudwatch = boto3.client("cloudwatch", region_name=settings.aws_region)
        background.append(
            asyncio.create_task(
                queue_metric.run_forever(state.pool, cloudwatch, settings.metric_namespace)
            )
        )
    try:
        yield
    finally:
        for task in background:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await state.qdrant.close()
        await state.redis.aclose()
        await state.pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="EagleEye API", version="0.6.0", lifespan=lifespan)
    # Starlette runs the LAST added middleware first:
    # request id → headers → size limit → CORS → crash-to-envelope → routes
    app.add_middleware(UnhandledErrorMiddleware)
    # last activity for the demo machine's idle stop (health checks don't count)
    app.add_middleware(ActivityMiddleware, redis=lambda: getattr(app.state, "redis", None))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(JsonBodyLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    for router in (
        health.router,
        me.router,
        chats.router,
        runs.router,
        documents.router,
        sources.router,
        artifacts.router,
        notebooks.router,
        datasets.router,
        demo.router,
        admin.router,
        admin_users.router,
    ):
        app.include_router(router, prefix="/v1")
    return app


app = create_app()
