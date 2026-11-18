"""Remove accounts on the live site the way the admin console's Delete does: audit entry first,
then the Clerk sign-in is deleted and the EagleEye row is marked deleted (history kept).

    uv run --package eagleeye-api python media/tools/remove_accounts.py <email LIKE pattern> ...

Each pattern must match exactly one active account, or nothing is removed for it. Emails are
printed masked. Reads DATABASE_URL and CLERK_SECRET_KEY from .env.cloud; prints neither.
"""

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "api"))


def cloud_setting(name: str) -> str:
    for line in (REPO / ".env.cloud").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].split(" #", 1)[0].strip().strip('"')
    sys.exit(f"{name} is not set in .env.cloud")


def mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:3]}…@{domain}"


async def main(patterns: list[str]) -> None:
    import asyncpg
    from app.repos import admin_metrics
    from app.repos import users as users_repo
    from app.services.clerk_admin import ClerkAdmin

    async def _init(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    clerk = ClerkAdmin(cloud_setting("CLERK_SECRET_KEY"))
    pool = await asyncpg.create_pool(
        cloud_setting("DATABASE_URL"), min_size=1, max_size=2, statement_cache_size=0, init=_init
    )
    try:
        admin_id = await pool.fetchval(
            "SELECT id FROM users WHERE role = 'admin' AND status = 'active' "
            "ORDER BY created_at LIMIT 1"
        )
        for pattern in patterns:
            rows = await pool.fetch(
                "SELECT id, email, clerk_user_id, role FROM users "
                "WHERE email LIKE $1 AND status != 'deleted'",
                pattern,
            )
            if len(rows) != 1:
                print(f"{pattern}: {len(rows)} matches, skipped")
                continue
            target = rows[0]
            if str(target["id"]) == str(admin_id):
                print(f"{mask(target['email'])}: is the main admin, skipped")
                continue
            await admin_metrics.record_admin_action(
                pool,
                str(admin_id),
                "user_deleted",
                {"email": target["email"], "via": "video setup"},
            )
            await clerk.delete_user(target["clerk_user_id"])
            await users_repo.mark_deleted(pool, str(target["id"]))
            print(f"{mask(target['email'])} ({target['role']}): removed")
    finally:
        await pool.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1:]))
