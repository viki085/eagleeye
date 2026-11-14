from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Credentials of the local SeaweedFS container (docker-compose). Fine for a laptop; refused
# anywhere APP_ENV is not "local" (see Settings._no_local_secrets_when_deployed).
LOCAL_S3_ACCESS_KEY = "eagleeye"
LOCAL_S3_SECRET = "eagleeye-local-secret"  # noqa: S105 — local-only default, guarded below


class Settings(BaseSettings):
    """12-factor settings. Validated at startup; the app fails fast on missing vars."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"

    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""  # Qdrant Cloud; empty for the local server
    # Object storage. Local: the S3-compatible server with its keys. AWS: leave the endpoint and
    # both keys empty, and boto3 uses the machine's role (no keys in settings) in aws_region.
    s3_endpoint_url: str = "http://localhost:8333"
    s3_access_key: str = LOCAL_S3_ACCESS_KEY
    s3_secret_key: str = LOCAL_S3_SECRET
    aws_region: str = "us-east-1"
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    # Database connections per process. In the cloud many tasks share Supabase's pooler, so
    # these are lowered there to fit its connection limit.
    db_pool_max_api: int = 10
    db_pool_max_worker: int = 10
    db_pool_max_gateway: int = 5

    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # Defaults chosen by evals/model_bench.py (2026-11-12) and evals/sql_eval.py (2026-11-13),
    # ADR-29/30: luna matched terra on every set at ~1/10 the cost. For harder workloads set
    # MODEL_CAPABLE=gpt-6.1-terra in .env — no code change needed.
    model_fast: str = "gpt-6-luna"
    model_capable: str = "gpt-6-luna"
    # Used once if the primary fails after retries; answers are flagged "degraded".
    model_fast_fallback: str = "gpt-4o-mini"
    model_capable_fallback: str = "gpt-6.1-terra"
    # Reasoning models only (GPT-5/6, o-series): "none" | "minimal" | "low" | "medium" | "high".
    # Empty = provider default. Ignored for classic models such as gpt-4o. "none" = no billed
    # thinking tokens and lowest latency (supported by the GPT-6 luna/terra models).
    reasoning_effort_fast: str = "none"
    reasoning_effort_capable: str = "none"
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 1536
    # Document chunking (chosen with evals/retrieval_eval.py, ADR-32). Changing these only
    # affects new uploads; run `python -m ingest_worker.reindex --all` to re-chunk the rest.
    chunk_max_chars: int = 1600
    chunk_soft_chars: int = 1200
    chunk_min_chars: int = 400
    chunk_overlap_chars: int = 200

    docs_bucket: str = "eagleeye-local-docs"
    max_upload_mb: int = 25
    qdrant_collection: str = "enterprise_chunks"
    # true → every user may add/delete enterprise docs; false → knowledge_admin/admin only
    enterprise_upload_open: bool = False
    rag_top_k: int = 5
    rag_min_score: float = 0.25  # cosine floor below which retrieval is "low relevance"

    # Agent budgets (C3 §2.3), checked before every supervisor LLM call
    agent_max_steps: int = 14
    agent_max_tool_calls: int = 12
    agent_max_cost_usd: float = 0.25
    agent_max_seconds: int = 120
    max_active_runs_per_user: int = 2

    # Phase 4: text-to-SQL. WAREHOUSE_DSN is read ONLY by the data gateway (and onboarding CLI).
    enable_sql: bool = True
    warehouse_dsn: str = "postgresql://eagleeye_ro:eagleeye-ro-local@127.0.0.1:5433/warehouse"
    gateway_url: str = "http://127.0.0.1:8100"
    gateway_hmac_secret: str = ""  # required outside APP_ENV=local
    artifacts_bucket: str = "eagleeye-local-artifacts"
    sql_explain_max_rows: int = 5_000_000  # EXPLAIN estimate above this → rejected
    sql_max_concurrency: int = 4  # per source, in the gateway
    usage_limit_usd: float = 500.0  # lifetime LLM spend cap per user; new runs refused beyond it
    # organisation-wide LLM budget per calendar month: the starting value; admins change it
    # in the console (stored in app_settings), which then takes precedence
    monthly_budget_usd: float = 100.0
    # EagleEye's own cache (guard checks, query rewrites, search embeddings, repeated
    # company-document answers); entries expire after app_cache_ttl_s
    app_cache_enabled: bool = True
    app_cache_ttl_s: int = 86400

    # Phase 5: data files, analysis sandbox, charts (C6). The sandbox is a Docker container
    # with no network; if Docker or the image is missing, analysis tools are not offered.
    enable_analysis: bool = True
    enable_python_analysis: bool = True  # false → DuckDB SQL only
    sandbox_image: str = "eagleeye-sandbox:1"
    # "docker" (laptop: one container per run) or "lambda" (cloud: the sandbox function)
    sandbox_backend: str = "docker"
    sandbox_lambda_function: str = "eagleeye-sandbox"
    sandbox_lambda_endpoint_url: str = ""  # a local Lambda emulator; empty = AWS Lambda
    # (the local emulator always serves its function as "function": set SANDBOX_LAMBDA_FUNCTION)
    sandbox_transfer_bucket: str = ""  # inputs/outputs in transit; empty = the artifacts bucket
    # the S3 address the function itself can reach, for the links it is given (local
    # emulator: the storage container's name); empty = the normal S3 endpoint
    sandbox_transfer_endpoint_url: str = ""
    sandbox_mem_mb: int = 1024
    sandbox_timeout_s: int = 60
    sandbox_runs_per_hour: int = 60  # per user
    agent_max_seconds_analysis: int = 240  # run deadline when analysis tools are available
    # Notebook mode (docs/notebook-eda-plan.md): analyst-style notebooks with plots for company
    # users (never the shared demo account), run with larger sandbox limits
    enable_notebook_mode: bool = True
    notebook_sandbox_mem_mb: int = 2048
    notebook_sandbox_timeout_s: int = 120
    agent_max_seconds_notebook: int = 300
    dataset_max_rows: int = 2_000_000
    dataset_max_columns: int = 200

    # Phase 6: rate limits (per verified user per minute; per IP before authentication)
    rate_limit_general_per_min: int = 300  # the UI's own polling is ~60/min while files process
    rate_limit_messages_per_min: int = 20
    rate_limit_uploads_per_min: int = 20
    rate_limit_ip_per_min: int = 600
    max_streams_per_user: int = 4

    clerk_secret_key: str = ""
    # organisation admin-added users join; empty = auto-detect (works when there is exactly one)
    clerk_organization_id: str = ""
    clerk_publishable_key: str = Field(
        default="", validation_alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
    )
    clerk_issuer: str = ""  # optional pin, e.g. https://xxx.clerk.accounts.dev

    # Shared public demo account (users.is_demo). Its credentials are public on purpose;
    # the account is a normal member with its own spend cap, reset every day.
    demo_username: str = "demouser1"
    demo_password: str = ""  # set to enable `python -m app.demo setup`; shown on the sign-in page
    demo_email: str = "demouser1+clerk_test@example.com"
    demo_usage_limit_usd: float = 1.0  # lifetime LLM spend cap for the demo account
    demo_files_dir: str = "Trial/data/data-files"  # seeded into the account on setup/reset
    demo_reset_hours: float = 24.0  # 0 = never reset automatically
    # one email per new demo sign-in session (empty = no notifications)
    demo_notify_email: str = ""
    demo_notify_max_per_hour: int = 20  # flood guard if someone scripts sign-ins
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465  # implicit TLS
    smtp_username: str = ""  # e.g. your Gmail address
    smtp_password: str = ""  # a Google app password, never your account password

    @model_validator(mode="after")
    def _no_local_secrets_when_deployed(self) -> "Settings":
        if self.app_env != "local" and (
            self.s3_secret_key == LOCAL_S3_SECRET or self.s3_access_key == LOCAL_S3_ACCESS_KEY
        ):
            raise ValueError(
                "S3_ACCESS_KEY / S3_SECRET_KEY still use the local development defaults; "
                f"set real object-store credentials for APP_ENV={self.app_env}."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
