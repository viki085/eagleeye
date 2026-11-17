"""Demo visits against the real local Postgres, inside a rolled-back transaction."""

import json
import uuid

import asyncpg
import pytest
from app.services import demo_visits as dv
from eagleeye_core.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def db():  # noqa: ANN201
    try:
        c = await asyncpg.connect(get_settings().database_url, timeout=3)
    except Exception:
        pytest.skip("local Postgres not available")
    await c.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    tx = c.transaction()
    await tx.start()
    try:
        # other demo spend in the dev database must not affect these tests
        await c.execute("UPDATE users SET is_demo = false WHERE is_demo")
        yield c
    finally:
        await tx.rollback()
        await c.close()


async def base_account(db: asyncpg.Connection) -> str:
    uid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO users (id, clerk_user_id, email, role, is_demo) "
        "VALUES ($1, $2, $3, 'member', true)",
        uid,
        f"clerk_demo_{uid}",
        f"demo-{uid}@test.local",
    )
    await db.execute(
        """
        INSERT INTO datasets (id, owner_id, origin, title, filename, sheet, s3_key_original,
                              s3_key, status, columns, row_count, size_bytes, sha256)
        VALUES (gen_random_uuid(), $1, 'csv_upload', 'sample', 'sample.csv', '', 'k/orig.csv',
                'k/data.parquet', 'READY', '[]'::jsonb, 10, 100, 'abc')
        """,
        uid,
    )
    return uid


async def spend(db: asyncpg.Connection, user_id: str, usd: float) -> None:
    chat = await db.fetchval("INSERT INTO chats (user_id) VALUES ($1) RETURNING id", user_id)
    await db.execute(
        "INSERT INTO runs (chat_id, user_id, status, cost_usd) VALUES ($1, $2, 'SUCCEEDED', $3)",
        chat,
        user_id,
        usd,
    )


async def test_a_new_session_gets_its_own_account_with_the_sample_files(db) -> None:  # noqa: ANN001
    base = await base_account(db)
    visitor = await dv.account_for_session(db, base, "sess_a", "203.0.113.7")
    assert visitor != base
    row = await db.fetchrow(
        "SELECT is_demo, usage_limit_usd, clerk_user_id FROM users WHERE id = $1", visitor
    )
    assert row["is_demo"] and float(row["usage_limit_usd"]) == 1.0
    assert row["clerk_user_id"].startswith("demo-visit:")
    files = await db.fetch("SELECT s3_key FROM datasets WHERE owner_id = $1", visitor)
    assert [f["s3_key"] for f in files] == ["k/data.parquet"]  # shared, not re-processed


async def test_same_ip_resumes_the_visit_and_other_ips_get_their_own(db) -> None:  # noqa: ANN001
    base = await base_account(db)
    first = await dv.account_for_session(db, base, "sess_1", "203.0.113.7")
    again = await dv.account_for_session(db, base, "sess_2", "203.0.113.7")  # signed in again
    v6_a = await dv.account_for_session(db, base, "sess_3", "2001:db8:1:2::10")
    v6_b = await dv.account_for_session(db, base, "sess_4", "2001:db8:1:2:ffff::99")  # same /64
    other = await dv.account_for_session(db, base, "sess_5", "198.51.100.20")
    assert first == again and v6_a == v6_b
    assert len({first, v6_a, other}) == 3
    assert await dv.account_for_session(db, base, "sess_1", "10.0.0.1") == first  # session sticks


async def test_heartbeats_count_time_but_cap_long_gaps(db) -> None:  # noqa: ANN001
    base = await base_account(db)
    visitor = await dv.account_for_session(db, base, "sess_h", "203.0.113.8")
    await db.execute(
        "UPDATE demo_sessions SET last_seen_at = now() - interval '50 seconds' "
        "WHERE clerk_session_id = 'sess_h'"
    )
    state = await dv.heartbeat(db, "sess_h")
    assert state is not None and 1800 - 51 <= state.seconds_left <= 1800 - 49
    await db.execute(
        "UPDATE demo_sessions SET last_seen_at = now() - interval '2 hours' "
        "WHERE clerk_session_id = 'sess_h'"
    )
    later = await dv.heartbeat(db, "sess_h")  # the tab was closed for two hours: counts 75 s
    assert state.seconds_left - later.seconds_left == dv.HEARTBEAT_CAP_S
    assert await dv.heartbeat(db, "unknown_session") is None
    assert (await dv.state_of(db, visitor)).exhausted is None


async def test_time_budget_and_daily_limits(db) -> None:  # noqa: ANN001
    base = await base_account(db)
    timed = await dv.account_for_session(db, base, "sess_t", "203.0.113.9")
    await db.execute("UPDATE demo_visits SET seconds_used = 1800 WHERE user_id = $1", timed)
    state = await dv.state_of(db, timed)
    assert state.exhausted == "time" and state.available_at == state.window_ends_at
    assert "30 minutes" in dv.refusal_message(state) and "try again after" in dv.refusal_message(
        state
    )
    gate = await db.fetchval("SELECT demo_gate('203.0.113.9')")
    assert gate["allowed"] is False and gate["reason"] == "time"

    spender = await dv.account_for_session(db, base, "sess_b", "203.0.113.10")
    await spend(db, spender, 1.0)
    assert (await dv.state_of(db, spender)).exhausted == "budget"
    assert (await db.fetchval("SELECT demo_gate('203.0.113.10')"))["reason"] == "budget"

    fresh = await dv.account_for_session(db, base, "sess_f", "203.0.113.11")
    assert (await dv.state_of(db, fresh)).exhausted is None
    assert (await db.fetchval("SELECT demo_gate('192.0.2.50')"))["allowed"] is True
    await spend(db, fresh, 2.1)  # all demo visitors together now over $3 today
    assert (await dv.state_of(db, fresh)).exhausted == "daily"
    gate = await db.fetchval("SELECT demo_gate('192.0.2.50')")
    assert gate["allowed"] is False and gate["reason"] == "daily"


