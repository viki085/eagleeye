# C5 — Text-to-SQL & Data Gateway

Goal: user asks in natural language; system produces a **correct, safe, permitted, read-only** SQL query on enterprise databases, shows the SQL and result, and explains it.

## 1. Components

```mermaid
flowchart LR
  SA[SQL agent] --> CAT[Catalog retrieval]
  CAT --> PGC[(catalog_* tables + embeddings)]
  SA -->|candidate SQL| VAL[sqlsafe validator]
  VAL -->|valid| DG[Data Gateway]
  VAL -->|invalid + reason| SA
  DG --> DB[(Enterprise DB read replica)]
  DG --> S3[(Result Parquet)]
  DG -->|schema, sample ≤50 rows, stats| SA
```

## 2. Semantic catalog (the key to accuracy)
Raw schemas alone yield poor SQL. We maintain a **catalog** per data source:
- **Tables & columns** with business descriptions (LLM-drafted at onboarding, **reviewed by data admins**), types, PK/FK, units, enumerations of low-cardinality values (masked if sensitive), sample values.
- **Metrics/definitions** (`catalog_metrics`): "revenue = SUM(net_amount) WHERE status='paid'", "active customer = purchase in last 90 days".
- **Join hints** & **golden example queries** (question → SQL) used as few-shot.
- Embeddings on table/column/metric descriptions for retrieval.
- **Refresh**: nightly job diffs the live schema (information_schema) → bumps `schema_version`, flags changed/removed objects; admins notified for new tables (default disabled until approved).
- Sensitivity flags drive what the LLM may see (C2 §3).

Retrieval per question: embed question → top-N tables/columns/metrics/examples **filtered by the user's grants** → compact schema prompt (≈ 1–3k tokens: DDL-like text with descriptions + FKs). If more than one source matches, the supervisor picks (or asks).

## 3. SQL agent loop (max 4 LLM calls, 3 executions)
1. Decide: need `describe_tables`/distinct-values lookups? (cheap tool: `SELECT DISTINCT col LIMIT 50`, itself validated).
2. Generate **one SELECT** (engine dialect specified) with explanatory comment/assumptions.
3. **Validate** (below). On failure → feed back error reason → regenerate.
4. Execute via gateway. On DB error (unknown column, type) → feed the error → regenerate (self-correction).
5. Sanity checks: zero rows (verify filters via distinct values), suspiciously huge rows (re-aggregate), obvious join fan-out (compare count with/without join if flagged).
6. Return artifact id, SQL, row count, preview ≤ 50 rows. UI shows SQL (collapsible) + table; model writes explanation **from the result**.

If ambiguous (metric/time range/entity), ask a single clarifying question instead of guessing.

## 4. `sqlsafe` validator (deterministic; sqlglot AST)
Applied in the agent worker (fast feedback) **and again in the gateway** (trust boundary).
| Check | Rule |
|-------|------|
| Statement type | Exactly one statement; root must be `SELECT` (CTEs allowed). Reject DDL/DML, `INTO`, `COPY`, `CALL`, procedure/exec, multiple statements, comments tricks |
| Tables/columns | Every referenced table ∈ user's allowed set; every column resolves in catalog; restricted/PII columns blocked or masked wrappers |
| Functions | Allow-list (aggregates, date/string/math); deny `pg_read_file`, `dblink`, `xp_cmdshell`, `lo_*`, system catalogs, sleep functions |
| Cost | Reject cartesian joins (no join predicate), `SELECT *` on wide/large tables (expanded to allowed columns), unbounded `ORDER BY` without limit |
| Rewrites | Inject/lower `LIMIT` (default 10,000 for artifact; 50 for LLM preview), inject row-filter predicates from `source_grants.row_filter_sql`, add dialect-specific timeout hint |
| Parameters | Literals extracted; no string concatenation of user input into identifiers |

## 5. Data Gateway service
- **Placement**: Phase 1 (local): Docker internal network — data-gateway container is not routed through Nginx and is unreachable from outside the compose network; enterprise DBs reachable from the host via localhost or Docker host network. Phase 2 (cloud): private subnets; only the gateway has a network path and credentials to enterprise DBs (VPN/Direct Connect/PrivateLink via Transit Gateway).
- **Credentials**: Phase 1: `.env` / Docker secrets (never committed). Phase 2: AWS Secrets Manager (`secret_arn` per source), rotation enabled. In both phases the DB account is **read-only**, limited to exposed schemas, pointed at a **read replica/reporting DB** (never OLTP primary).
- **Execution**: connection pools per source (size by source capacity, e.g., 10), `statement_timeout` (default 15 s; max 60 s), row cap, byte cap; streaming fetch → Parquet in SeaweedFS/S3 (`artifacts/…`) → returns `{columns, types, row_count, truncated, sample, stats}`. Per-source concurrency semaphore and per-user rate limit protect the DBs.
- **Dialects/drivers**: SQLAlchemy + psycopg/pymysql/pyodbc (SQL Server)/redshift-connector; adapter interface `SourceAdapter{validate_dialect, explain_cost, execute}`. Optional `EXPLAIN` pre-check to reject plans with estimated rows/cost over threshold.
- **Auditing**: every statement logged to `sql_query_log` (user, hash, text, rows, duration, rejection reason).
- **Resilience**: circuit breaker per source; on outage the agent reports the source as unavailable and continues with other sources.

## 6. Security specifics
- No dynamic DDL/DML anywhere → no HITL needed in v1.
- DB-native row-level security supported via per-group DB roles or session variables (`SET app.region = …`) when the DB offers it — preferred over `row_filter_sql` where available.
- Prompt injection from data (e.g., a text column saying "ignore instructions"): results wrapped as `<tool_data>`, preview truncated, no write tools exist, guard layer scans.
- Result privacy: only ≤ 50 sampled rows (masked per policy) are sent to the LLM; the full table renders from S3 to the user.

## 7. Evaluation (see C9)
Golden set of ≥ 100 question→SQL→expected result pairs per source; metrics: **execution accuracy** (result equality), exact-match rate, rejection rate, self-correction success, latency, tokens. Gate releases on regressions. Production feedback (👎 on SQL answers) is triaged into new golden cases or catalog fixes (most failures are catalog description gaps, not model gaps).

## 8. Performance targets
Catalog retrieval < 150 ms; SQL generation p50 < 3 s (capable-class); validation < 20 ms; query execution budget 15 s; end-to-end p50 < 10 s for typical questions.

## 9. Open questions
D3: which DB engines and where do they live (network path)? Are there read replicas? Existing data dictionaries/BI semantic layers (dbt, LookML) we can import to bootstrap the catalog? Per-user row-level entitlements?
