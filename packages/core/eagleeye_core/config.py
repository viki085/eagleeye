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
    model_fast: str = "gpt-4o-mini"
    model_capable: str = "gpt-4o"

    clerk_secret_key: str = ""
    clerk_publishable_key: str = Field(
        default="", validation_alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
    )
    clerk_issuer: str = ""  # optional pin, e.g. https://xxx.clerk.accounts.dev


@lru_cache
def get_settings() -> Settings:
    return Settings()
