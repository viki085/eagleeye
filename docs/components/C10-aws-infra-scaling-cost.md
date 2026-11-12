# C10 — Infrastructure, Scaling & Cost

## Phase 1 — Local / Docker Compose

### 1.1 Service map (docker-compose.yml)
| Service | Image / Notes | Purpose |
|---------|---------------|---------|
| `nginx` | nginx:alpine | Reverse proxy; routes web/api; terminates local HTTPS if needed |
| `web` | apps/web (Next.js) | Frontend |
| `api` | apps/api (FastAPI) | REST + SSE |
| `agent-worker` | apps/agent-worker (Celery) | Runs LangGraph agent graphs |
| `ingest-worker` | apps/ingest-worker (Celery) | Parse/chunk/embed pipeline |
| `data-gateway` | apps/data-gateway (FastAPI, internal) | SQL execution proxy |
| `redis` | redis:7-alpine | Celery broker + streams + cache + rate limits |
| `qdrant` | qdrant/qdrant | Enterprise vector store |
| `supabase` | Supabase CLI local stack | PostgreSQL + pgvector + Auth + RLS |
| `seaweedfs` | chrislusf/seaweedfs | S3-compatible object store (MinIO replacement — public MinIO images withdrawn) |
| `langfuse` | langfuse/langfuse OSS | LLM traces + evaluation UI |
| `prometheus` | prom/prometheus | Metrics collection |
| `grafana` | grafana/grafana | Dashboards |
| `ollama` _(optional profile)_ | ollama/ollama | Local LLM + embedding (free, no API key) |

### 1.2 Sizing (single-machine dev/demo)
Recommended host: 16 GB RAM, 8-core CPU, 100 GB SSD (more if running Ollama with a 7B+ model).

| Service | RAM target | Notes |
|---------|-----------|-------|
| ollama (7B model) | 8–10 GB | Optional; skip if using Anthropic/OpenAI API |
| qdrant | 2–4 GB | Scales with corpus size |
| supabase local | 1–2 GB | PostgreSQL + API services |
| redis | 512 MB | |
| SeaweedFS | 256 MB | |
| langfuse + postgres | 1 GB | |
| api + workers + gateway | 1–2 GB combined | |

### 1.3 Cost model (Phase 1)
| Item | Cost |
|------|------|
| Compute | $0 (local machine) |
| Qdrant, Redis, SeaweedFS, Langfuse, Prometheus/Grafana | $0 (Docker, open source) |
| Supabase local (Supabase CLI) | $0 |
| LLM — Anthropic API or OpenAI | Pay-per-use (optional; use Ollama for $0) |
| LLM — Ollama (local models) | $0 (electricity only) |
| **Total compute** | **~$0 (only LLM API if not using Ollama)** |

---

## Phase 2 — Cloud / AWS

### 2.1 Accounts & environments
AWS Organizations: `shared-services` (ECR, CI roles), `dev`, `staging`, `prod`, `security/log-archive`. Control Tower landing zone + SCPs. Terraform modules per layer (network, data, compute, edge, observability); remote state in S3 + DynamoDB lock; GitHub Actions with OIDC (no static AWS keys). Staging mirrors prod topology at ~25% size.

### 2.2 Network
VPC /16, 3 AZs; public (ALB, NAT), private-app, isolated-data subnets. NAT per AZ (or one in non-prod). VPC endpoints: S3 (gateway), Secrets Manager, KMS, ECR api/dkr, CloudWatch Logs, STS, SSM. Enterprise DB connectivity: Site-to-Site VPN (start) → Direct Connect (if needed) via Transit Gateway; security group + route only from the `data-gateway` subnet.

### 2.3 Edge
Route 53 → CloudFront (static assets cache; `/api/*` and SSE bypass cache, `ResponseTimeout` raised; origin keep-alive) → AWS WAF (managed rule groups + rate rules) → ALB (idle timeout 300 s; HTTP/2). ACM certs.

### 2.4 Compute (ECS Fargate)
| Service | Role | Size (start) | Min–Max tasks | Scale on |
|---------|------|--------------|---------------|----------|
| web | Next.js | 1 vCPU / 2 GB | 2–10 | CPU, req/s |
| api | REST + SSE tail | 1 vCPU / 2 GB | 3–20 | CPU, connections (SSE ~500/task) |
| agent-worker | Celery + LangGraph (I/O bound, async) | 2 vCPU / 4 GB | 4–60 | **active runs per task** (target ~25), Redis queue lag |
| ingest-worker | Celery: parse/chunk/embed | 4 vCPU / 8 GB | 1–30 | Redis queue depth/age |
| data-gateway | SQL execution proxy | 1 vCPU / 2 GB | 2–10 | CPU, in-flight queries |
| qdrant | Vector store (ECS or managed) | 4 vCPU / 16 GB | 1–3 | collection size, query latency |
| langfuse | LLM observability | per Langfuse docs | 2 | — |
| Lambda `analysis-sandbox` | EDA/DuckDB | 3–10 GB | concurrency reserved 200 | requests |

Spot capacity for ingest-worker; On-Demand for the rest. Graceful shutdown: Celery workers stop claiming, finish/checkpoint in-flight runs (ECS stopTimeout 120 s).

