# EagleEye

ChatGPT-style enterprise AI assistant: RAG over documents, text-to-SQL on enterprise databases, cross-source EDA with charts — local-first (Docker Compose), cloud-ready (AWS).

Full design pack: [docs/README.md](docs/README.md)

## Repository layout

```
apps/web            Next.js frontend
apps/api            FastAPI: auth, REST, run admission, SSE streaming
apps/agent-worker   Celery: executes agent runs (queue `agent`)
apps/ingest-worker  Celery: scan/parse/chunk/embed/upsert pipeline (queue `ingest`)
apps/data-gateway   Internal SQL executor               (Phase 4)
packages/core       Shared config, envelope, ObjectStore port, queue names
packages/llm        LLMGateway (tools, fallback) + Embedder ports, LiteLLM adapters
packages/events     Run event vocabulary + Redis Stream sink/reader
packages/retrieval  Hybrid retrieval: Qdrant + pgvector + tsvector, RRF, access filter
packages/agents     Agent graph: guard → router → simple | RAG | supervisor ⇄ tools → checks
infra/              docker-compose.yml (Phase 1 local stack)
evals/              Guard smoke eval (golden sets + harness in Phase 6)
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

# 4. Agent worker (separate terminal) — answers every chat message
uv run --package eagleeye-agent-worker celery -A agent_worker.celery_app worker --pool=threads --concurrency=8 -Q agent -l info -n agent@%h

# 5. Ingest worker (separate terminal; --pool=solo is required on Windows)
uv run --package eagleeye-ingest-worker celery -A ingest_worker.celery_app worker --pool=solo -Q ingest -l info -n ingest@%h

# 6. Web
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000 and sign in. Upload a PDF/DOCX/MD/TXT in the right-hand panel and ask about it. Each answer shows a collapsible step tree (guard → route → retrieval / tool calls → checks), cites `[n]` sources you can open, and can be stopped mid-answer. `/status` shows live health of every service.

## Tests

```bash
uv run pytest apps/api/tests apps/ingest-worker/tests packages
cd apps/web && npx tsc --noEmit && npm run lint && npm test

# Guard smoke eval against the real fast model (a few cents)
uv run --package eagleeye-agents python evals/guard_smoke.py
```
