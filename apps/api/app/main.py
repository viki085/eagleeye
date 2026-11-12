import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eagleeye_core.config import get_settings
from eagleeye_llm.litellm_adapter import LiteLLMGateway

from app.db import create_pool
from app.routers import chats, health, me, runs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _export_provider_keys() -> None:
    """litellm reads provider keys from os.environ; mirror them from Settings."""
    settings = get_settings()
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _export_provider_keys()
    app.state.pool = await create_pool()
    # socket_timeout=None: redis-py 8 defaults to 5 s, which would kill blocked XREADs
    app.state.redis = aioredis.from_url(
        settings.redis_url, socket_timeout=None, socket_connect_timeout=5
    )
    app.state.llm = LiteLLMGateway(settings.model_fast, settings.model_capable)
    app.state.run_tasks = {}
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.pool.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="EagleEye API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )
    app.include_router(health.router, prefix="/v1")
    app.include_router(me.router, prefix="/v1")
    app.include_router(chats.router, prefix="/v1")
    app.include_router(runs.router, prefix="/v1")
    return app


app = create_app()