### 2.5 Data tier
- **Supabase Cloud (or self-hosted on RDS)**: PostgreSQL 16 with pgvector, RLS, PITR (continuous backup), read replicas for retrieval queries. Replaces Aurora — same SQL dialect, simpler pricing, built-in auth integration.
- **Qdrant (ECS or Qdrant Cloud)**: enterprise vector store; replaces pgvector at scale. Collections per environment.
- **ElastiCache Redis 7** (cluster mode, 3 shards × 1 replica, Multi-AZ, in-transit + at-rest encryption, `cache.r7g.large`): Celery broker, streams, locks, cache, rate limits. Persistence not relied upon for correctness (Supabase PG is source of truth).
- **S3**: SSE-KMS, versioning, lifecycle rules, CRR for docs/data; Object Lock on audit bucket.
- **Celery + Redis** broker: replaces SQS for all async task queuing. `ingest` queue + `agent` queue + dead-letter set in Redis.
- **Secrets Manager / SSM / AppConfig** for secrets, params, feature flags.

### 2.6 LLM — LiteLLM proxy
Provider-agnostic via `LLM_PROVIDER` env var (Anthropic, OpenAI, or Ollama). No Bedrock dependency. Per-model concurrency limits in `LLMGateway`; quota increase requests filed with provider as needed. Model IDs/prices in config.

### 2.7 Capacity model (assumptions A1)
- 10,000 users; ~1,500 DAU; ~60k turns/day; peak ≈ 4 turns/s, ~1,000 concurrent open chats, ~150–250 concurrent *active runs*.
- Per turn (typical mix): guard ~0.4k in/0.05k out (fast-class) + rewrite ~0.8k/0.15k (fast-class) + answer/supervisor ~6k in/0.6k out (capable-class; ≈ 2 calls for complex, 1 for simple) → average ≈ 8k in, 0.8k out across models.
- Peak LLM load ≈ 4 turns/s × ~2.5 calls ≈ 10 calls/s → verify provider RPM/TPM quotas. Mitigations: prompt caching, simple-path routing, semantic cache, queue-shed with fair-use, provider fallback.
- SSE connections: 1,000–2,000 concurrent → ~4 api tasks at 500/task; headroom to 10,000 at 20 tasks.
- Supabase PG: retrieval ~40 index queries/s peak (personal scope, pgvector); comfortable for 2 readers. Enterprise scope served by Qdrant.

### 2.8 Resilience matrix
| Failure | Effect | Mitigation |
|---------|--------|-----------|
| AZ loss | Capacity −33% | Multi-AZ services, Supabase failover, Redis replica promotion |
| Supabase failover | Brief write errors | Connection retry, runs resume via LangGraph checkpoint in Supabase PG |
| Redis node loss | Stream loss for active runs | Cluster failover; client resubscribe; run state in Supabase PG; sweeper requeues |
| LLM provider outage | Slow/failed LLM calls | Backoff, circuit breaker, fallback model/provider chain, degraded mode, status banner |
| Enterprise DB down | SQL unavailable | Per-source circuit breaker; other tools continue |
| Poison ingest doc | Celery queue stuck | Dead-letter after 3 tries, per-doc isolation |
| Region loss | Full outage | DR deferred (not required for portfolio v1); Supabase PG backup restore; S3 CRR |

### 2.9 CI/CD
GitHub Actions: lint/type/test (80% coverage gate), SAST/SCA, build images (SBOM, Trivy), push to ECR (immutable tags = commit SHA), Terraform plan on PR, deploy via ECS rolling/blue-green (CodeDeploy) with automatic rollback on alarms; DB migrations as a pre-deploy job (expand/contract); smoke + Playwright E2E in staging; manual approval to prod; feature flags for risky features; one-command rollback to prior SHA.

### 2.10 Cost model (rough, monthly, Phase 2 prod; **order-of-magnitude, to be validated**)
Pricing assumptions (confirm against current price lists): capable-class ≈ $3/$15 per M input/output tokens; fast-class ≈ $1/$5 (illustrative). 60k turns/day ≈ 1.8M turns/month.

| Item | Basis | Est. $/month |
|------|-------|--------------|
| LLM — capable-class | ~45% of turns × ~7k in / 0.7k out (≈ 30–40% less with prompt caching + semantic cache) | ~$11k |
| LLM — fast-class (guard, rewrite, summaries, titles) | ~1.8M turns × ~1.5k in / 0.2k out | ~$4k |
| Embeddings & enrichment | ingestion + queries | ~$0.3–1k |
| Supabase Cloud (or self-hosted) | PostgreSQL + pgvector + storage | ~$1–2k |
| Qdrant (ECS or Qdrant Cloud) | 5M chunks, 1024-d | ~$0.5–1k |
| ElastiCache Redis | 6 nodes r7g.large | ~$1.5k |
| ECS Fargate | ~25 avg tasks mixed | ~$2–3k |
| Lambda sandbox, S3, SeaweedFS→S3 | usage-based | ~$0.5–1k |
| Network (NAT, endpoints, CloudFront, WAF, DX/VPN) | | ~$1.5–3k |
| Observability (CloudWatch, Langfuse infra, Grafana) | | ~$1–2k |
| Misc (Secrets, KMS, GuardDuty, Inspector) | | ~$0.5–1k |
| **Total** | | **≈ $22–30k / month (~$2–3 per user/month; ~$0.012–0.017 per turn)** |

LLM is ~50–60% of cost → biggest levers: simple-path routing, prompt caching, semantic cache, top-k reduction, fast-class for sub-tasks, per-user quotas, Ollama for non-critical workloads. Per-run budget cap ($0.25) bounds worst case; org daily budget alarm.

### 2.11 Environments & data policy
Dev uses synthetic data only; staging uses masked copies; prod data never leaves prod accounts. Separate Clerk instances per env. Separate guardrail configs per env.
