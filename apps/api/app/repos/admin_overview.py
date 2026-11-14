"""The admin console's Overview: KPIs against the previous period, trends, LLM cost by model,
request routing, slowest pipeline steps and the enterprise knowledge base.

Read-only, admin path only: nothing here runs during answer generation. Every query is a
parameterised aggregate over indexed columns (runs.created_at, usage_ledger.created_at,
security_events.created_at, run_steps.run_id). Cost is billing, so it comes from usage_ledger,
which keeps its rows when a chat is deleted. Times are UTC.
"""

from datetime import timedelta
from typing import Any

import asyncpg

from app.repos.admin_metrics import TERMINAL, Window, _num
from app.services.health_checks import ServiceHealth

MAX_MODELS = 5  # donut slices; smaller models fold into "Other"
# Major pipeline stages for the latency trend (sub-steps such as "find tables" are left out
# so the chart stays readable). Order = fixed colour order in the console.
MAJOR_STEPS = ("guard", "planning", "response", "retrieval", "sql_agent", "analysis_agent")
_STEP_GROUP_SQL = """
    CASE
        WHEN s.kind = 'guard' THEN 'guard'
        WHEN s.kind = 'llm' AND s.name = 'plan & answer' THEN 'planning'
        WHEN s.kind = 'llm' AND s.name = 'answer' THEN 'response'
        WHEN (s.kind = 'retrieval' AND s.name = 'search documents')
          OR (s.kind = 'tool' AND s.name = 'search_knowledge') THEN 'retrieval'
        WHEN s.kind = 'tool' AND s.name = 'query_database' THEN 'sql_agent'
        WHEN s.kind = 'tool' AND s.name = 'analyze_data' THEN 'analysis_agent'
    END
"""
MAX_STEPS = 10
DATABASES = {"supabase-pg": "Primary database (Postgres)", "qdrant": "Vector database (Qdrant)"}


def rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def fold_models(rows: list[dict[str, Any]], keep: int = MAX_MODELS) -> list[dict[str, Any]]:
    """Largest `keep` models by cost; the rest summed into one "Other" slice."""
    if len(rows) <= keep:
        return rows
    head, tail = rows[:keep], rows[keep:]
    other = {
        "model_id": "Other",
        "cost_usd": _num(sum(r["cost_usd"] for r in tail)),
        "tokens": sum(r["tokens"] for r in tail),
        "calls": sum(r["calls"] for r in tail),
    }
    return [*head, other]


def database_health(checks: list[ServiceHealth]) -> dict[str, Any]:
    """Primary + vector database pings, summarised for one status card."""
    items = [
        {"name": DATABASES.get(c.name, c.name), "status": c.status, "latency_ms": c.latency_ms}
        for c in checks
    ]
    up = sum(1 for c in checks if c.status == "up")
    primary = next((c for c in checks if c.name == "supabase-pg"), None)
    if primary is None or primary.status != "up":
        status = "down"
    elif up < len(checks):
        status = "degraded"
    else:
        status = "healthy"
    return {
        "status": status,
        "up": up,
        "total": len(checks),
        "primary_latency_ms": primary.latency_ms if primary else None,
        "items": items,
    }


