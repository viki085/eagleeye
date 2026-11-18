# 00 — Requirements and Scope

## 1. Purpose
EagleEye is an enterprise AI assistant for employees. It answers from (a) enterprise-wide documents, (b) documents the user uploads, (c) enterprise SQL databases through natural language, and (d) uploaded CSV and Excel files. It can combine these sources in one answer, run exploratory analysis, draw charts and summarise insights, and every answer shows the evidence it is based on.

## 2. Personas
| Persona | Needs |
|---------|-------|
| **Employee (member)** | Chat, upload personal docs/CSVs, ask questions across sources, get charts |
| **Data/Domain Admin** | Register data sources, curate schema descriptions, grant source access to groups |
| **Knowledge Admin** | Upload/manage enterprise documents and their access groups |
| **Platform Admin / SecOps** | Usage, cost, audit logs, kill switches, guardrail config |

## 3. Functional requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| F1 | Sign-up / login via **Clerk** (email+password, SSO/SAML via Clerk enterprise connections, MFA) | Restricted to corporate domain / invited orgs |
| F2 | Conversational interface: new chat, chat list, streaming answers, stop/regenerate, rename/delete chat | |
| F3 | Right sidebar: upload documents/CSVs, list/delete them, toggle which are "in context" for the chat, view ingestion status | Per-chat and per-user scope |
| F4 | **RAG over enterprise docs** with per-document access control | Citations open the source chunk |
| F5 | **RAG over personal uploads**, visible only to the owner | PDF, DOCX, PPTX, TXT, MD, XLSX, CSV |
| F6 | **Text-to-SQL**: NL question → SQL → result table → natural-language answer | Read-only, permission-scoped |
| F7 | **Charts** on request (bar, line, pie, scatter, histogram, heatmap…) and automatic insight narration | Numbers must come from tool results |
| F8 | **EDA on CSV**: profile, missing values, distributions, correlations, outliers, summary insights | |
| F9 | **Cross-source analysis**: combine enterprise data, personal CSV, DB query results, doc-extracted tables | DuckDB federation, see C6 |
| F10 | Transparent reasoning: show step tree (tools used, SQL executed, sources) | Live step panel |
| F11 | Conversation memory within a chat; optional user facts/preferences | User can view/edit/delete facts |
| F12 | Export: result table to CSV, chart to PNG/SVG, conversation to PDF/MD | v1.1 |
| F13 | Admin console: sources, document ACLs, usage, audit | v1 minimal |
| F14 | Feedback (thumbs up/down + comment) per answer | Feeds eval set |

### Out of scope (v1) — and why
| Out of scope | Reason |
|--------------|--------|
| Any **write** to enterprise databases or systems | Read-only keeps authorization and compliance tractable; HITL design deferred |
| Web search / public internet browsing | Egress + injection surface; enterprise-data only (D9) |
| Fine-tuning models | Knowledge changes often; RAG covers it |
| Real-time streaming data sources | Batch/query only |
| Voice, mobile native apps | Responsive web only |
| Autonomous scheduled agents / alerts | Later phase |

## 4. Non-functional requirements

| Area | Target | How achieved (see HLD) |
|------|--------|-----------------------|
| Scale | 10,000 registered users; ~1,000 concurrent chats, burst 2,000 | Stateless services; Docker Compose locally (Phase 1); ECS Fargate + autoscaling in cloud (Phase 2); Redis shared state |
| Latency — first token | p50 < 2 s, p95 < 4 s for doc Q&A | Streaming SSE, fast-class model routing, prompt caching, pre-built context |
| Latency — full answer | p50 < 8 s simple, < 25 s for SQL+chart, < 60 s heavy EDA (with progress events) | Parallel tool calls, budget caps, async heavy jobs |
| Ingestion | 50-page PDF searchable < 2 min; 200 MB CSV profiled < 3 min | Celery workers + Redis; docker-compose scaled workers |
| Availability | 99.9% monthly for chat path (Phase 2 cloud target; local Phase 1 is best-effort) | Model fallback chain, graceful degradation; Phase 2 adds multi-AZ |
| Durability | Phase 1 (local): dev/demo data only. Phase 2: RPO ≤ 5 min via Supabase continuous backup + S3 versioning | Phase 2: Supabase Point-in-Time Recovery, S3 versioning |
| Security | No cross-user/cross-ACL leakage; no unauthorized data reaches the LLM; full audit | RLS + metadata filters, data gateway, network-isolated sandbox, guardrail rules |
| Cost | Target ≤ $0.05 average per chat turn (alert at $0.15 per conversation). Phase 1: near-zero (Ollama local, free tiers) | Model tier routing, semantic cache, per-run budget; Ollama for free local dev |
| Accuracy | RAG answer faithfulness ≥ 90% on golden set; SQL execution accuracy ≥ 85% on golden set | Eval harness via Langfuse (C9) |
| Compliance | Audit log immutable 1 yr (Phase 2); data retention configurable; PII column masking | Phase 2: S3 Object Lock for audit log; PII flags in catalog enforced in Phase 1 |
| Accessibility | WCAG 2.1 AA | shadcn/ui component library |

## 5. Assumptions
- **A1** 10,000 registered users; ~15% DAU (1,500); avg 8 chats/day/active user → ~1,500 × 8 × ~5 turns ≈ **60k turns/day**, peak ~4 turns/s. (Phase 1 local: single-user dev/demo.)
- **A2** Enterprise corpus: ≤ 50,000 documents (~5M chunks) in v1; personal uploads ≤ 20 files/user, ≤ 50 MB docs / 500 MB CSV per file.
- **A3** Enterprise DBs are reachable from the host machine (or Docker network) and expose a read replica or reporting schema; in Phase 2 (cloud), via VPN/Direct Connect/PrivateLink.
- **A4** Phase 1: single local machine. Phase 2: one primary cloud region; disaster recovery deferred beyond the first release.
- **A5** LLM provider available and API key configured. Phase 1 default: Anthropic API or Ollama local. Phase 2: same via LiteLLM proxy.
- **A6** Users are all employees of one company (single tenant).

## 6. Constraints and risks
| Risk | Mitigation |
|------|-----------|
| LLM API rate limits too low for peak | LiteLLM proxy retry + backoff; fast-class routing reduces expensive calls; Celery queue provides natural backpressure; Ollama removes API rate limits entirely for local dev |
| Text-to-SQL hallucination / wrong joins | Curated semantic catalog, AST validation, self-correction loop, show SQL to user, golden-set eval |
| Cross-source joins exploding in size | Pushdown filters/aggregations, row/byte caps, sample-first |
| Prompt injection via documents/DB content | Tool output wrapped as data, guardrails, no write tools, least privilege |
| Data leakage via shared enterprise index | ACL stored on every chunk, enforced in query (and RLS as backstop) |
| LLM cost overrun | Per-run & per-user budgets, semantic cache, alerts |
