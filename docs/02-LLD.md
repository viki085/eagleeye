# 02 — Low-Level Design (LLD)

Scope: service internals, module layout, API contract, streaming protocol, state machines, configuration. Component deep-dives are in `components/`.

## 1. Repository layout (monorepo)

```
eagleeye/
├─ apps/
│  ├─ web/                    # Next.js app
│  ├─ api/                    # FastAPI: REST + SSE, authN/Z
│  ├─ agent-worker/           # Celery worker: runs LangGraph agent graphs
│  ├─ ingest-worker/          # Celery worker: parse/chunk/embed pipeline
│  ├─ data-gateway/           # FastAPI (internal): executes validated SQL
│  └─ sandbox/                # Phase 1: Docker subprocess runner; Phase 2: Lambda container
├─ packages/
│  ├─ core/                   # domain models (pydantic), errors, config, ports
│  ├─ llm/                    # LLMGateway port + LiteLLM adapter, model tier config
│  ├─ agents/                 # graphs, prompts, tools (guard, supervisor, sub-agents)
│  ├─ retrieval/              # hybrid search, RRF, rerank hooks (Qdrant + Supabase pgvector)
│  ├─ sqlsafe/                # sqlglot validation + rewriting
│  ├─ catalog/                # schema catalog + semantic layer
│  ├─ events/                 # event vocabulary, Redis stream sink/fold
│  └─ observability/          # Langfuse traces, Prometheus metrics
├─ infra/
│  ├─ docker-compose.yml      # Phase 1: full local stack
│  ├─ docker-compose.override.yml  # local dev overrides (hot reload, debug ports)
│  └─ terraform/              # Phase 2: AWS cloud provisioning
├─ evals/                     # golden sets, harness (Langfuse evals)
└─ docs/
```
Ports/adapters: `LLMGateway`, `Embedder`, `VectorStore` (Qdrant + Supabase pgvector), `ObjectStore` (SeaweedFS/S3), `EventBus` (Redis Streams), `TaskQueue` (Celery/Redis), `AuthProvider`, `SecretStore`. Business logic depends on ports only — enables provider swaps (LiteLLM backends, SeaweedFS↔S3, Supabase CLI↔Cloud) and easy test doubles.

## 2. API service

### 2.1 Middleware order
`request-id → correlation-id → security headers → CORS → trusted host → size limit → rate limit (Redis token bucket per user+IP) → authN (Clerk JWT, JWKS cached) → user context (DB lookup, cached 60 s) → route`.

### 2.2 REST contract (v1)
Envelope for all JSON: `{ "success": bool, "data": T|null, "error": {code,message,request_id}|null, "meta": {page,limit,total}|null }`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/me` | Profile, roles, groups, quotas |
| GET/POST | `/v1/chats` | List / create chat |
| GET/PATCH/DELETE | `/v1/chats/{id}` | Read (with messages, paged) / rename / delete |
| POST | `/v1/chats/{id}/messages` | Send message → `202 {run_id}` (body: text, attachment_ids, selected_source_ids, idempotency_key) |
| GET | `/v1/runs/{id}/stream` | SSE event stream (resumable via `Last-Event-ID`) |
| POST | `/v1/runs/{id}/cancel` | Cancel run |
| GET | `/v1/runs/{id}` | Run status, steps, usage (for refresh/replay) |
| POST | `/v1/uploads` | Create upload: returns presigned URL + `document_id` (409 on duplicate hash) |
| POST | `/v1/uploads/{id}/complete` | Mark uploaded; enqueues ingestion if S3 event missed |
| GET | `/v1/documents?scope=mine\|enterprise` | List with status |
| GET/DELETE | `/v1/documents/{id}` | Detail (chunks preview) / delete (cascade chunks, S3) |
| GET | `/v1/documents/{id}/chunks/{cid}` | Citation target (original text, page, bbox) |
| POST | `/v1/datasets` | Upload a data file (`.csv`/`.tsv`/`.xlsx`, ≤ 25 MB; 415 other types, 409 duplicate) → enqueues `ingest.profile_dataset` |
| GET | `/v1/datasets` | The caller's data files with status, row/column counts (Phase 5: personal only) |
| GET | `/v1/datasets/{id}` | One data file with its EDA `profile` and `column_map` (owner-only, else 404) |
| GET | `/v1/datasets/{id}/rows?offset=&limit=` | Paged rows (≤ 200; 409 while processing) |
| DELETE | `/v1/datasets/{id}` | Delete row + Parquet (+ original when no sibling sheet uses it) |
| GET | `/v1/sources` | Data sources the caller's role can use: granted tables with descriptions, `can_see_pii` |
| GET | `/v1/artifacts/{id}?offset=&limit=` | Owner-only table artifact: columns, page of rows (≤ 200), `row_count`, `truncated`, `sql` (404 for others) |
| GET | `/v1/artifacts/{id}/csv` | Owner-only CSV download (≤ 10,000 rows; cells starting `= + - @` prefixed with `'`) |
| POST | `/v1/messages/{id}/feedback` | Thumbs + comment |
| GET/PUT/DELETE | `/v1/me/facts` | User facts (view/edit/delete) |
| — | `/v1/admin/...` | Sources, catalog descriptions, enterprise docs & ACLs, usage, audit, kill switches (role=admin) — **as built in Phase 6, see §2.2a** |
| POST | `/v1/webhooks/clerk` | Clerk user/org events (Svix signature verified) |

