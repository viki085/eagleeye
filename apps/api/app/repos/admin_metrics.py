"""Aggregates for the admin console (parameterised SQL only).

Privacy: counts, costs, reasons and statuses only — never chat content, blocked inputs or SQL
text. Times are UTC. Runs from before Phase 6 have no first_token_at/finished_at/warnings;
durations fall back to updated_at, and time-to-first-token only counts runs that have it.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import asyncpg

Range = Literal["24h", "7d", "30d"]
TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED", "BUDGET_EXCEEDED")
USER_SORTS = {
    "last_seen": "u.last_seen_at DESC NULLS LAST",
    "cost": "cost_usd DESC",
    "runs": "runs DESC",
    "email": "u.email ASC",
}
MAX_PAGE = 100


@dataclass(frozen=True)
class Window:
    span: timedelta
    bucket: str  # date_trunc unit
    step: timedelta


WINDOWS: dict[str, Window] = {
    "24h": Window(timedelta(hours=24), "hour", timedelta(hours=1)),
    "7d": Window(timedelta(days=7), "day", timedelta(days=1)),
    "30d": Window(timedelta(days=30), "day", timedelta(days=1)),
}


def _num(value: Any) -> float:
    return round(float(value or 0), 6)


def _rows(records: list[asyncpg.Record]) -> list[dict[str, Any]]:
    return [dict(r) for r in records]


async def overview(pool: asyncpg.Pool, w: Window) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        SELECT count(DISTINCT user_id) AS active_users,
               count(*) AS runs,
               count(*) FILTER (WHERE status = 'SUCCEEDED') AS succeeded,
               count(*) FILTER (WHERE status IN ('FAILED', 'BUDGET_EXCEEDED')) AS failed,
               count(*) FILTER (WHERE status = 'CANCELLED') AS cancelled,
               count(*) FILTER (WHERE degraded) AS degraded,
               coalesce(sum(cost_usd), 0) AS cost_usd,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM
                   coalesce(finished_at, updated_at) - created_at))
                   FILTER (WHERE status = ANY($2)) AS p50_duration_s,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM
                   coalesce(finished_at, updated_at) - created_at))
                   FILTER (WHERE status = ANY($2)) AS p95_duration_s,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM
                   first_token_at - created_at))
                   FILTER (WHERE first_token_at IS NOT NULL) AS p50_ttft_s,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM
                   first_token_at - created_at))
                   FILTER (WHERE first_token_at IS NOT NULL) AS p95_ttft_s
          FROM runs WHERE created_at >= now() - $1::interval
        """,
        w.span,
        list(TERMINAL),
    )
    series = await pool.fetch(
        """
        SELECT b.bucket,
               count(r.id) AS runs,
               count(DISTINCT r.user_id) AS users,
               coalesce(sum(r.cost_usd), 0) AS cost_usd,
               count(r.id) FILTER (WHERE r.status IN ('FAILED', 'BUDGET_EXCEEDED')) AS failed
          FROM generate_series(date_trunc($2::text, now() - $1::interval),
                               date_trunc($2::text, now()), $3::interval) AS b(bucket)
          LEFT JOIN runs r ON date_trunc($2::text, r.created_at) = b.bucket
                          AND r.created_at >= now() - $1::interval
         GROUP BY b.bucket ORDER BY b.bucket
        """,
        w.span,
        w.bucket,
        w.step,
    )
    data = dict(row)
    runs = data["runs"] or 0
    for key in ("cost_usd", "p50_duration_s", "p95_duration_s", "p50_ttft_s", "p95_ttft_s"):
        data[key] = None if data[key] is None else _num(data[key])
    data["cost_per_run_usd"] = _num(data["cost_usd"] / runs) if runs else 0.0
    data["series"] = [
        {**dict(s), "bucket": s["bucket"].isoformat(), "cost_usd": _num(s["cost_usd"])}
        for s in series
    ]
    return data


