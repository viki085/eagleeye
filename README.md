# EagleEye

ChatGPT-style enterprise AI assistant: RAG over documents, text-to-SQL on enterprise databases, cross-source EDA with charts — local-first (Docker Compose), cloud-ready (AWS).

Full design pack: [docs/README.md](docs/README.md)

## Repository layout

```
apps/web            Next.js frontend
apps/api            FastAPI: auth, REST, run admission, SSE streaming
apps/agent-worker   Celery: executes agent runs (queue `agent`)
apps/ingest-worker  Celery: scan/parse/chunk/embed/upsert pipeline (queue `ingest`)
apps/data-gateway   Internal SQL executor: re-validates, runs read-only, writes Parquet artifacts
packages/core       Shared config, envelope, ObjectStore port, queue names, service auth (HMAC)
packages/sqlsafe    Deterministic SQL validator (sqlglot AST): one SELECT, granted tables, PII, limit
packages/catalog    Semantic catalog: introspection + YAML seed + LLM descriptions + embeddings
packages/llm        LLMGateway (tools, fallback) + Embedder ports, LiteLLM adapters
packages/events     Run event vocabulary + Redis Stream sink/reader
packages/retrieval  Hybrid retrieval: Qdrant + pgvector + tsvector, RRF, access filter
packages/agents     Agent graph: guard → router → simple | RAG | supervisor ⇄ tools → checks
infra/              docker-compose.yml (local stack) + warehouse/ (demo enterprise DB seed)
evals/              Guard smoke eval, SQL golden set + execution-accuracy harness
docs/               Design pack (HLD, LLD, components, ADRs)
```

## Quickstart

Prereqs: Docker Desktop, Node 20+, [uv](https://docs.astral.sh/uv/), a Clerk app (B2B) and an OpenAI key.

```bash
cp .env.example .env   # fill NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, OPENAI_API_KEY

# 1. Infra services (Redis, Qdrant, SeaweedFS object store, demo warehouse on :5433)
docker compose -f infra/docker-compose.yml up -d

# 2. Supabase local (Postgres + pgvector) and migrations
npm install          # installs supabase CLI (dev dep)
npx supabase start
npx supabase migration up

# 3. API (creates the docs bucket + Qdrant collection on startup)
uv sync --all-packages
uv run --package eagleeye-api uvicorn app.main:app --app-dir apps/api --port 8000

# 4. Agent worker (separate terminal) — answers every chat message
uv run --package eagleeye-agent-worker celery -A agent_worker.celery_app worker --pool=threads --concurrency=8 -Q agent -l info -n agent@%h

# 5. Ingest worker (separate terminal; --pool=solo is required on Windows)
uv run --package eagleeye-ingest-worker celery -A ingest_worker.celery_app worker --pool=solo -Q ingest -l info -n ingest@%h

# 6. Data gateway (separate terminal) + one-time catalog onboarding of the demo warehouse
uv run --package eagleeye-catalog python -m eagleeye_catalog.cli onboard acme_warehouse
uv run --package eagleeye-data-gateway uvicorn gateway.main:app --app-dir apps/data-gateway --port 8100

# 7. Web
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000 and sign in. Upload a PDF/DOCX/MD/TXT in the right-hand panel and ask about it, or ask a business question ("top 5 product categories by revenue last quarter") — the answer shows the SQL, a result table (View all / CSV) and an explanation written from the result. Data access follows your role (`users.role`): `member` sees `sales.*` without personal data; `data_admin`/`admin` also see customer emails/phones. Set `ENABLE_SQL=false` to turn data querying off. Each answer shows a collapsible step tree (guard → route → retrieval / tool calls → checks), cites `[n]` sources you can open, and can be stopped mid-answer. `/status` shows live health of every service.

## Tests

```bash
uv run pytest -m "not integration"   # integration tests need the warehouse container
cd apps/web && npx tsc --noEmit && npm run lint && npm test

# Guard smoke eval against the real fast model (a few cents)
uv run --package eagleeye-agents python evals/guard_smoke.py

# SQL golden set: execution accuracy, refusals, cost, latency per model (~$0.07 for terra)
uv run --package eagleeye-agent-worker python evals/sql_eval.py gpt-6.1-terra gpt-6-luna
```