async def test_a_visit_ends_after_24_hours_and_a_new_one_starts(db) -> None:  # noqa: ANN001
    base = await base_account(db)
    old = await dv.account_for_session(db, base, "sess_old", "203.0.113.12")
    await db.execute(
        "UPDATE demo_visits SET window_start = now() - interval '25 hours', "
        "seconds_used = 1800 WHERE user_id = $1",
        old,
    )
    assert (await db.fetchval("SELECT demo_gate('203.0.113.12')"))["allowed"] is True
    new = await dv.account_for_session(db, base, "sess_new", "203.0.113.12")
    assert new != old and (await dv.state_of(db, new)).seconds_left == 1800


class RecordingStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


async def test_expired_visits_are_removed_but_the_samples_and_todays_spend_stay(db) -> None:  # noqa: ANN001
    from app.demo import account

    base = await base_account(db)
    gone = await dv.account_for_session(db, base, "sess_gone", "203.0.113.20")
    kept = await dv.account_for_session(db, base, "sess_kept", "203.0.113.21")
    await db.execute(
        """
        INSERT INTO datasets (id, owner_id, origin, title, filename, sheet, s3_key_original,
                              s3_key, status, columns, row_count, size_bytes, sha256)
        VALUES (gen_random_uuid(), $1, 'csv_upload', 'mine', 'mine.csv', '', 'u/orig.csv',
                'u/data.parquet', 'READY', '[]'::jsonb, 5, 50, 'own')
        """,
        gone,
    )
    await spend(db, kept, 0.01)  # spent today: stays until tomorrow (daily total)
    await db.execute(
        "UPDATE demo_visits SET window_start = now() - interval '25 hours' "
        "WHERE user_id = ANY($1::uuid[])",
        [gone, kept],
    )
    store = RecordingStore()
    assert await account.cleanup_expired_visits(db, store) == 1
    assert await db.fetchval("SELECT count(*) FROM users WHERE id = $1", gone) == 0
    assert await db.fetchval("SELECT count(*) FROM users WHERE id = $1", kept) == 1
    assert sorted(store.deleted) == ["u/data.parquet", "u/orig.csv"]  # the upload only
    assert await db.fetchval("SELECT count(*) FROM datasets WHERE s3_key = 'k/data.parquet'") >= 2


async def test_ipv4_seen_through_ipv6_is_the_same_visitor(db) -> None:  # noqa: ANN001
    """Regression: the web server saw ::ffff:127.0.0.1 / ::1 while the API saw 127.0.0.1, so
    the sign-in gate and the visits used different keys."""
    keys = await db.fetchrow(
        "SELECT demo_ip_key('::ffff:203.0.113.7') AS mapped, demo_ip_key('::1') AS loop6"
    )
    assert keys["mapped"] == "203.0.113.7" and keys["loop6"] == "127.0.0.1"
    base = await base_account(db)
    a = await dv.account_for_session(db, base, "sess_v4", "203.0.113.7")
    b = await dv.account_for_session(db, base, "sess_mapped", "::ffff:203.0.113.7")
    assert a == b


async def test_an_admin_reset_gives_a_used_up_visit_its_allowance_back(db) -> None:  # noqa: ANN001
    base = await base_account(db)
    visitor = await dv.account_for_session(db, base, "sess_r", "203.0.113.20")
    # the visit started an hour ago, used its 30 minutes and its budget
    await db.execute(
        "UPDATE demo_visits SET window_start = now() - interval '1 hour', seconds_used = 1800"
        " WHERE user_id = $1",
        visitor,
    )
    await spend(db, visitor, 1.0)
    await db.execute(
        "UPDATE runs SET created_at = now() - interval '30 minutes' WHERE user_id = $1", visitor
    )
    await db.execute(
        "INSERT INTO usage_ledger (user_id, model_id, cost_usd) VALUES ($1, 'm', 1.0)", visitor
    )
    assert (await dv.state_of(db, visitor)).exhausted == "time"
    visit_id = await db.fetchval("SELECT id FROM demo_visits WHERE user_id = $1", visitor)

    assert await dv.reset_visit(db, str(visit_id)) is True
    state = await dv.state_of(db, visitor)
    assert state.exhausted is None and state.seconds_left == 1800 and state.budget_left_usd == 1.0
    assert (await db.fetchval("SELECT demo_gate('203.0.113.20')"))["allowed"] is True
    cap = await db.fetchval("SELECT usage_limit_usd FROM users WHERE id = $1", visitor)
    assert float(cap) == 2.0  # lifetime spend so far + one visit budget
    assert await db.fetchval("SELECT count(*) FROM chats WHERE user_id = $1", visitor) == 1
    assert await dv.reset_visit(db, str(uuid.uuid4())) is False