async def users(
    pool: asyncpg.Pool, w: Window, sort: str, offset: int, limit: int, usage_limit: float
) -> dict[str, Any]:
    order = USER_SORTS.get(sort, USER_SORTS["last_seen"])
    rows = await pool.fetch(
        f"""
        SELECT u.id, u.email, u.role, u.status, u.last_seen_at, u.created_at,
               coalesce(r.runs, 0) AS runs, coalesce(r.cost_usd, 0) AS cost_usd,
               coalesce(r.tokens, 0) AS tokens, r.last_run_at,
               coalesce(l.lifetime_cost, 0) AS lifetime_cost_usd
          FROM users u
          LEFT JOIN (
                SELECT user_id, count(*) AS runs, sum(cost_usd) AS cost_usd,
                       sum(coalesce((usage->>'tokens_in')::bigint, 0)
                           + coalesce((usage->>'tokens_out')::bigint, 0)) AS tokens,
                       max(created_at) AS last_run_at
                  FROM runs WHERE created_at >= now() - $1::interval GROUP BY user_id
               ) r ON r.user_id = u.id
          LEFT JOIN (
                SELECT user_id, sum(cost_usd) AS lifetime_cost FROM usage_ledger GROUP BY user_id
               ) l ON l.user_id = u.id
         ORDER BY {order}, u.email
         LIMIT $2 OFFSET $3
        """,  # noqa: S608 — ORDER BY comes from the USER_SORTS allow-list
        w.span,
        min(max(limit, 1), MAX_PAGE),
        max(offset, 0),
    )
    total = await pool.fetchval("SELECT count(*) FROM users")
    items = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        item["cost_usd"] = _num(item["cost_usd"])
        item["lifetime_cost_usd"] = _num(item["lifetime_cost_usd"])
        item["limit_used_pct"] = (
            round(100 * item["lifetime_cost_usd"] / usage_limit, 2) if usage_limit else None
        )
        for key in ("last_seen_at", "created_at", "last_run_at"):
            item[key] = item[key].isoformat() if item[key] else None
        items.append(item)
    return {"items": items, "total": total, "offset": offset}


async def usage(pool: asyncpg.Pool, w: Window) -> dict[str, Any]:
    by_model = await pool.fetch(
        """
        SELECT day, model_id, sum(cost_usd) AS cost_usd,
               sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out
          FROM usage_ledger WHERE created_at >= now() - $1::interval
         GROUP BY day, model_id ORDER BY day, model_id
        """,
        w.span,
    )
    top_users = await pool.fetch(
        """
        SELECT u.email, sum(l.cost_usd) AS cost_usd, count(DISTINCT l.run_id) AS runs
          FROM usage_ledger l JOIN users u ON u.id = l.user_id
         WHERE l.created_at >= now() - $1::interval
         GROUP BY u.email ORDER BY cost_usd DESC LIMIT 10
        """,
        w.span,
    )
    routes = await pool.fetch(
        """
        SELECT coalesce(route, 'unknown') AS route, count(*) AS runs
          FROM runs WHERE created_at >= now() - $1::interval GROUP BY 1 ORDER BY runs DESC
        """,
        w.span,
    )
    tools = await pool.fetch(
        """
        SELECT s.name, count(*) AS calls,
               count(*) FILTER (WHERE s.status = 'error') AS errors,
               round(avg(s.duration_ms)) AS avg_ms
          FROM run_steps s JOIN runs r ON r.id = s.run_id
         WHERE r.created_at >= now() - $1::interval
           AND s.kind = 'tool' AND s.parent_step_id IS NOT NULL
         GROUP BY s.name ORDER BY calls DESC LIMIT 15
        """,
        w.span,
    )
    return {
        "by_model": [
            {**dict(r), "day": r["day"].isoformat(), "cost_usd": _num(r["cost_usd"])}
            for r in by_model
        ],
        "top_users": [{**dict(r), "cost_usd": _num(r["cost_usd"])} for r in top_users],
        "routes": _rows(routes),
        "tools": [{**dict(r), "avg_ms": int(r["avg_ms"] or 0)} for r in tools],
    }


