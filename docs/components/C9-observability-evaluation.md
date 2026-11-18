# C9 — Observability & Evaluation

## 1. Tracing
- **OpenTelemetry** across web (browser RUM), api, workers, gateway; `trace_id` propagated via headers and stored on `runs`, `audit_log`, `sql_query_log`; export to **Langfuse OSS** (Docker Compose, Phase 1) for LLM traces: each LLM call, tool call, retrieval, SQL execution = a span with latency, tokens, cost, model id, prompt version. Phase 2 adds CloudWatch/X-Ray for infra traces (ECS, ALB, Lambda) alongside Langfuse.
- Prompts/outputs in traces are **redacted** (PII scrubber) and sampled (100% errors/blocked/negative feedback; 10% others); 30-day retention.
- A run's step tree in the UI is built from the same events (single source of truth).

## 2. Metrics (Prometheus + Grafana, Phase 1; + CloudWatch Phase 2) & SLOs
| Area | Metrics | SLO / alert |
|------|---------|-------------|
| Chat | TTFT p50/p95, total latency by intent, error rate, degraded rate, active runs, queue wait | TTFT p95 < 4 s; error < 1%; alert degraded > 5% |
| LLM | calls, tokens in/out, cost, 429 rate, retries, circuit-breaker state, cache hit (prompt/semantic) | LLM provider throttle > 2% alert |
| RAG | retrieval latency, empty/low-relevance rate, rerank usage, chunks injected | p95 < 300 ms |
| SQL | gen success rate, validation rejects, self-correction count, DB latency per source, timeouts | exec accuracy (eval) ≥ 85% |
| Analysis | sandbox duration, OOM/timeouts, charts rejected by grounding | timeout < 2% |
| Ingestion | Celery queue depth/age, stage durations, failure rate, dead-letter depth | oldest task < 10 min; DLQ > 0 pages |
| Infra | CPU/mem, Supabase PG connections/replica lag, Qdrant memory/indexing, Redis memory/evictions, Docker container health (Phase 1) / ECS task count (Phase 2) | standard alarms |
| Product | DAU, chats/user, thumbs ratio, abandon rate, top intents | dashboards |
| Cost | $/turn, $/user/day, top spenders, budget breaches | alert > $0.15/conversation avg, daily budget |

Availability SLO 99.9% on chat path; error budget policy (freeze risky releases when burned).

## 3. Logging
Structured JSON (request_id, trace_id, user_id hash, route, latency); no raw prompts/PII in app logs; security events on a dedicated stream; log retention 90 d hot, 1 yr cold (Phase 2: S3 Object Lock for immutable audit log; Phase 1: local Docker log files, dev/demo data only).

## 4. Evaluation framework (eval-driven development)
An evaluation pyramid (properties → golden sets → human review), run in CI and nightly.

| Suite | What | Metric | Gate |
|-------|------|--------|------|
| Property tests | Always: no PII leak, cites sources for doc claims, SQL read-only, charts only use artifact numbers, refusal on injection corpus | pass rate 100% | block merge |
| Retrieval golden set (≥150) | enterprise + personal questions with gold chunks | recall@5, MRR | no regression > 2 pts |
| RAG answer quality | faithfulness, relevance, citation precision (LLM-judge calibrated vs human labels) | ≥ 90% faithful | block release |
| Text-to-SQL golden set (≥100/source) | NL → expected result | execution accuracy, valid-SQL rate | ≥ 85% / no regression |
| EDA/analysis set (≥50) | numeric questions on fixture CSVs, cross-source joins | numeric match within tolerance | ≥ 90% |
| Safety suite | injection, jailbreak, exfil, SQL escape, sandbox escape, ACL leak | zero leaks | block release |
| Latency/cost | scripted flows with live models in staging | p50/p95, $/turn | alert on drift |
| Human eval | 50 sampled prod conversations/month, rubric (accuracy, helpfulness, tone) | trend | quarterly review |

Mechanics: datasets versioned in `evals/`; runner supports **mock-LLM mode** (fast, deterministic CI) and **live mode** (nightly); results to Langfuse datasets; prompt/model/embedding change requires eval report in PR. Production feedback (👎 + comment) → triage queue → new golden case or catalog/prompt fix. **Different model family for the judge than the generator when possible** (avoid self-grading bias).

## 5. Dashboards & on-call
Dashboards (Grafana, Phase 1; + CloudWatch dashboards Phase 2): Chat health, LLM cost & quota, RAG quality, SQL accuracy, Ingestion, Security events. Paging for SLO burn, DLQ > 0, LLM provider quota exhaustion, Supabase/Redis health, gateway outage per source. Runbooks per alarm.

## 5a. As built — Phase 6 (local, ADR-32)

Monitoring is an **in-app admin console** (`/admin`, admins only) instead of Grafana/Langfuse in the
local phase. Every figure is a read-only aggregate computed when an admin opens the console —
nothing is added to answer generation; aggregates are cached 60 s per period.

| Report | Contents |
|---|---|
| Overview | Active users, requests, success and failure rate (period-over-period deltas, sparklines), LLM cost (billing ledger), average response time (p95, first token); live database health (Postgres + Qdrant pings), active/stalled agents, safety events, enterprise knowledge; request outcomes per day/hour, LLM cost by model (donut), request routing distribution, slowest pipeline steps (mean), step latency trend and change for six major stages |
| Users | Accounts, roles, last seen, requests, tokens, cost, usage-limit share; add (one or CSV), delete |
| Usage & cost | Cost per day by model, top spenders, agent tool usage |
| Quality & safety | Guard events by category, SQL refusals, sandbox results, unverified-figure rate, failed runs, admin audit trail |
| Content | Enterprise knowledge base (upload one or many, delete with typed confirmation), indexing status, failures |
| System & controls | Service health, queue depth, active/stuck runs, kill switches, clear stuck runs |

Runs now record `first_token_at`, `finished_at` and `warnings`. Evaluation suites in `evals/`:
guard, SQL, analysis, model bench and (Phase 6) **retrieval** (`retrieval_eval.py`, see C4 §9.1).
Structured JSON logs, tracing and the 2,000-connection load test move to the cloud phase.

## 6. Load & chaos testing
k6 scripts: 2,000 concurrent SSE with stubbed LLM (LiteLLM mock mode); separate LLM provider rate-limit test (simulate 429 storms); Celery ingestion backlog test (1,000 docs); chaos: kill Celery workers mid-run (resume via LangGraph checkpoint), throttle LLM provider (fallback model chain), drop Redis node (failover), block a DB source (degrade gracefully), expire Clerk JWKS cache.
