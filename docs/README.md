# EagleEye — Enterprise Agentic AI Platform: Design Pack

**Status:** v0.2 — reviewed and accepted (see [Decision Log](99-decision-log.md)).
**Deployment:** Phase 1 = fully local (Docker Compose, near-zero cost); Phase 2 = AWS. **Auth:** Clerk. **Scale target:** 10,000 users (see assumption A1).

## How to read this pack

| # | Doc | Purpose |
|---|-----|---------|
| 00 | [Requirements & Scope](00-requirements-and-scope.md) | What we build, what we don't, NFRs, assumptions |
| 01 | [High-Level Design (HLD)](01-HLD.md) | Architecture, layers, key flows, tech choices with trade-offs |
| 02 | [Low-Level Design (LLD)](02-LLD.md) | Service internals, API contract, sequence flows, state machines, config |
| 03 | [Data Model](components/03-data-model.md) | Postgres schema, S3 layout, Redis keys |
| C1 | [Frontend](components/C1-frontend.md) | Chat UI, right sidebar, streaming, charts |
| C2 | [Auth, Identity & Access Control](components/C2-auth-and-access-control.md) | Clerk, roles, document ACLs, data-source permissions |
| C3 | [Agent Orchestration](components/C3-agent-orchestration.md) | Guard, router, supervisor, sub-agents, budgets |
| C4 | [RAG](components/C4-rag.md) | Ingestion, hybrid retrieval, enterprise vs personal scope |
| C5 | [Text-to-SQL / Data Gateway](components/C5-text-to-sql-data-gateway.md) | NL → validated SQL → results |
| C6 | [EDA, Cross-Source Analysis & Charts](components/C6-eda-analysis-charts.md) | CSV EDA, DuckDB federation, chart specs, insights |
| C7 | [Memory & Context](components/C7-memory-and-context.md) | Short-term, summaries, long-term facts, token budgets |
| C8 | [Guardrails & Security](components/C8-guardrails-security.md) | Defence in depth, threat model |
| C9 | [Observability & Evaluation](components/C9-observability-evaluation.md) | Tracing, metrics, eval harness |
| C10 | [Infrastructure, Scaling & Cost](components/C10-aws-infra-scaling-cost.md) | Phase 1 Docker Compose map; Phase 2 network, compute, capacity, cost model |
| 99 | [Decision Log (ADRs)](99-decision-log.md) | Every major decision: options, choice, why, when to revisit |

Source principles come from *Section 12: Complete Agent Design and Interview Playbook* (seven-layer architecture, supervisor-worker, hybrid RAG, loop budgets, HITL, graceful degradation, model routing, tracing). Product reference is DocLens (streamed step tree, citations to chunk, memory panel, tool caps, fail-closed safety gate).

## Key decisions (confirmed — full rationale in the [Decision Log](99-decision-log.md))

| ID | Question | Decision |
|----|----------|----------|
| D1 | Scale | 10,000 registered, ~15% daily active, **~1,000 concurrent chats peak, 2,000 burst** (Phase 1 local: single-user dev/demo) |
| D2 | LLM provider | **LiteLLM proxy** — provider via `LLM_PROVIDER` env var (Anthropic API, OpenAI, or Ollama local/free); fast-class + capable-class model tiers (ADR-02/03) |
| D3 | Queryable enterprise DBs | Postgres/MySQL/SQL Server/Redshift via SQLAlchemy drivers; Snowflake/Oracle later |
| D4 | Enterprise doc sources | Admin upload + object-store sync in v1; SharePoint/Confluence connectors in v2 |
| D5 | Compliance | SOC2-style controls; single region; DR deferred (not required for portfolio v1) |
| D6 | Tenancy | **Single enterprise tenant**, schema ready for `org_id` (multi-tenant later) |
| D7 | Agent framework | **LangGraph** (checkpointing, streaming) behind our own thin ports (ADR-17) |
| D8 | Vector store | **Dual store**: Qdrant for enterprise chunks; Supabase pgvector for personal docs (ADR-04) |
| D9 | Web search tool | **No** (enterprise data only) |
| D10 | IaC / CI-CD | **docker-compose.yml** (Phase 1) + Terraform + GitHub Actions (Phase 2) |
| D11 | Backend language | **Python 3.12 + FastAPI** |
| D12 | Human-in-the-loop | No write actions in v1 (read-only platform); HITL reserved for v2 |

## Phased roadmap (proposed)

All milestones below run on the local Docker Compose stack; AWS (Phase 2 of ADR-16/25) comes after.

| Milestone | Scope | Exit criteria |
|-----------|-------|---------------|
| 0 | Sign-off on this pack, Clerk tenant, docker-compose skeleton, `.env.example` | Decisions D1–D12 closed; `docker compose up` boots the stack |
| 1 | Auth, chat UI, streaming, single LLM path (LiteLLM), chat history | Authenticated chat with streamed answers |
| 2 | RAG: personal upload + enterprise docs, dual-store retrieval, citations | Golden-set retrieval recall@5 ≥ target |
| 3 | Text-to-SQL via Data Gateway + schema catalog | Execution accuracy ≥ target on golden SQL set |
| 4 | CSV EDA, DuckDB cross-source analysis, charts, insights | End-to-end "combine CSV + DB + docs" demo |
| 5 | Hardening: guardrails, load test to 2k concurrent, security review | Load-test + security sign-off |
| 6 (Phase 2) | AWS lift: Terraform, ECS Fargate, Supabase Cloud, managed Redis/Qdrant | Cloud deploy green; parity with local demo |

**Build status (2026-11-12):** milestones 0 and 1 done. Milestone 2 (RAG) is functionally complete — upload, ingest worker, dual-store hybrid retrieval, cited answers (see C4 §9 "As built"); its exit criterion (golden-set recall@5) waits on the eval harness. Agent orchestration (C3) is built: guard → router → supervisor with tools in a Celery agent worker (see C3 §8 "As built").

## Notes on the reference site

I could read DocLens' engineering write-up (architecture, memory, streaming, RAG, safety gate) but **not** its interactive product-tour content or the demo UI, because those are client-rendered. UI decisions in C1 follow your description (chat centre, right sidebar for documents) plus DocLens patterns. If you want pixel-level parity, I can walk through the live demo in a browser and capture screenshots.