async def _period(pool: asyncpg.Pool, span: timedelta, offset: timedelta) -> dict[str, Any]:
    """KPIs for [now - offset - span, now - offset); offset 0 is this period (no upper bound,
    so rows stamped at this very instant count), offset = span is the previous period."""
    row = await pool.fetchrow(
        """
        SELECT count(DISTINCT user_id) AS active_users,
               count(*) AS requests,
               count(*) FILTER (WHERE status = 'SUCCEEDED') AS succeeded,
               count(*) FILTER (WHERE status IN ('FAILED', 'BUDGET_EXCEEDED')) AS failed,
               count(*) FILTER (WHERE status = 'CANCELLED') AS cancelled,
               count(*) FILTER (WHERE degraded) AS degraded,
               avg(extract(epoch FROM coalesce(finished_at, updated_at) - created_at))
                   FILTER (WHERE status = ANY($3)) AS avg_duration_s,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM
                   coalesce(finished_at, updated_at) - created_at))
                   FILTER (WHERE status = ANY($3)) AS p95_duration_s,
               avg(extract(epoch FROM first_token_at - created_at))
                   FILTER (WHERE first_token_at IS NOT NULL) AS avg_ttft_s
          FROM runs
         WHERE created_at >= now() - $1::interval - $2::interval
           AND ($2::interval = interval '0' OR created_at < now() - $2::interval)
        """,
        span,
        offset,
        list(TERMINAL),
    )
    ledger = await pool.fetchrow(
        """
        SELECT coalesce(sum(cost_usd), 0) AS cost, count(*) AS llm_calls,
               coalesce(sum(tokens_in), 0) AS tokens_in,
               coalesce(sum(tokens_out), 0) AS tokens_out,
               coalesce(sum(cached_tokens), 0) AS cached_tokens
          FROM usage_ledger
         WHERE created_at >= now() - $1::interval - $2::interval
           AND ($2::interval = interval '0' OR created_at < now() - $2::interval)
        """,
        span,
        offset,
    )
    cost = ledger["cost"]
    safety = await pool.fetchval(
        """
        SELECT count(*) FROM security_events
         WHERE kind <> 'admin_action'
           AND created_at >= now() - $1::interval - $2::interval
           AND ($2::interval = interval '0' OR created_at < now() - $2::interval)
        """,
        span,
        offset,
    )
    data = dict(row)
    requests = data["requests"] or 0
    for key in ("avg_duration_s", "p95_duration_s", "avg_ttft_s"):
        data[key] = None if data[key] is None else _num(data[key])
    return {
        **data,
        "success_rate": rate(data["succeeded"], requests),
        "failure_rate": rate(data["failed"], requests),
        "cost_usd": _num(cost),
        "cost_per_request_usd": _num(cost / requests) if requests else None,
        "safety_events": safety,
        "llm_calls": ledger["llm_calls"],
        "tokens_in": int(ledger["tokens_in"]),
        "tokens_out": int(ledger["tokens_out"]),
        "cached_tokens": int(ledger["cached_tokens"]),
        "cache_hit_rate": rate(int(ledger["cached_tokens"]), int(ledger["tokens_in"])),
    }


