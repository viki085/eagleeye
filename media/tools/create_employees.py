"""Create the fictional employees shown in the product video, on the live site.

Same steps as the admin console's "Add user" (Clerk account, organisation membership, EagleEye
row, audit entry), recorded as added by the first active admin. Each account then gets a
strong random password, so the video signs in with company email + password and no email is
ever sent to the made-up addresses. Passwords go to media/.secrets/employees.json (git-ignored).

    uv run --package eagleeye-api python media/tools/create_employees.py

Reads DATABASE_URL and CLERK_SECRET_KEY from .env.cloud (the live settings); prints neither.
Re-running is safe: an existing account keeps its row and just gets a new password.
"""

import asyncio
import json
import secrets
import string
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "api"))

EMPLOYEES = [
    {"email": "vikram.k@grandlineshipping.com", "first_name": "Vikram", "last_name": "K", "username": "vikram_k"},
    {"email": "sam.rivera@grandlineshipping.com", "first_name": "Sam", "last_name": "Rivera", "username": "sam_rivera"},
]
SECRETS = REPO / "media" / ".secrets" / "employees.json"


def cloud_setting(name: str) -> str:
    for line in (REPO / ".env.cloud").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].split(" #", 1)[0].strip().strip('"')  # drop inline comments
    sys.exit(f"{name} is not set in .env.cloud")


def new_password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(18))
    return f"Gl-{core}!"  # long and random; never shown on camera (password field dots)


async def main() -> None:
    import asyncpg

    from app.repos import admin_metrics
    from app.repos import users as users_repo
    from app.services.clerk_admin import ClerkAdmin

    clerk = ClerkAdmin(cloud_setting("CLERK_SECRET_KEY"))
    async def _init(conn: asyncpg.Connection) -> None:  # as the API's pool (app/db.py)
        await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

    pool = await asyncpg.create_pool(
        cloud_setting("DATABASE_URL"), min_size=1, max_size=2, statement_cache_size=0, init=_init
    )
    try:
        admin_id = await pool.fetchval(
            "SELECT id FROM users WHERE role = 'admin' AND status = 'active' ORDER BY created_at LIMIT 1"
        )
        if admin_id is None:
            sys.exit("no active admin found")
        saved = json.loads(SECRETS.read_text(encoding="utf-8")) if SECRETS.exists() else {}
        for e in EMPLOYEES:
            existing = await users_repo.find_by_email(pool, e["email"])
            if existing is not None and existing["status"] != "deleted":
                clerk_id = existing["clerk_user_id"]
                print(f"{e['email']}: already exists, setting a new password")
                audited = await pool.fetchval(
                    "SELECT count(*) FROM security_events WHERE kind = 'admin_action' AND category = 'user_added' AND detail->>'email' = $1",
                    e["email"],
                )
                if not audited:  # an earlier run created the account but stopped before the audit
                    await admin_metrics.record_admin_action(
                        pool, str(admin_id), "user_added", {"email": e["email"], "role": "member", "via": "video setup"}
                    )
            else:
                clerk_id, created, username = await clerk.create_user(
                    e["email"], e["first_name"], e["last_name"], username=e["username"]
                )
                await clerk.add_to_organization(clerk_id)
                await users_repo.provision(
                    pool,
                    clerk_user_id=clerk_id,
                    email=e["email"],
                    display_name=f"{e['first_name']} {e['last_name']}",
                    role="member",
                    created_by=str(admin_id),
                    username=username,
                    reactivate_id=str(existing["id"]) if existing is not None else None,
                )
                await admin_metrics.record_admin_action(
                    pool, str(admin_id), "user_added", {"email": e["email"], "role": "member", "via": "video setup"}
                )
                print(f"{e['email']}: created (member)")
            password = new_password()
            await clerk.set_password(clerk_id, password)
            saved[e["email"]] = {"username": e["username"], "password": password}
        SECRETS.parent.mkdir(parents=True, exist_ok=True)
        SECRETS.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        print(f"passwords saved to {SECRETS.relative_to(REPO)} (git-ignored)")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
