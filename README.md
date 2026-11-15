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

### Demo data: Grand Line Shipping Company

The app runs on data for **Grand Line Shipping Company**, a fictional container shipping line
(Jan 2024 – Oct 2026). Its database, documents and data files are generated so they agree with
each other, alongside real public material (daily Brent prices, US federal shipping and customs
rules; see `data/public/SOURCES.md`). Details: `docs/phase7-enterprise-data-plan.md`.

```bash
# warehouse: about 12.6M rows, ~6 min (scripts/start --onboard does this on first run)
uv run --no-project --with numpy==2.1.3 --with pandas==2.2.3 --with faker==33.1.0 --with asyncpg==0.30.0 python infra/warehouse/generate.py
# document library (~400 files; about USD 0.15 of LLM use once, cached afterwards)
uv run --package eagleeye-ingest-worker python data/grandline/make_docs.py
# data files for the analysis feature (upload them from the Data files panel)
uv run --package eagleeye-datasets --with pandas==2.2.3 --with numpy==2.1.3 python data/grandline/make_files.py
# load the documents into the app as enterprise documents (ingest worker running)
uv run --package eagleeye-api python data/grandline/load_docs.py
```

Generated output lives in `data/grandline/out/` (not committed).

## Cloud demo (AWS + Vercel)

The public demo (Phase 7B, [ADR-33](docs/99-decision-log.md), [plan](docs/phase7-cloud-plan.md)):
the web app on **Vercel**; the API behind **CloudFront** on one **EC2 machine** that runs the same
image with Docker Compose and is **stopped when nobody uses it**; analysis code in a **Lambda**
sandbox with no internet; Supabase (session pooler), Qdrant Cloud and S3 for data. Everything on
AWS is Terraform in `infra/terraform/`.

### First-time setup (in order)

```bash
aws login --profile eagleeye                       # an IAM admin user with MFA, not root
cd infra/terraform/bootstrap && terraform init && terraform apply   # the state bucket
terraform output -raw backend_hcl > ../base/backend.hcl
cd ../base && cp terraform.tfvars.example terraform.tfvars          # fill it in (git-ignored)
terraform init -backend-config=backend.hcl && terraform apply
gh variable set AWS_DEPLOY_ROLE_ARN --body "$(terraform output -raw deploy_role_arn)"
# push to main → CI → Deploy builds and pushes both images; then create the sandbox function:
#   add sandbox_image_tag = "<commit sha>" to terraform.tfvars and terraform apply
uv run --no-project --with "boto3[crt]" python scripts/cloud_env.py push   # secrets from .env.cloud
```

Then, with the machine running: apply `supabase/migrations` to the cloud project
(`supabase db push --db-url <session pooler URL>`), restore the warehouse (a `pg_dump` of the local
one), run catalog onboarding against the cloud database, run `python -m app.demo setup` and
`data/grandline/load_docs.py` inside the API container, and make the first admin in SQL. Vercel:
import the repo with root `apps/web` and paste the settings (`NEXT_PUBLIC_API_URL`, Clerk keys,
`WAKE_URL`/`WAKE_SECRET`, `SUPABASE_URL`/`SUPABASE_DEMO_GATE_KEY`, demo credentials); set
`web_origin` in `terraform.tfvars` to the Vercel address and apply.

### Day to day

| Task | How |
|---|---|
| Deploy | Push to `main`: after CI passes, Deploy pushes the images, records the tag in SSM and restarts the stack if the machine is running (a stopped machine uses the new tag at its next start) |
| Change a secret | Edit `.env.cloud`, `cloud_env.py push`, then restart the machine (or wait for its next start) |
| Wake / stop | Visitors wake it from `/demo` or the "Starting EagleEye" screen. It stops itself after 30 idle minutes with no background work; at most 6 h of running time a day; safety stop 03:00 UTC |
| A shell on the machine | No SSH. `aws ssm start-session --target <instance id>` (Session Manager plugin) or `aws ssm send-command`; `eagleeye-compose ps/logs` wraps Compose with the demo settings |
| Machine start-up | `infra/cloud/boot.sh`, fetched from S3 at every boot (change it and `terraform apply`; no new machine needed) |
| Demo limits | `app_settings` keys `demo_visit_seconds`, `demo_visit_budget_usd`, `demo_daily_budget_usd` (defaults 1800, 0.50, 2.00) |
| Costs | About $5 a month standing (Elastic IP + disk) plus about $0.10 an hour while the machine runs; budget emails at $25 / $50 / $75 |

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
