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
packages/datasets   Data files: CSV/XLSX → Parquet, DuckDB profile, shared table-artifact store
packages/sandbox    Analysis sandbox: static checks + Docker executor for model-written SQL/Python
packages/charts     Chart intent → Vega-Lite spec, data aggregated in code
packages/llm        LLMGateway (tools, fallback) + Embedder ports, LiteLLM adapters
packages/events     Run event vocabulary + Redis Stream sink/reader
packages/retrieval  Hybrid retrieval: Qdrant + pgvector + tsvector, RRF, access filter
packages/agents     Agent graph: guard → router → simple | RAG | supervisor ⇄ tools → checks
infra/              docker-compose.yml (local stack) + warehouse/ (demo DB seed) + sandbox/ (image)
evals/              Guard smoke eval, SQL, analysis + retrieval golden sets and harnesses, fixtures/
docs/               Design pack (HLD, LLD, components, ADRs)
```

## Quickstart

Prereqs: Docker Desktop, Node 20+, [uv](https://docs.astral.sh/uv/), a Clerk app (B2B) and an OpenAI key.

```bash
cp .env.example .env   # fill NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, OPENAI_API_KEY

# 1. Infra services (Redis, Qdrant, SeaweedFS object store, demo warehouse on :5433)
#    + the analysis sandbox image (once; rebuild after changing infra/sandbox)
docker compose -f infra/docker-compose.yml up -d
docker build -t eagleeye-sandbox:1 infra/sandbox

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

# 6. Data gateway (separate terminal) + one-time load and onboarding of the Grand Line warehouse
uv run --no-project --with numpy==2.1.3 --with pandas==2.2.3 --with faker==33.1.0 --with asyncpg==0.30.0 python infra/warehouse/generate.py --if-empty
uv run --package eagleeye-catalog python -m eagleeye_catalog.cli onboard grandline_ops
uv run --package eagleeye-data-gateway uvicorn gateway.main:app --app-dir apps/data-gateway --port 8100

# 7. Web
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000 and sign in. Upload a PDF/DOCX/MD/TXT in the right-hand panel and ask about it, or ask a business question ("top 5 product categories by revenue last quarter") — the answer shows the SQL, a result table (View all / CSV) and an explanation written from the result. Data access follows your role (`users.role`): `member` sees `sales.*` without personal data; `data_admin`/`admin` also see customer emails/phones. Set `ENABLE_SQL=false` to turn data querying off.

Upload a CSV or Excel file (e.g. `evals/fixtures/targets.csv`) to get an automatic profile (the "Profile" button in **Data files**), then ask analysis questions — "Compare monthly 2026 net revenue from the database with my targets file and flag the months below target, with a chart". Analysis code (DuckDB SQL or Python) runs in a Docker container with no network; the step tree shows it, charts are drawn from the result table, and the code sits in the collapsed result card. Without Docker or the image, data files and charts still work and the assistant says analysis is unavailable. Each answer shows a collapsible step tree (guard → route → retrieval / tool calls → checks), cites `[n]` sources you can open, and can be stopped mid-answer. `/status` shows live health of every service.

### Accounts and the admin console

There is no self-signup: only people an admin adds can sign in (the API refuses any other Clerk
account). Sign-in is by Google, or username / work email with a password or an emailed code. The
first admin is set in the database (`UPDATE users SET role='admin' WHERE email=…`); after that,
admins add people from **Admin console → Users** (one at a time or a CSV with `email, username,
first_name, last_name, role`) and delete them with a typed confirmation. In Clerk, set sign-up mode
to *Restricted* as well. Admins switch between **Chat** and the **Admin console** (Overview KPIs and
charts, Users, Usage & cost, Quality & safety, Content with enterprise uploads, System & controls
with kill switches).

### Re-indexing documents

Chunking settings (`CHUNK_*`, see `.env.example`) apply to new uploads. To re-chunk existing
documents (they stay searchable throughout), with the ingest worker running:

```bash
uv run --package eagleeye-ingest-worker python -m ingest_worker.reindex --all   # or --document <id>, --dry-run
```

## Tests

```bash
uv run pytest -m "not integration"   # integration tests need the warehouse + sandbox image
cd apps/web && npx tsc --noEmit && npm run lint && npm test

# Guard smoke eval against the real fast model (a few cents)
uv run --package eagleeye-agents python evals/guard_smoke.py

# SQL golden set: execution accuracy, refusals, cost, latency per model (~$0.07 for terra)
uv run --package eagleeye-agent-worker python evals/sql_eval.py gpt-6.1-terra gpt-6-luna

# Analysis golden set: numeric accuracy over the fixtures, in the real sandbox (~$0.05 for terra)
uv run --package eagleeye-agent-worker --with scipy --with pandas python evals/analysis_eval.py gpt-6-luna

# Retrieval eval: compares chunking configurations (embeddings only, ~$0.01 per configuration)
uv run --package eagleeye-ingest-worker --with fpdf2 python evals/fixtures/make_docs.py   # regenerate fixtures
uv run --package eagleeye-ingest-worker python evals/retrieval_eval.py --split dev --configs A,B,C,D
```

Security review and how to re-run the scans: [docs/security-review-phase6.md](docs/security-review-phase6.md).
