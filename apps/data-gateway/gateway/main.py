"""Data Gateway: internal FastAPI service (port 8100). Not exposed to browsers.

uv run --package eagleeye-data-gateway \
    uvicorn gateway.main:app --app-dir apps/data-gateway --port 8100
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated

import asyncpg
from eagleeye_catalog.repo import CatalogRepo
from eagleeye_catalog.service import CatalogService
from eagleeye_core.config import get_settings
from eagleeye_core.logs import configure_logging
from eagleeye_core.service_auth import ContextToken, TokenError, resolve_secret, verify
from eagleeye_core.storage import S3ObjectStore
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gateway.service import GatewayDeps, GatewayError, execute
from gateway.sources import SourcePools

configure_logging(get_settings(), "gateway")
logger = logging.getLogger(__name__)


class ExecuteBody(BaseModel):
    source_id: str = Field(min_length=1, max_length=64)
    sql: str = Field(min_length=1, max_length=8000)
    title: str = Field(default="Query result", max_length=200)


async def _meta_pool(dsn: str) -> asyncpg.Pool:
    async def _init(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    return await asyncpg.create_pool(
        dsn, min_size=1, max_size=get_settings().db_pool_max_gateway, init=_init
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.secret = resolve_secret(s.gateway_hmac_secret, s.app_env)  # fails fast in prod
    meta = await _meta_pool(s.database_url)
    store = S3ObjectStore.from_settings(s, s.artifacts_bucket)
    try:
        await store.ensure_bucket()
    except Exception:
        logger.warning("artifacts bucket not ready", exc_info=True)
    sources = SourcePools(s.sql_max_concurrency)
    app.state.deps = GatewayDeps(
        meta, CatalogService(CatalogRepo(meta)), sources, store, s.sql_explain_max_rows
    )
    try:
        yield
    finally:
        await sources.close()
        await meta.close()


app = FastAPI(
    title="EagleEye Data Gateway",
    version="0.4.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def context_token(
    request: Request, x_context_token: Annotated[str | None, Header()] = None
) -> ContextToken:
    if not x_context_token:
        raise GatewayError(401, "UNAUTHENTICATED", "Missing context token.")
    try:
        return verify(request.app.state.secret, x_context_token)
    except TokenError as exc:
        raise GatewayError(401, "UNAUTHENTICATED", "Invalid context token.") from exc


@app.exception_handler(GatewayError)
async def _gateway_error(_req: Request, exc: GatewayError) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "code": exc.code,
            "user_safe_error": exc.user_safe_error,
            "retryable": exc.retryable,
        },
        status_code=exc.status,
    )


@app.get("/health")
async def health(request: Request) -> dict:
    """Gateway liveness + a SELECT 1 per active source (names only; no hosts or DSNs)."""
    deps: GatewayDeps = request.app.state.deps
    repo = CatalogRepo(deps.meta_pool)
    sources: dict[str, str] = {}
    rows = await deps.meta_pool.fetch("SELECT id FROM data_sources WHERE status = 'active'")
    for row in rows:
        source = await repo.get_source(str(row["id"]))
        if source is None:
            continue
        try:
            pool = await deps.sources.pool_for(source)
            await asyncio.wait_for(pool.fetchval("SELECT 1"), timeout=3)
            sources[source.name] = "up"
        except Exception as exc:  # noqa: BLE001 - report, never raise from health
            sources[source.name] = type(exc).__name__
    return {"ok": True, "sources": sources}


@app.post("/execute")
async def execute_sql(
    body: ExecuteBody, request: Request, token: Annotated[ContextToken, Depends(context_token)]
) -> dict:
    if token.source_id != body.source_id:
        raise GatewayError(401, "UNAUTHENTICATED", "Token does not match the requested source.")
    return await execute(request.app.state.deps, token, body.sql, body.title)