async def _series(pool: asyncpg.Pool, w: Window) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        WITH b AS (
            SELECT generate_series(date_trunc($2::text, now() - $1::interval),
                                   date_trunc($2::text, now()), $3::interval) AS bucket
        ), r AS (
            SELECT date_trunc($2::text, created_at) AS bucket, count(*) AS requests,
                   count(DISTINCT user_id) AS users,
                   count(*) FILTER (WHERE status IN ('FAILED', 'BUDGET_EXCEEDED')) AS failed,
                   count(*) FILTER (WHERE status = 'SUCCEEDED') AS succeeded,
                   avg(extract(epoch FROM coalesce(finished_at, updated_at) - created_at))
                       FILTER (WHERE status = ANY($4)) AS avg_duration_s
              FROM runs WHERE created_at >= now() - $1::interval GROUP BY 1
        ), l AS (
            SELECT date_trunc($2::text, created_at) AS bucket, sum(cost_usd) AS cost_usd,
                   count(*) AS llm_calls, sum(tokens_in) AS tokens_in,
                   sum(tokens_out) AS tokens_out, sum(cached_tokens) AS cached_tokens
              FROM usage_ledger WHERE created_at >= now() - $1::interval GROUP BY 1
        ), s AS (
            SELECT date_trunc($2::text, created_at) AS bucket, count(*) AS safety_events
              FROM security_events
             WHERE created_at >= now() - $1::interval AND kind <> 'admin_action' GROUP BY 1
        )
        SELECT b.bucket, coalesce(r.requests, 0) AS requests, coalesce(r.users, 0) AS users,
               coalesce(r.failed, 0) AS failed, coalesce(r.succeeded, 0) AS succeeded,
               r.avg_duration_s, coalesce(l.cost_usd, 0) AS cost_usd,
               coalesce(l.llm_calls, 0) AS llm_calls, coalesce(l.tokens_in, 0) AS tokens_in,
               coalesce(l.tokens_out, 0) AS tokens_out,
               coalesce(l.cached_tokens, 0) AS cached_tokens,
               coalesce(s.safety_events, 0) AS safety_events
          FROM b LEFT JOIN r USING (bucket) LEFT JOIN l USING (bucket) LEFT JOIN s USING (bucket)
         ORDER BY b.bucket
        """,
        w.span,
        w.bucket,
        w.step,
        list(TERMINAL),
    )
    return [
        {
            **dict(r),
            "bucket": r["bucket"].isoformat(),
            "cost_usd": _num(r["cost_usd"]),
            "avg_duration_s": None if r["avg_duration_s"] is None else _num(r["avg_duration_s"]),
            "tokens_in": int(r["tokens_in"]),
            "tokens_out": int(r["tokens_out"]),
            "cached_tokens": int(r["cached_tokens"]),
        }
        for r in rows
    ]


BUDGET_ALERTS = (0.75, 0.9)  # alert ticks on the monthly spend bar


async def _month(pool: asyncpg.Pool, budget_usd: float) -> dict[str, Any]:
    """LLM spend in the current calendar month (UTC) against the organisation budget."""
    row = await pool.fetchrow(
        """
        SELECT date_trunc('month', now() AT TIME ZONE 'UTC') AS month_start,
               coalesce(sum(cost_usd), 0) AS spend
          FROM usage_ledger
         WHERE created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
        """
    )
    spend = _num(row["spend"])
    budget = max(float(budget_usd), 0.0)
    return {
        "month_start": row["month_start"].date().isoformat(),
        "spend_usd": spend,
        "budget_usd": budget,
        "remaining_usd": round(max(budget - spend, 0.0), 2),
        "used_fraction": round(spend / budget, 4) if budget else None,
        "alerts": list(BUDGET_ALERTS),
    }


async def _cost_by_model(pool: asyncpg.Pool, span: timedelta) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT model_id, sum(cost_usd) AS cost_usd,
               sum(tokens_in + tokens_out) AS tokens, count(*) AS calls
          FROM usage_ledger WHERE created_at >= now() - $1::interval
         GROUP BY model_id ORDER BY cost_usd DESC, model_id
        """,
        span,
    )
    return fold_models(
        [
            {**dict(r), "cost_usd": _num(r["cost_usd"]), "tokens": int(r["tokens"] or 0)}
            for r in rows
        ]
    )


