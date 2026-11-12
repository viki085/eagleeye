from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """12-factor settings. Validated at startup; the app fails fast on missing vars."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"

    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    s3_endpoint_url: str = "http://localhost:8333"
    s3_access_key: str = "eagleeye"
    s3_secret_key: str = "eagleeye-local-secret"
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # Defaults chosen by evals/model_bench.py on 2026-11-12 (ADR-29): equal-or-better quality
    # than gpt-4o-mini / gpt-4o at ~28% / ~51% lower cost.
    model_fast: str = "gpt-6-luna"
    model_capable: str = "gpt-6.1-terra"
    # Used once if the primary fails after retries; answers are flagged "degraded".
    model_fast_fallback: str = "gpt-4o-mini"
    model_capable_fallback: str = "gpt-4o"
    # Reasoning models only (GPT-5/6, o-series): "none" | "minimal" | "low" | "medium" | "high".
    # Empty = provider default. Ignored for classic models such as gpt-4o. "none" = no billed
    # thinking tokens and lowest latency (supported by the GPT-6 luna/terra models).
    reasoning_effort_fast: str = "none"
    reasoning_effort_capable: str = "none"
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 1536

    docs_bucket: str = "eagleeye-local-docs"
    max_upload_mb: int = 25
    qdrant_collection: str = "enterprise_chunks"
    enterprise_upload_open: bool = True  # Phase 2: any user may upload enterprise docs
    rag_top_k: int = 5
    rag_min_score: float = 0.25  # cosine floor below which retrieval is "low relevance"

    # Agent budgets (C3 §2.3), checked before every supervisor LLM call
    agent_max_steps: int = 14
    agent_max_tool_calls: int = 12
    agent_max_cost_usd: float = 0.25
    agent_max_seconds: int = 120
    max_active_runs_per_user: int = 2
    usage_limit_usd: float = 500.0  # lifetime LLM spend cap per user; new runs refused beyond it

    clerk_secret_key: str = ""
    clerk_publishable_key: str = Field(
        default="", validation_alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
    )
    clerk_issuer: str = ""  # optional pin, e.g. https://xxx.clerk.accounts.dev


@lru_cache
def get_settings() -> Settings:
    return Settings()
