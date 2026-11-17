"""Demo visitor allowances (Phase 7). See supabase/migrations/20261117000016_demo_visits.sql.

Every sign-in with the shared demo credentials is a Clerk session. The first request of a
session is mapped to the visit of the visitor's IP (IPv6: its /64) for the last 24 hours, or a
new visit is created with its own internal account (and references to the sample files). The
API then acts as that account, so visitors never see each other's data, and the account's
usage_limit_usd is the visit's budget. Time is counted from heartbeats sent while the app is
open; the limits live in the database (demo_limits()).

Visits from a network on the exempt list (demo_exempt_networks, scripts/demo_exempt.py: the
owner's own connection) have no time or budget limit and are left out of the daily cap.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

HEARTBEAT_CAP_S = 75  # a gap longer than this means the app was closed: count at most this
WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class Limits:
    visit_seconds: int
    visit_budget_usd: float
    daily_budget_usd: float


@dataclass(frozen=True)
class VisitState:
    visit_id: str
    user_id: str
    seconds_left: int
    budget_left_usd: float
    window_ends_at: datetime
    exhausted: str | None  # "time" | "budget" | "daily" | None
    available_at: datetime | None
    exempt: bool = False  # a tester network: no limits

    def public(self) -> dict[str, Any]:
        """For the app: time left and whether the visit is over (no money figures)."""
        return {
            "seconds_left": self.seconds_left,
            "exhausted": self.exhausted,
            "available_at": self.available_at.isoformat() if self.available_at else None,
        }


async def limits(db: Any) -> Limits:
    row = await db.fetchrow("SELECT * FROM demo_limits()")
    return Limits(int(row[0]), float(row[1]), float(row[2]))


async def _visit_of_session(db: Any, session_id: str) -> Any:
    return await db.fetchrow(
        """
        SELECT v.id, v.user_id FROM demo_sessions s JOIN demo_visits v ON v.id = s.visit_id
         WHERE s.clerk_session_id = $1 AND v.window_start > now() - interval '24 hours'
        """,
        session_id,
    )


async def _create_visit(db: Any, base_user_id: str, key: str, budget: float) -> str:
    """A visit account (never matches a real sign-in) with references to the sample files."""
    user_id, tag = str(uuid.uuid4()), uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO users (id, clerk_user_id, email, display_name, role, is_demo, usage_limit_usd)
        VALUES ($1, $2, $3, 'Demo visitor', 'member', true, $4)
        """,
        user_id,
        f"demo-visit:{tag}",
        f"demo-visit-{tag}@demo.invalid",
        budget,
    )
    visit_id = await db.fetchval(
        "INSERT INTO demo_visits (ip_key, user_id) VALUES ($1, $2) RETURNING id", key, user_id
    )
    # the same processed files (no re-ingestion); the visitor can't delete these
    await db.execute(
        """
        INSERT INTO datasets (id, owner_id, origin, title, filename, sheet, s3_key_original,
                              s3_key, status, error, columns, column_map, row_count, size_bytes,
                              sha256, profile, summary)
        SELECT gen_random_uuid(), $2, origin, title, filename, sheet, s3_key_original, s3_key,
               status, error, columns, column_map, row_count, size_bytes, sha256, profile, summary
          FROM datasets WHERE owner_id = $1 AND status = 'READY'
        """,
        base_user_id,
        user_id,
    )
    return str(visit_id)


async def account_for_session(db: Any, base_user_id: str, session_id: str, ip: str) -> str:
    """The visit account to act as for this demo sign-in session (created on first use)."""
    if hasattr(db, "acquire"):  # a pool: the creation below needs one connection's transaction
        async with db.acquire() as conn:
            return await account_for_session(conn, base_user_id, session_id, ip)
    found = await _visit_of_session(db, session_id)
    if found is not None:
        return str(found["user_id"])
    async with db.transaction():
        key = await db.fetchval("SELECT demo_ip_key($1)", ip)
        # one visit per IP even when a visitor's first requests arrive together
        await db.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"demo-visit:{key}")
        visit = await db.fetchrow(
            """
            SELECT id, user_id FROM demo_visits
             WHERE ip_key = $1 AND window_start > now() - interval '24 hours'
             ORDER BY window_start DESC LIMIT 1
            """,
            key,
        )
        if visit is None:
            lim = await limits(db)
            visit_id = await _create_visit(db, base_user_id, key, lim.visit_budget_usd)
        else:
            visit_id = str(visit["id"])
        await _apply_exemption(db, visit_id, ip)
        await db.execute(
            """
            INSERT INTO demo_sessions (clerk_session_id, visit_id) VALUES ($1, $2)
            ON CONFLICT (clerk_session_id) DO UPDATE SET visit_id = EXCLUDED.visit_id
            """,
            session_id,
            visit_id,
        )
        return str(await db.fetchval("SELECT user_id FROM demo_visits WHERE id = $1", visit_id))


