# EagleEye

ChatGPT-style enterprise AI assistant: RAG over documents, text-to-SQL on enterprise databases, cross-source EDA with charts — local-first (Docker Compose), cloud-ready (AWS).

Full design pack: [docs/README.md](docs/README.md)

## Repository layout

```
apps/web            Next.js frontend
apps/api            FastAPI: REST + SSE
apps/agent-worker   Celery: LangGraph agent graphs      (Phase 3)
apps/ingest-worker  Celery: scan/parse/chunk/embed/upsert pipeline
apps/data-gateway   Internal SQL executor               (Phase 4)
packages/core       Shared config, envelope, ObjectStore port, queue names
packages/llm        LLMGateway + Embedder ports, LiteLLM adapters
packages/retrieval  Hybrid retrieval: Qdrant + pgvector + tsvector, RRF, access filter
infra/              docker-compose.yml (Phase 1 local stack)
evals/              Golden sets + eval harness          (Phase 6)
docs/               Design pack (HLD, LLD, components, ADRs)
```

## Quickstart

Prereqs: Docker Desktop, Node 20+, [uv](https://docs.astral.sh/uv/), a Clerk app (B2B) and an OpenAI key.

```bash
cp .env.example .env   # fill NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, OPENAI_API_KEY

# 1. Infra services (Redis, Qdrant, SeaweedFS object store)
docker compose -f infra/docker-compose.yml up -d

# 2. Supabase local (Postgres + pgvector) and migrations
npm install          # installs supabase CLI (dev dep)
npx supabase start
npx supabase migration up

# 3. API (creates the docs bucket + Qdrant collection on startup)
uv sync --all-packages
uv run --package eagleeye-api uvicorn app.main:app --app-dir apps/api --port 8000

# 4. Ingest worker (separate terminal; --pool=solo is required on Windows)
uv run --package eagleeye-ingest-worker celery -A ingest_worker.celery_app worker --pool=solo -Q ingest -l info

# 5. Web
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000, sign in, upload a PDF/DOCX/MD/TXT in the right-hand panel, wait for **Ready**, and ask about it — answers cite `[n]` sources you can open. `/status` shows live health of every service.

## Tests

```bash
uv run pytest apps/api/tests apps/ingest-worker/tests packages
cd apps/web && npx tsc --noEmit && npm run lint
```