async def safety(pool: asyncpg.Pool, w: Window) -> dict[str, Any]:
    events = await pool.fetch(
        """
        SELECT kind, category, count(*) AS events
          FROM security_events WHERE created_at >= now() - $1::interval AND kind <> 'admin_action'
         GROUP BY kind, category ORDER BY events DESC
        """,
        w.span,
    )
    sql = await pool.fetch(
        """
        SELECT CASE WHEN rejected_reason LIKE 'DB_ERROR%' THEN 'DB_ERROR'
                    ELSE rejected_reason END AS reason,
               count(*) AS queries
          FROM sql_query_log
         WHERE created_at >= now() - $1::interval AND rejected_reason IS NOT NULL
         GROUP BY 1 ORDER BY queries DESC
        """,
        w.span,
    )
    sql_total = await pool.fetchval(
        "SELECT count(*) FROM sql_query_log WHERE created_at >= now() - $1::interval", w.span
    )
    sandbox = await pool.fetch(
        """
        SELECT mode, status, count(*) AS runs, round(avg(duration_ms)) AS avg_ms
          FROM sandbox_runs WHERE created_at >= now() - $1::interval
         GROUP BY mode, status ORDER BY runs DESC
        """,
        w.span,
    )
    warnings = await pool.fetchrow(
        """
        SELECT count(*) FILTER (WHERE 'unverified_numbers' = ANY(warnings)) AS unverified,
               count(*) AS finished
          FROM runs WHERE created_at >= now() - $1::interval AND finished_at IS NOT NULL
        """,
        w.span,
    )
    failed = await pool.fetch(
        """
        SELECT r.id, r.created_at, u.email, r.status, r.error_code, r.route
          FROM runs r JOIN users u ON u.id = r.user_id
         WHERE r.created_at >= now() - $1::interval AND r.status IN ('FAILED', 'BUDGET_EXCEEDED')
         ORDER BY r.created_at DESC LIMIT 20
        """,
        w.span,
    )
    actions = await pool.fetch(
        """
        SELECT e.created_at, u.email, e.category, e.detail
          FROM security_events e LEFT JOIN users u ON u.id = e.user_id
         WHERE e.kind = 'admin_action' ORDER BY e.created_at DESC LIMIT 20
        """
    )
    return {
        "events": _rows(events),
        "sql_rejections": _rows(sql),
        "sql_queries": sql_total,
        "sandbox": [{**dict(r), "avg_ms": int(r["avg_ms"] or 0)} for r in sandbox],
        "unverified_figures": dict(warnings),
        "failed_runs": [
            {**dict(r), "id": str(r["id"]), "created_at": r["created_at"].isoformat()}
            for r in failed
        ],
        "admin_actions": [{**dict(r), "created_at": r["created_at"].isoformat()} for r in actions],
    }


async def content(pool: asyncpg.Pool) -> dict[str, Any]:
    docs = await pool.fetch(
        """
        SELECT scope, status, count(*) AS documents, coalesce(sum(chunk_count), 0) AS chunks
          FROM documents GROUP BY scope, status ORDER BY scope, status
        """
    )
    doc_failures = await pool.fetch(
        """
        SELECT title, scope, error, updated_at FROM documents
         WHERE status = 'FAILED' ORDER BY updated_at DESC LIMIT 10
        """
    )
    datasets = await pool.fetch(
        """
        SELECT status, count(*) AS files, coalesce(sum(row_count), 0) AS rows
          FROM datasets GROUP BY status ORDER BY status
        """
    )
    data_failures = await pool.fetch(
        """
        SELECT title, error, updated_at FROM datasets
         WHERE status = 'FAILED' ORDER BY updated_at DESC LIMIT 10
        """
    )
    return {
        "documents": _rows(docs),
        "document_failures": [
            {**dict(r), "updated_at": r["updated_at"].isoformat()} for r in doc_failures
        ],
        "datasets": _rows(datasets),
        "dataset_failures": [
            {**dict(r), "updated_at": r["updated_at"].isoformat()} for r in data_failures
        ],
    }


async def run_counts(pool: asyncpg.Pool, running_stale_s: int, queued_stale_s: int) -> dict:
    row = await pool.fetchrow(
        """
        SELECT count(*) FILTER (WHERE status IN ('QUEUED', 'RUNNING')) AS active,
               count(*) FILTER (WHERE (status = 'RUNNING' AND coalesce(heartbeat_at, updated_at)
                                         < now() - make_interval(secs => $1))
                                   OR (status = 'QUEUED'
                                       AND created_at < now() - make_interval(secs => $2)))
                   AS stuck
          FROM runs WHERE status IN ('QUEUED', 'RUNNING')
        """,
        running_stale_s,
        queued_stale_s,
    )
    return dict(row)


async def record_admin_action(
    pool: asyncpg.Pool, user_id: str, category: str, detail: dict[str, Any]
) -> None:
    await pool.execute(
        """
        INSERT INTO security_events (user_id, kind, category, detail)
        VALUES ($1, 'admin_action', $2, $3)
        """,
        user_id,
        category,
        detail,
    )
