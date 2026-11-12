# EagleEye

ChatGPT-style enterprise AI assistant: RAG over documents, text-to-SQL on enterprise databases, cross-source EDA with charts — local-first (Docker Compose), cloud-ready (AWS).

Full design pack: [docs/README.md](docs/README.md)

## Repository layout

```
apps/web            Next.js frontend
apps/api            FastAPI: REST + SSE
apps/agent-worker   Celery: LangGraph agent graphs      (Phase 3)
apps/ingest-worker  Celery: parse/chunk/embed pipeline  (Phase 2)
apps/data-gateway   Internal SQL executor               (Phase 4)
packages/core       Shared domain models, config, ports
infra/              docker-compose.yml (Phase 1 local stack)
evals/              Golden sets + eval harness          (Phase 6)
docs/               Design pack (HLD, LLD, components, ADRs)
```

## Quickstart (Phase 0)

Prereqs: Docker Desktop, Node 20+, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env

# 1. Infra services (Redis, Qdrant, SeaweedFS object store)
docker compose -f infra/docker-compose.yml up -d

# 2. Supabase local (Postgres + pgvector)
npm install          # installs supabase CLI (dev dep)
npx supabase start

# 3. API
uv sync
uv run --package eagleeye-api uvicorn app.main:app --app-dir apps/api --port 8000

# 4. Web
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000 — the status page shows live health of every service.

## Tests

```bash
uv run --package eagleeye-api pytest apps/api
```
