"""Who is using EagleEye now (admin console): online counts and the demo visitors' visits.

"Online" = a request within the last ONLINE_S seconds. Company users are measured by
users.last_seen_at (recorded at most once a minute per user, see auth.py); a demo visit by its
sessions' heartbeat time. Demo visit accounts are internal and never listed as users.
No chat content is read; visitor IPs are shown masked to their network.
"""

import ipaddress
from typing import Any

import asyncpg

ONLINE_S = 300
VISIT_HOURS = 24
DEMO_VISIT = "demo-visit:%"
MAX_VISITS = 100

# company users: real accounts, not the shared demo sign-in, not demo visit accounts
_COMPANY = "u.status = 'active' AND NOT coalesce(u.is_demo, false) AND u.clerk_user_id NOT LIKE $1"


def mask_ip(ip_key: str) -> str:
    """'203.0.113.7' → '203.0.113.x'; an IPv6 /64 key → its first two groups + ':…'."""
    base = ip_key.split("/")[0]
    try:
        addr = ipaddress.ip_address(base)
    except ValueError:
        return "hidden"
    if addr.version == 4:
        return ".".join(base.split(".")[:3]) + ".x"
    groups = addr.exploded.split(":")
    return f"{groups[0].lstrip('0') or '0'}:{groups[1].lstrip('0') or '0'}:…"


async def presence(pool: asyncpg.Pool) -> dict[str, Any]:
    row = await pool.fetchrow(
        f"""
        SELECT
          (SELECT count(*) FROM users u WHERE {_COMPANY}
              AND u.last_seen_at >= now() - make_interval(secs => $2)) AS company_online,
          (SELECT count(*) FROM users u WHERE {_COMPANY}
              AND u.last_seen_at >= date_trunc('day', now())) AS company_today,
          (SELECT count(*) FROM users u WHERE {_COMPANY}
              AND u.last_seen_at >= now() - interval '7 days') AS company_7d,
          (SELECT count(DISTINCT s.visit_id) FROM demo_sessions s
              WHERE s.last_seen_at >= now() - make_interval(secs => $2)) AS demo_online,
          (SELECT count(DISTINCT s.visit_id) FROM demo_sessions s
              WHERE s.last_seen_at >= date_trunc('day', now())) AS demo_today,
          (SELECT count(DISTINCT s.visit_id) FROM demo_sessions s
              WHERE s.last_seen_at >= now() - interval '7 days') AS demo_7d
        """,  # noqa: S608 — _COMPANY is a constant
        DEMO_VISIT,
        ONLINE_S,
    )
    return {
        "online_window_s": ONLINE_S,
        "online": {"company": row["company_online"], "demo": row["demo_online"]},
        "today": {"company": row["company_today"], "demo": row["demo_today"]},
        "week": {"company": row["company_7d"], "demo": row["demo_7d"]},
    }


async def demo_visitors(pool: asyncpg.Pool) -> dict[str, Any]:
    limits = await pool.fetchrow("SELECT * FROM demo_limits()")
    rows = await pool.fetch(
        """
        SELECT v.id, v.ip_key, v.window_start, v.seconds_used,
               (SELECT max(s.last_seen_at) FROM demo_sessions s WHERE s.visit_id = v.id)
                   AS last_active,
               (SELECT coalesce(sum(l.cost_usd), 0) FROM usage_ledger l
                 WHERE l.user_id = v.user_id AND l.created_at >= v.window_start) AS spend_usd,
               (SELECT count(*) FROM runs r WHERE r.user_id = v.user_id) AS questions,
               EXISTS (SELECT 1 FROM artifacts a WHERE a.user_id = v.user_id
                        AND a.type = 'notebook') AS notebook_used
          FROM demo_visits v
         WHERE v.window_start >= now() - interval '7 days'
         ORDER BY last_active DESC NULLS LAST
         LIMIT $1
        """,
        MAX_VISITS,
    )
    today = await pool.fetchval(
        """
        SELECT coalesce(sum(l.cost_usd), 0) FROM usage_ledger l
          JOIN users u ON u.id = l.user_id
         WHERE u.clerk_user_id LIKE $1 AND l.created_at >= date_trunc('day', now())
        """,
        DEMO_VISIT,
    )
    online_since = await pool.fetchval("SELECT now() - make_interval(secs => $1)", ONLINE_S)
    expired_before = await pool.fetchval(
        "SELECT now() - make_interval(hours => $1)", VISIT_HOURS
    )
    seconds, budget = int(limits["visit_seconds"]), float(limits["visit_budget_usd"])
    items = []
    for r in rows:
        spend = float(r["spend_usd"])
        if r["window_start"] < expired_before:
            status = "expired"
        elif r["seconds_used"] >= seconds or spend >= budget:
            status = "used_up"
        else:
            status = "active"
        items.append(
            {
                "id": str(r["id"]),
                "network": mask_ip(r["ip_key"]),
                "started_at": r["window_start"].isoformat(),
                "last_active_at": r["last_active"].isoformat() if r["last_active"] else None,
                "online": bool(r["last_active"] and r["last_active"] >= online_since),
                "seconds_used": int(r["seconds_used"]),
                "spend_usd": round(spend, 4),
                "questions": int(r["questions"]),
                "notebook_used": bool(r["notebook_used"]),
                "status": status,
            }
        )
    return {
        "items": items,
        "limits": {
            "visit_seconds": seconds,
            "visit_budget_usd": budget,
            "daily_budget_usd": float(limits["daily_budget_usd"]),
        },
        "today_spend_usd": round(float(today), 4),
    }
