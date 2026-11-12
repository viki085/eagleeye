# C6 — EDA, Cross-Source Analysis & Charts

## 1. Concept: everything tabular is a **dataset**
A dataset is a Parquet file in SeaweedFS/S3 plus schema/profile metadata in Supabase PostgreSQL. Sources of datasets:
| Origin | Created by |
|--------|-----------|
| `csv_upload` / `xlsx` | User upload (each sheet = dataset) |
| `query_result` | SQL agent artifact (Data Gateway result) |
| `doc_table` | Table extracted by the RAG parser (optional promote-to-dataset) |
| `enterprise_dataset` | Admin-published curated extracts (optional) |
The Analysis agent works **only** on datasets (not on live DBs), which isolates DB access to the Data Gateway.

## 2. CSV/XLSX ingestion & automatic profile
Pipeline (ingest worker, `UPLOADED → PROFILING → READY`):
1. Validate (size ≤ 500 MB, encoding/delimiter sniff, header detection, row-count cap, formula/macros neutralised — XLSX read as values only, macros ignored).
2. Convert to **Parquet** (typed columns; date parsing with confidence; keep original strings for ambiguous). Column names normalised to safe identifiers (with a mapping to original names).
3. **Profile** (DuckDB + pandas): row/col count, types, null %, distinct count, min/max/mean/median/std/quantiles, top-k categories, string length stats, date range, duplicates, constant/ID-like columns, correlation matrix (numeric), skew/outlier flags (IQR/z-score), data quality warnings (mixed types, impossible values), 20-row sample (PII masked if detected). Stored in `datasets.profile` and `profile.json`.
4. Short LLM-written summary of the dataset (columns' likely meaning) → also indexed in RAG for discovery.

"Run EDA" on a file = the agent reads the profile (instant) and, for deeper asks, calls the sandbox for targeted analysis (group-bys, segment comparisons, trends, time-series decomposition, correlations, simple regression/clustering) — then narrates findings with charts.

## 3. Cross-source combination
Scenario: "Compare monthly sales from the sales DB with my uploaded targets.csv and flag months below target", possibly with policy thresholds from enterprise docs.

Flow:
1. Supervisor decomposes: (a) SQL agent fetches monthly sales (pushdown aggregation at the source) → dataset A; (b) `targets.csv` is dataset B; (c) optional `search_knowledge` for rules.
2. Analysis agent writes **DuckDB SQL** joining A and B (e.g., `JOIN ON month`), computes variance, flags.
3. Result dataset C → table + chart + narration; provenance recorded (A's SQL, B's file, C's DuckDB SQL).

Design rules:
- **Pushdown first**: filter/aggregate in the source DB; never `SELECT *` entire tables to join locally. Gateway row/byte caps apply (default 1M rows / 200 MB per query result); the agent is prompted to aggregate when exceeding.
- **Key alignment** helper: detects join key type/format mismatches (string vs int, date granularity, case/whitespace); agent proposes normalisation and *states the assumption* in the answer.
- **Join quality report**: match rate, unmatched keys on each side, duplicate-key fan-out warning — included in the answer when match rate < 95% or fan-out > 1.
- **Permissions**: datasets derived from restricted sources inherit the **most restrictive** sensitivity; derived artifacts are owner-only.

## 4. Sandbox execution

**Phase 1 (local — Docker subprocess):** The analysis-worker spawns a child process (`subprocess.run`, `--network none`) with an isolated temp directory bind-mounted read-write; no other filesystem paths are writable. Image: `python:3.12-slim` + DuckDB + pandas + numpy + scipy + scikit-learn-light + pyarrow. Limits configured via env (`SANDBOX_MEM_MB`, `SANDBOX_TIMEOUT_S`). Outputs ≤ 20 MB returned inline, larger results streamed to SeaweedFS.

**Phase 2 (cloud — Lambda container):** Same Python image deployed as a Lambda container. No VPC egress; IAM role scoped to `s3://…/sessions/{session_id}/*` via per-invocation STS session policy. Memory 10 GB, timeout 120–300 s, output ≤ 20 MB inline else S3.

Both phases share:
- **Inputs**: list of dataset SeaweedFS/S3 keys + task spec.
- **Two execution modes**:
  1. **DuckDB SQL mode** (preferred; safer, declarative): agent emits SQL over registered views `ds_<id>`; validated by sqlglot (SELECT-only, no `read_csv('http…')`, `COPY`, `ATTACH`, `INSTALL`, extensions disabled via `SET enable_external_access=false`, `lock_configuration=true`).
  2. **Python mode** (EDA/stat tasks beyond SQL): agent writes a short pandas/scipy script; static check (AST allow-list: no `os`, `subprocess`, `socket`, `open` on paths outside the temp dir, no `__import__`/`eval`/`exec`), executed with resource limits; stdout/stderr captured (truncated).
- **Outputs**: result tables (Parquet → artifacts), scalar stats JSON, optional PNG (matplotlib) fallback.
- **Why subprocess vs Lambda**: Phase 1 subprocess is zero-cost and sufficient for single-user local dev. Phase 2 Lambda gives per-invocation Firecracker isolation, instant scale to hundreds of concurrent runs, and no idle cost. The `AnalysisExecutor` port makes the swap transparent to the agent.
- **Failure handling**: timeout/OOM → return structured error to agent (one retry with sampling/aggregation); never hang the run.

## 5. Charts

**Approach**: the agent proposes a *chart intent*; the **Chart tool** (deterministic code) builds and validates a **Vega-Lite** spec bound to an artifact.
1. Intent: `{artifact_id, type: bar|line|area|pie|scatter|hist|box|heatmap|combo, x, y, color?, aggregate?, sort?, title, top_n?}`.
2. Tool validates columns/types exist; picks defaults (e.g., line for temporal x; bar for categorical; limit categories to top 20 + "Other"; log scale suggestion on skew); downsamples large data (LTTB for time series, bin for scatter > 5k pts) server-side — data inlined for ≤ 5k rows, else fetched from the artifact endpoint.
3. **Number grounding**: all plotted data come from the artifact, never typed by the LLM. Annotation text (e.g., "peak: $1.2M") is generated by code from the data.
4. Frontend renders with `vega-embed`, `expr` disabled, tooltip + legend + accessible description (`aria-label` from the spec title/summary), export PNG/SVG.
5. Multiple charts per answer allowed (cap 4).
Fallback: if spec validation fails twice → return a table + text explanation instead.

## 6. Insights
- Compute first, narrate second: statistics (trend slope, YoY/MoM change, top contributors, outliers, correlation strength, segment gaps) computed by DuckDB/pandas; the LLM **receives these numbers** and writes insights. Grounding check (C3 §2.5) rejects unsupported numbers.
- Insight templates guide quality: *What happened → Why it might have (hypotheses, labelled as such) → What to look at next*. Distinguish observation from speculation; show caveats (sample size, missing data, join mismatch).
- Suggested follow-up questions (3) generated from profile/results.

## 7. Limits & cost control
| Limit | Value |
|-------|-------|
| Datasets in one analysis | 6 |
| Rows per analysis input | 5M (DuckDB handles; larger → ask to aggregate) |
| Python mode scripts per run | 3 |
| Sandbox runs per user per hour | 60 |
| Charts per answer | 4 |
Heavy tasks emit `progress` events; if > 60 s the UI shows a "still working" step with stop button.

## 8. Testing
Profile correctness vs pandas reference on fixture CSVs (dirty headers, mixed types, BOM, 1M rows); sandbox escape corpus (network, file, process, resource exhaustion); chart spec validation fuzz; golden EDA questions ("which region has the highest churn?") with numeric tolerance; cross-source join tests with key mismatches.

## 9. Open questions
Max realistic CSV size? Need for Excel with multiple sheets/pivots? Should enterprise-curated datasets (not DB) exist? Preferred chart style guide / brand colours? Ever need forecasting (Prophet/ARIMA) in v1?