async def _apply_exemption(db: Any, visit_id: str, ip: str) -> None:
    """Re-checked at every new sign-in session, so a network added to (or removed from) the
    list takes effect at the next sign-in. An exempt visit's account has no demo budget (the
    organisation's normal spend limit applies instead)."""
    exempt = bool(await db.fetchval("SELECT demo_exempt($1)", ip))
    lim = await limits(db)
    await db.execute(
        """
        WITH v AS (UPDATE demo_visits SET exempt = $2 WHERE id = $1 RETURNING user_id)
        UPDATE users SET usage_limit_usd = CASE WHEN $2 THEN NULL ELSE $3::numeric END
         WHERE id = (SELECT user_id FROM v)
        """,
        visit_id,
        exempt,
        lim.visit_budget_usd,
    )


def _today_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def state_of(db: Any, user_id: str) -> VisitState | None:
    row = await db.fetchrow(
        """
        SELECT v.id, v.user_id, v.window_start, v.seconds_used, v.exempt,
               (SELECT coalesce(sum(cost_usd), 0) FROM runs WHERE user_id = v.user_id) AS spent,
               now() AS now
          FROM demo_visits v WHERE v.user_id = $1
        """,
        user_id,
    )
    if row is None:
        return None
    lim = await limits(db)
    now: datetime = row["now"]
    today = await db.fetchval(
        """
        SELECT coalesce(sum(r.cost_usd), 0) FROM runs r JOIN users u ON u.id = r.user_id
         WHERE u.is_demo AND r.created_at >= $1
           AND NOT EXISTS (SELECT 1 FROM demo_visits ev WHERE ev.user_id = u.id AND ev.exempt)
        """,
        _today_start(now),
    )
    window_ends = row["window_start"] + WINDOW
    seconds_left = max(lim.visit_seconds - int(row["seconds_used"]), 0)
    budget_left = max(lim.visit_budget_usd - float(row["spent"]), 0.0)
    exhausted, available = None, None
    exempt = bool(row["exempt"])
    if exempt:  # a tester network: the full allowance, always
        seconds_left, budget_left = lim.visit_seconds, lim.visit_budget_usd
    elif float(today) >= lim.daily_budget_usd:
        exhausted, available = "daily", _today_start(now) + timedelta(days=1)
    elif seconds_left <= 0:
        exhausted, available = "time", window_ends
    elif budget_left <= 0:
        exhausted, available = "budget", window_ends
    return VisitState(
        str(row["id"]),
        str(row["user_id"]),
        seconds_left,
        budget_left,
        window_ends,
        exhausted,
        available,
        exempt,
    )


async def heartbeat(db: Any, session_id: str) -> VisitState | None:
    """Counts the time since this session's last heartbeat (at most HEARTBEAT_CAP_S)."""
    row = await db.fetchrow(
        """
        WITH old AS (SELECT visit_id, last_seen_at FROM demo_sessions WHERE clerk_session_id = $1)
        UPDATE demo_sessions s SET last_seen_at = now() FROM old
         WHERE s.clerk_session_id = $1
        RETURNING s.visit_id, extract(epoch FROM now() - old.last_seen_at) AS elapsed
        """,
        session_id,
    )
    if row is None:
        return None
    seconds = min(max(int(row["elapsed"] or 0), 0), HEARTBEAT_CAP_S)
    user_id = await db.fetchval(
        "UPDATE demo_visits SET seconds_used = seconds_used + $2 WHERE id = $1 RETURNING user_id",
        row["visit_id"],
        seconds,
    )
    return await state_of(db, str(user_id))


MESSAGES = {
    "time": "Your 30 minutes of demo time for today are used up.",
    "budget": "Your demo budget for AI answers is used up for today.",
    "daily": "The demo has reached today's limit for all visitors.",
}


def refusal_message(state: VisitState) -> str:
    when = (
        state.available_at.astimezone(UTC).strftime("%H:%M UTC on %d %b")
        if state.available_at
        else ""
    )
    again = f" You can try again after {when}." if when else ""
    return f"{MESSAGES.get(state.exhausted or '', 'The demo is not available right now.')}{again}"
