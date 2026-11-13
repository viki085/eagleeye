"""Admin aggregates against the real local Postgres, inside a rolled-back transaction."""

import json
import uuid

import asyncpg
import pytest
from app.repos import admin_metrics as m
from eagleeye_core.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def conn():  # noqa: ANN201
    try:
        c = await asyncpg.connect(get_settings().database_url, timeout=3)
    except Exception:
        pytest.skip("local Postgres not available")
    await c.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    tx = c.transaction()
    await tx.start()
    try:
        yield c
    finally:
        await tx.rollback()
        await c.close()


async def _seed(c: asyncpg.Connection) -> tuple[str, str]:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    for uid, email in ((a, "metrics-a@test.local"), (b, "metrics-b@test.local")):
        await c.execute(
            "INSERT INTO users (id, clerk_user_id, email, role) VALUES ($1, $2, $3, 'member')",
            uid,
            f"clerk_{uid}",
            email,
        )
    chat = await c.fetchval("INSERT INTO chats (user_id) VALUES ($1) RETURNING id", a)
    chat_b = await c.fetchval("INSERT INTO chats (user_id) VALUES ($1) RETURNING id", b)
    rows = [  # (user, chat, status, cost, secs, ttft, warnings)
        (a, chat, "SUCCEEDED", 0.10, 4, 1.0, ["unverified_numbers"]),
        (a, chat, "FAILED", 0.02, 2, None, []),
        (b, chat_b, "SUCCEEDED", 0.30, 8, 2.0, []),
    ]
    for uid, chat_id, status, cost, secs, ttft, warnings in rows:
        run = await c.fetchval(
            """
            INSERT INTO runs (chat_id, user_id, status, cost_usd, route, created_at,
                              finished_at, first_token_at, warnings, error_code)
            VALUES ($1, $2, $3, $4, 'sql', now() - interval '1 hour',
                    now() - interval '1 hour' + make_interval(secs => $5),
                    CASE WHEN $6::float IS NULL THEN NULL
                         ELSE now() - interval '1 hour' + make_interval(secs => $6) END,
                    $7, CASE WHEN $3 = 'FAILED' THEN 'RUN_ERROR' END)
            RETURNING id
            """,
            chat_id,
            uid,
            status,
            cost,
            secs,
            ttft,
            warnings,
        )
        await c.execute(
            "INSERT INTO usage_ledger (user_id, run_id, model_id, tokens_in, tokens_out, cost_usd)"
            " VALUES ($1, $2, 'gpt-test', 100, 10, $3)",
            uid,
            run,
            cost,
        )
    await c.execute(
        "INSERT INTO security_events (user_id, kind, category, detail) "
        "VALUES ($1, 'input_blocked', 'prompt_injection', '{}')",
        a,
    )
    return a, b


async def test_overview_matches_seeded_runs(conn: asyncpg.Connection) -> None:
    before = await m.overview(conn, m.WINDOWS["24h"])
    await _seed(conn)
    after = await m.overview(conn, m.WINDOWS["24h"])
    assert after["runs"] - before["runs"] == 3
    assert after["succeeded"] - before["succeeded"] == 2
    assert after["failed"] - before["failed"] == 1
    assert after["cost_usd"] - before["cost_usd"] == pytest.approx(0.42)
    assert len(after["series"]) in (24, 25)  # hourly buckets
    assert sum(s["runs"] for s in after["series"]) == after["runs"]


async def test_cost_survives_chat_deletion(conn: asyncpg.Connection) -> None:
    """Billing comes from usage_ledger: deleting a chat removes its answers, not its cost."""
    before = await m.overview(conn, m.WINDOWS["24h"])
    a, _b = await _seed(conn)
    await conn.execute("DELETE FROM chats WHERE user_id = $1", a)
    after = await m.overview(conn, m.WINDOWS["24h"])
    assert after["runs"] - before["runs"] == 1  # only user b's answer is left
    assert after["cost_usd"] - before["cost_usd"] == pytest.approx(0.42)
    assert sum(s["cost_usd"] for s in after["series"]) == pytest.approx(after["cost_usd"])
    page = await m.users(conn, m.WINDOWS["24h"], "cost", 0, 100, 500.0)
    mine = {u["email"]: u for u in page["items"]}
    assert mine["metrics-a@test.local"]["cost_usd"] == pytest.approx(0.12)
    assert mine["metrics-a@test.local"]["runs"] == 0


async def test_users_usage_and_safety(conn: asyncpg.Connection) -> None:
    a, b = await _seed(conn)
    page = await m.users(conn, m.WINDOWS["7d"], "cost", 0, 100, 500.0)
    mine = {u["email"]: u for u in page["items"] if u["email"].endswith("@test.local")}
    assert mine["metrics-b@test.local"]["cost_usd"] == pytest.approx(0.30)
    assert mine["metrics-a@test.local"]["runs"] == 2
    assert mine["metrics-a@test.local"]["limit_used_pct"] == pytest.approx(0.02 + 0.004, abs=0.01)

    usage = await m.usage(conn, m.WINDOWS["7d"])
    top = {u["email"]: u["cost_usd"] for u in usage["top_users"]}
    assert top["metrics-b@test.local"] == pytest.approx(0.30)

    safety = await m.safety(conn, m.WINDOWS["7d"])
    assert any(e["category"] == "prompt_injection" for e in safety["events"])
    assert safety["unverified_figures"]["unverified"] >= 1
    assert any(r["error_code"] == "RUN_ERROR" for r in safety["failed_runs"])


async def test_counts_and_content_queries_run(conn: asyncpg.Connection) -> None:
    counts = await m.run_counts(conn, 60, 300)
    assert set(counts) == {"active", "stuck"}
    content = await m.content(conn)
    assert set(content) == {"documents", "document_failures", "datasets", "dataset_failures"}
