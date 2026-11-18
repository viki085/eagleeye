"""Aggregates for the admin console (parameterised SQL only).

Privacy: counts, costs, reasons and statuses only — never chat content, blocked inputs or SQL
text. Times are UTC. Runs from before Phase 6 have no first_token_at/finished_at/warnings;
durations fall back to updated_at, and time-to-first-token only counts runs that have it.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import asyncpg

from app.repos.admin_presence import ONLINE_S

Range = Literal["24h", "7d", "14d", "30d"]
TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED", "BUDGET_EXCEEDED")
# active since their last sign-out (a sign-out takes them offline at once)
SIGNED_IN = "(u.signed_out_at IS NULL OR u.signed_out_at < u.last_seen_at)"
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
    "1h": Window(timedelta(hours=1), "minute", timedelta(minutes=1)),  # live view, e.g. a load test
    "24h": Window(timedelta(hours=24), "hour", timedelta(hours=1)),
    "7d": Window(timedelta(days=7), "day", timedelta(days=1)),
    "14d": Window(timedelta(days=14), "day", timedelta(days=1)),
    "30d": Window(timedelta(days=30), "day", timedelta(days=1)),
}


def _num(value: Any) -> float:
    return round(float(value or 0), 6)


def _rows(records: list[asyncpg.Record]) -> list[dict[str, Any]]:
    return [dict(r) for r in records]


async def users(
    pool: asyncpg.Pool,
    w: Window,
    sort: str,
    offset: int,
    limit: int,
    usage_limit: float,
    online_only: bool = False,
) -> dict[str, Any]:
    order = USER_SORTS.get(sort, USER_SORTS["last_seen"])
    # demo visit accounts are internal (shown in the Demo visitors panel, not as users)
    where = "u.status <> 'deleted' AND u.clerk_user_id NOT LIKE 'demo-visit:%'"
    if online_only:
        where += f" AND u.last_seen_at >= now() - interval '{ONLINE_S} seconds' AND {SIGNED_IN}"
    rows = await pool.fetch(
        f"""
        SELECT u.id, u.email, u.username, u.display_name, u.role, u.status,
               u.last_seen_at, u.created_at,
               coalesce(r.runs, 0) AS runs, coalesce(p.cost_usd, 0) AS cost_usd,
               coalesce(p.tokens, 0) AS tokens, r.last_run_at,
               coalesce(l.lifetime_cost, 0) AS lifetime_cost_usd,
               coalesce(u.last_seen_at >= now() - interval '{ONLINE_S} seconds' AND {SIGNED_IN},
                        false) AS online
          FROM users u
          LEFT JOIN (
                SELECT user_id, count(*) AS runs, max(created_at) AS last_run_at
                  FROM runs WHERE created_at >= now() - $1::interval GROUP BY user_id
               ) r ON r.user_id = u.id
          LEFT JOIN (  -- billing from the ledger: survives chat deletion
                SELECT user_id, sum(cost_usd) AS cost_usd,
                       sum(tokens_in + tokens_out) AS tokens
                  FROM usage_ledger WHERE created_at >= now() - $1::interval GROUP BY user_id
               ) p ON p.user_id = u.id
          LEFT JOIN (
                SELECT user_id, sum(cost_usd) AS lifetime_cost FROM usage_ledger GROUP BY user_id
               ) l ON l.user_id = u.id
         WHERE {where}
         ORDER BY {order}, u.email
         LIMIT $2 OFFSET $3
        """,  # noqa: S608 — ORDER BY from the USER_SORTS allow-list; WHERE from constants
        w.span,
        min(max(limit, 1), MAX_PAGE),
        max(offset, 0),
    )
    total = await pool.fetchval(f"SELECT count(*) FROM users u WHERE {where}")  # noqa: S608
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