async def _routes(pool: asyncpg.Pool, span: timedelta) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT coalesce(route, 'unknown') AS route, count(*) AS requests
          FROM runs WHERE created_at >= now() - $1::interval
         GROUP BY 1 ORDER BY requests DESC
        """,
        span,
    )
    return [dict(r) for r in rows]


async def _slow_steps(pool: asyncpg.Pool, span: timedelta) -> list[dict[str, Any]]:
    """Pipeline steps by mean duration (request types are unbalanced, so not totals)."""
    rows = await pool.fetch(
        """
        SELECT s.kind, s.name, count(*) AS executions,
               avg(s.duration_ms) AS avg_ms,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY s.duration_ms) AS p95_ms,
               count(*) FILTER (WHERE s.status = 'error') AS errors
          FROM run_steps s JOIN runs r ON r.id = s.run_id
         WHERE r.created_at >= now() - $1::interval AND s.duration_ms IS NOT NULL
         GROUP BY s.kind, s.name
         ORDER BY avg_ms DESC
         LIMIT $2
        """,
        span,
        MAX_STEPS,
    )
    return [
        {**dict(r), "avg_ms": round(float(r["avg_ms"])), "p95_ms": round(float(r["p95_ms"]))}
        for r in rows
    ]


async def _step_trend(pool: asyncpg.Pool, w: Window) -> list[dict[str, Any]]:
    """Mean duration per bucket for each major stage (buckets with no executions are absent)."""
    rows = await pool.fetch(
        f"""
        SELECT date_trunc($2::text, r.created_at) AS bucket, {_STEP_GROUP_SQL} AS step,
               avg(s.duration_ms) AS avg_ms, count(*) AS executions
          FROM run_steps s JOIN runs r ON r.id = s.run_id
         WHERE r.created_at >= now() - $1::interval AND s.duration_ms IS NOT NULL
         GROUP BY 1, 2 HAVING {_STEP_GROUP_SQL} IS NOT NULL
         ORDER BY 1, 2
        """,  # noqa: S608 — constant SQL fragment, no user input
        w.span,
        w.bucket,
    )
    return [
        {
            "bucket": r["bucket"].isoformat(),
            "step": r["step"],
            "avg_ms": round(float(r["avg_ms"])),
            "executions": r["executions"],
        }
        for r in rows
    ]


async def _step_change(pool: asyncpg.Pool, span: timedelta) -> list[dict[str, Any]]:
    """Each major stage's mean duration this period vs the previous one."""
    rows = await pool.fetch(
        f"""
        SELECT {_STEP_GROUP_SQL} AS step,
               avg(s.duration_ms) FILTER (WHERE r.created_at >= now() - $1::interval) AS avg_ms,
               avg(s.duration_ms) FILTER (WHERE r.created_at < now() - $1::interval) AS prev_avg_ms,
               count(*) FILTER (WHERE r.created_at >= now() - $1::interval) AS executions
          FROM run_steps s JOIN runs r ON r.id = s.run_id
         WHERE r.created_at >= now() - 2 * $1::interval AND s.duration_ms IS NOT NULL
         GROUP BY 1 HAVING {_STEP_GROUP_SQL} IS NOT NULL
        """,  # noqa: S608 — constant SQL fragment, no user input
        span,
    )
    by_step = {r["step"]: r for r in rows}
    return [
        {
            "step": step,
            "avg_ms": None
            if by_step[step]["avg_ms"] is None
            else round(float(by_step[step]["avg_ms"])),
            "prev_avg_ms": None
            if by_step[step]["prev_avg_ms"] is None
            else round(float(by_step[step]["prev_avg_ms"])),
            "executions": by_step[step]["executions"],
        }
        for step in MAJOR_STEPS
        if step in by_step
    ]


async def _knowledge(pool: asyncpg.Pool) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        SELECT count(*) FILTER (WHERE status = 'READY') AS ready,
               count(*) FILTER (WHERE status NOT IN ('READY', 'FAILED')) AS indexing,
               count(*) FILTER (WHERE status = 'FAILED') AS failed,
               coalesce(sum(chunk_count) FILTER (WHERE status = 'READY'), 0) AS chunks
          FROM documents WHERE scope = 'enterprise'
        """
    )
    return dict(row)


async def overview(pool: asyncpg.Pool, w: Window, budget_usd: float = 0.0) -> dict[str, Any]:
    # sequential on purpose: one connection at a time keeps the console's load on the shared
    # database small (and works inside a single test transaction)
    current = await _period(pool, w.span, timedelta(0))
    previous = await _period(pool, w.span, w.span)
    total_users = await pool.fetchval("SELECT count(*) FROM users WHERE status = 'active'")
    return {
        "current": current,
        "previous": previous,
        "total_users": total_users,
        "series": await _series(pool, w),
        "cost_by_model": await _cost_by_model(pool, w.span),
        "routes": await _routes(pool, w.span),
        "slow_steps": await _slow_steps(pool, w.span),
        "step_trend": await _step_trend(pool, w),
        "step_change": await _step_change(pool, w.span),
        "knowledge": await _knowledge(pool),
        "month": await _month(pool, budget_usd),
    }