Errors: `400 validation, 401, 403, 404, 409 duplicate, 413 too large, 422, 429 rate/quota (Retry-After), 503 degraded`.

### 2.2a As built — Phase 6 (admin, accounts, hardening; ADR-32)

**Middleware (outermost first):** request id → security headers → JSON body limit (64 KB) → CORS
(exposes `X-Request-ID`, `Retry-After`) → crash-to-envelope → routes. Rate limits run in the auth
dependency (IP before token check, user after). Every error envelope carries `request_id`.

**Accounts:** no lazy provisioning — a Clerk user without an EagleEye row gets `403` ("ask your
administrator"); `deleted`/`disabled` accounts get `403`.

| Method | Path | Purpose (all `/v1/admin/*` require role `admin`, re-read from the DB per call) |
|--------|------|---------|
| GET | `/v1/admin/overview?range=24h\|7d\|30d` | KPIs + previous period, series, cost by model, routes, slowest steps, step trend/change, knowledge base; live database health + active runs. Aggregates cached 60 s per range |
| GET | `/v1/admin/users?range&sort&offset&limit` | Live accounts (not `deleted`) with period requests/tokens/cost and usage-limit share |
| POST | `/v1/admin/users` | Add one user `{email, username?, first_name, last_name, role}` → Clerk account + organisation membership + row (`201`; `409` existing; rollback on failure) |
| POST | `/v1/admin/users/bulk` | `{users: [...≤25]}` → per-row `{email, ok, error?, user?}` |
| DELETE | `/v1/admin/users/{id}` | Revoke Clerk sign-in, mark `deleted`; `400` self, `409` last admin; audited first |
| GET | `/v1/admin/usage\|safety\|content\|system` | Usage & cost, quality & safety (incl. admin audit trail), content status, service health/queues/runs/switches |
| POST | `/v1/admin/switches/{chat\|sql\|analysis\|uploads}` | `{killed: bool}`; audited before the flag changes |
| POST | `/v1/admin/runs/clear-stuck` | Fail runs with no worker heartbeat |

Enterprise document upload/delete (`/v1/documents`, scope `enterprise`) is audited as an admin
action. Limits (settings): `RATE_LIMIT_GENERAL_PER_MIN=300`, `RATE_LIMIT_MESSAGES_PER_MIN=20`,
`RATE_LIMIT_UPLOADS_PER_MIN=20`, `RATE_LIMIT_IP_PER_MIN=600`, `MAX_STREAMS_PER_USER=4`.
Chunking: `CHUNK_SOFT_CHARS=1200`, `CHUNK_MAX_CHARS=1600`, `CHUNK_OVERLAP_CHARS=200`,
`CHUNK_MIN_CHARS=400`; re-index with `python -m ingest_worker.reindex --all`.

### 2.3 SSE event vocabulary (single sink stamps gapless `seq` from 0)
```
run.started      {run_id}
guard.result     {safe, intent, route}
step.started     {step_id, parent_id, kind: guard|llm|tool|retrieval|check, name, input_summary}
step.finished    {step_id, status: ok|error|skipped, output_summary, duration_ms, tokens, cost}
text.delta       {text}
text.replace     {text}                       # output filter / citation cleanup replaced the answer
citation         {n, document_id, chunk_id, title, page, heading_path, scope, snippet}
chat.updated     {chat_id, title}
artifact         {artifact_id, type: table, title, sql, mode: sql|duckdb|python, columns, row_count, truncated, preview}
chart            {chart_id, title, spec (Vega-Lite, data inline, no colours), summary, source_id}  # Phase 5; part "charts"
run.done         {message_id, status, degraded, cancelled, usage{in,out,cost}, warnings[]}  # e.g. "unverified_numbers"
run.error        {code, user_message}         # after 200, errors are events
```
Names live in `packages/events/eagleeye_events/names.py`; the web fold is `apps/web/src/lib/run-fold.ts`.
Client folds events into message parts; backend persists the same fold (a shared test fixture verifies both folds produce identical parts).

Transport: fetch-based SSE client (needs POST/Authorization header); ALB idle timeout 300 s; 15 s heartbeat comments; server reads from Redis Stream `run:{id}:events`.

## 3. Agent worker

### 3.1 Run lifecycle (state machine)
```
QUEUED → RUNNING → (AWAITING_INPUT*) → SUCCEEDED | FAILED | CANCELLED | BUDGET_EXCEEDED
```
(*reserved for future HITL.) Persisted in `runs`. A worker claims via Redis consumer group; claim has a visibility timeout (60 s heartbeat). A **sweeper** (Celery beat, 1 min; EventBridge in Phase 2) requeues runs stuck RUNNING with no heartbeat (max 1 retry, idempotent steps) else marks FAILED and emits `run.error`.

### 3.2 Graph (LangGraph) — summary (full: C3)
```
guard → route ─┬─ simple_chat → finalize
               └─ supervisor ⇄ {knowledge_agent, sql_agent, analysis_agent, chart_tool}
                                → ground_check → finalize
```
Budgets per run (config): `max_steps=14, max_tool_calls=12, max_cost_usd=0.25, max_seconds=120` (analysis runs: 240 s). Spend checked before every LLM call; unknown model priced as most expensive.

### 3.3 Tool contract
Every tool: pydantic input/output schema, `timeout`, `retry policy`, `idempotent: bool`, returns `ToolResult{ok, data, error_code, user_safe_error, citations[], artifacts[]}`. Tool output is wrapped `<tool_data>…</tool_data>` before the model sees it; instructions in it are ignored by system prompt hierarchy.

Tools exposed to the supervisor:

| Tool | Input | Output | Backed by |
|------|-------|--------|-----------|
| `search_knowledge` | query, scope(enterprise/personal/both), doc_ids? | top chunks + citations | Retrieval pkg |
| `list_data_sources` / `describe_tables` | question | relevant catalog entries | Catalog |
| `run_sql` | source_id, sql (generated by SQL agent) | artifact_id + preview (≤ 50 rows to LLM) | Data Gateway |
| `analyze_data` | dataset_ids/artifact_ids, task | stats, new artifacts | Sandbox |
| `make_chart` | artifact_id, chart intent | Vega-Lite spec (validated) | Chart tool |
| `get_dataset_profile` | dataset_id | EDA profile | Catalog |

## 4. Ingest worker (see C4)
Celery task `ingest_document(document_id)` consumed from Redis queue `ingest`. Retry up to 3 times with exponential backoff; failed tasks moved to `ingest.dead` Redis set (DLQ pattern). One document per task; stage events written to `documents.stage` in Supabase and pushed to Redis Stream for UI. Idempotent by `(document_id, stage)`; re-run safe (chunks upserted by deterministic `chunk_hash`).

State machine: `UPLOADING → SCANNING → PARSING → CHUNKING → EMBEDDING → READY | FAILED(reason)`.
Tabular files: `UPLOADED → PROFILING → READY` (Parquet conversion in SeaweedFS/S3 + EDA profile in Supabase).
Chunks routed to: Qdrant (scope=enterprise) or Supabase pgvector (scope=personal).

## 5. Data Gateway (see C5)
**As built (Phase 4):** `apps/data-gateway` on :8100, `POST /execute {source_id, sql, title}` + header `X-Context-Token` (HMAC `{user_id, source_id, run_id, exp}`), `GET /health`. Persisted message part `{"type": "artifacts", "items": [...]}`; the run part carries `warnings`. Supervisor tools: `query_database(question, source?)` (nested SQL sub-agent) and `list_data_sources`, registered only when `ENABLE_SQL` and the user has a grant.

Internal-only FastAPI service (not exposed through Nginx). `POST /execute {source_id, sql, user_ctx(signed), limits}` → re-validates SQL (never trusts caller), applies row-level grants, executes with read-only credentials, `statement_timeout`, `LIMIT` cap, streams results to Parquet in SeaweedFS/S3, returns schema + sample + row count. Auth: service-to-service via shared internal HMAC secret + short-lived signed context token (HMAC + exp, 30 s). Phase 2 replaces with SigV4 or service mesh mTLS.

## 6. Sandbox (see C6)
**As built (Phase 5):** no analysis worker. The agent worker runs each task through `AnalysisExecutor` → `DockerExecutor` (`packages/sandbox`), one `docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 1g --memory-swap 1g --cpus 1` per execution, image `eagleeye-sandbox:1` (`infra/sandbox`). Supervisor tools: `list_datasets`, `get_dataset_profile`, `analyze_data(question, inputs[])` (nested analysis sub-agent), `make_chart(source_id, type, x, y|[y…], color?, aggregate?, sort?, top_n?, title)`. Message parts gain `{"type": "charts", "items": [...]}`.

**Phase 1 (local):** Docker subprocess spawned by analysis-worker (`subprocess.run`, `--network none`, isolated temp directory bind-mount). Image: `python:3.12-slim` + DuckDB + pandas + numpy + scipy + scikit-learn-light. Limits: configurable via env (`SANDBOX_MEM_MB`, `SANDBOX_TIMEOUT_S`); output ≤ 20 MB inline else SeaweedFS.

**Phase 2 (cloud):** Lambda container (same Python image). No VPC egress; IAM role scoped to `s3://…/sessions/{session_id}/*` via per-invocation STS session policy. Limits: 10 GB mem, 120–300 s, output ≤ 20 MB inline else S3.

## 7. Caching
| Cache | Key | TTL | Notes |
|-------|-----|-----|-------|
| Auth user ctx | `uctx:{user_id}` | 60 s | invalidated by webhook |
| Pre-built prompt prefix | `ctx:{chat_id}:{facts_v}:{last_msg_no}` | 15 min | prompt-cache friendly ordering |
| Semantic cache | embedding of normalized query + `scope_hash` (ACL groups + source set) | 6 h | **Only** for doc-only, non-personal answers; never for SQL/personal |
| Catalog | `catalog:{source_id}:{version}` | until version bump | |
| Rate limit | `rl:{user}:{window}` | window | token bucket |

## 8. Configuration & secrets
12-factor env vars. **Phase 1 (local):** `.env` file (gitignored); `.env.example` documents every variable. **Phase 2 (cloud):** AWS SSM Parameter Store (non-secret) and Secrets Manager (secrets). Pydantic `Settings`, validated at startup — fail fast on missing required vars. Feature flags via env or AppConfig (Phase 2): `ENABLE_ANALYSIS`, `ENABLE_SQL`, `LLM_PROVIDER`, `MODEL_FAST`, `MODEL_CAPABLE`, `KILL_SWITCH`. Model names, prices, budget limits are config not code.

## 9. Error handling conventions
- Domain errors (`NotFound`, `Forbidden`, `BudgetExceeded`, `ToolTimeout`, `GuardBlocked`) mapped to HTTP + SSE `run.error` with user-safe text; details only in logs/traces.
- Retries: exponential backoff 1s/2s/4s, max 3, only for transient (429/5xx/timeouts); never retry non-idempotent writes without an idempotency key.
- Every message carries `idempotency_key` (client UUID) to dedupe double-submits.

## 10. Testing strategy (80%+ coverage)
| Level | Scope |
|-------|-------|
| Unit | sqlsafe validator, RRF, chunker, budget manager, event fold, ACL filter builder |
| Integration | API↔Supabase PG (Testcontainers or Supabase CLI test project), Qdrant (Docker in CI), retrieval with pgvector, Data Gateway against Postgres fixtures, Redis streams |
| Contract | Event-vocabulary fixtures shared by backend and frontend; OpenAPI schema diff in CI |
| Agent | Property-based (no PII, cites sources, no ungrounded numbers), golden-set regression (evals/) with mocked + live-model modes |
| E2E | Playwright: login (Clerk test mode), upload, ask, chart, resume stream |
| Load | k6: 2,000 concurrent SSE streams with stubbed LLM (LiteLLM mock mode); Celery worker concurrency stress test |
| Security | ACL leak tests (user A can't retrieve user B chunks), injection corpus, SQL escape corpus |
