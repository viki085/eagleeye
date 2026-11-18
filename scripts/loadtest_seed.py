"""Prepare a load test (Phase 7C, ADR-34). Only against an APP_ENV=loadtest environment.

    1. keys     make the signing key pair for synthetic sign-in
                -> set LOADTEST_TOKEN_PUBLIC_KEY on the API to the contents of public.pem
    2. users    create N synthetic users in the load-test database and sign one token each
                (tokens.json, read by the k6 script; valid for --hours, at most 6)
       tokens   sign fresh tokens for existing users without touching the database (the
                users are baked into the load-test database image; sign just before the run)
    3. uploads  through the running API: a few enterprise documents (as the synthetic
                knowledge admin) and one small CSV for every user who runs analyses

    4. remove-users  after the test: delete every synthetic account

Run from the repo root with the load-test settings, e.g.
    APP_ENV=loadtest DATABASE_URL=... uv run python scripts/loadtest_seed.py \
        users --count 2000 --confirm-db-host <the load-test database host>

The private key and tokens.json give access to the load-test environment: keep them out of the
repo (the default folder, .loadtest/, is git-ignored) and delete them after the test.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ISSUER = "eagleeye-loadtest"
SUBJECT_PREFIX = "loadtest:"
ADMIN_SUBJECT = f"{SUBJECT_PREFIX}admin"
ADMIN_ROLE = "knowledge_admin"  # may add enterprise documents, nothing more
MAX_HOURS = 6.0
ANALYSIS_EVERY = 20  # user n runs analyses when n % 20 == 0 (5% of users)
DEFAULT_DIR = Path(".loadtest")
REPO = Path(__file__).resolve().parents[1]
POOL_FILE = REPO / "packages" / "llm" / "eagleeye_llm" / "loadtest_questions.json"
CORPUS = REPO / "data" / "grandline" / "out"  # the Grand Line documents the pool asks about
VOYAGE_DATA = REPO / "Trial" / "data" / "data-files" / "vessel_fuel_and_emissions.csv"


def _refuse_unless_loadtest() -> None:
    from eagleeye_core.config import LOADTEST_ENV, get_settings

    env = get_settings().app_env
    if env != LOADTEST_ENV:
        sys.exit(f"refusing: APP_ENV is {env!r}; this script only runs with APP_ENV={LOADTEST_ENV}")


def db_host(database_url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(database_url).hostname or ""


def _refuse_unless_confirmed(database_url: str, confirmed_host: str) -> None:
    """APP_ENV alone is not enough to write users: the operator names the database host, so a
    production DATABASE_URL left in the shell can't be seeded with synthetic accounts."""
    host = db_host(database_url)
    if not host or confirmed_host != host:
        sys.exit(
            f"refusing: DATABASE_URL points at {host!r}; pass --confirm-db-host {host} if (and "
            "only if) that is the separate load-test database"
        )


def _write_private(path: Path, data: bytes) -> None:
    """Owner-only file (0600): the signing key and the tokens let anyone sign in."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)  # an existing file keeps its old mode through os.open


def subject(n: int) -> str:
    return f"{SUBJECT_PREFIX}{n}"


def runs_analyses(n: int) -> bool:
    return n % ANALYSIS_EVERY == 0


def make_keys(out: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),  # a throwaway key for one test; files are 0600
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    _write_private(out / "private.pem", private)
    (out / "public.pem").write_bytes(public)
    print(f"wrote {out / 'public.pem'} (set LOADTEST_TOKEN_PUBLIC_KEY to its contents)")


def sign(private_pem: bytes, sub: str, hours: float, now: float | None = None) -> str:
    import jwt

    issued = int(now if now is not None else time.time())
    claims = {"iss": ISSUER, "sub": sub, "iat": issued, "exp": issued + int(hours * 3600)}
    return jwt.encode(claims, private_pem, algorithm="RS256")


async def create_users(database_url: str, count: int) -> None:
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        rows = [(ADMIN_SUBJECT, "loadtest-admin@loadtest.invalid", "Load test admin", ADMIN_ROLE)]
        rows += [
            (subject(n), f"loadtest{n}@loadtest.invalid", f"Load test user {n}", "member")
            for n in range(1, count + 1)
        ]
        await conn.executemany(
            """
            INSERT INTO users (clerk_user_id, email, display_name, role)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (clerk_user_id) DO UPDATE SET status = 'active'
            """,
            rows,
        )
    finally:
        await conn.close()
    print(f"{count} users ready (+ the knowledge admin)")


async def video_accounts(database_url: str, admin_clerk_id: str, member_clerk_id: str) -> None:
    """The two real sign-in accounts used for the screen recordings (the window wall and the
    admin console), mapped into the load-test database: one admin, one member."""
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        await conn.executemany(
            """
            INSERT INTO users (clerk_user_id, email, display_name, role)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (clerk_user_id) DO UPDATE SET role = EXCLUDED.role, status = 'active'
            """,
            [
                (admin_clerk_id, "vikram.k@grandlineshipping.com", "Vikram K", "admin"),
                (member_clerk_id, "sam.rivera@grandlineshipping.com", "Sam Rivera", "member"),
            ],
        )
    finally:
        await conn.close()
    print("video accounts ready (admin + member)")


async def remove_users(database_url: str) -> None:
    """Teardown: delete every synthetic account (and, by cascade, its chats and files)."""
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        result = await conn.execute(
            "DELETE FROM users WHERE clerk_user_id LIKE $1", f"{SUBJECT_PREFIX}%"
        )
    finally:
        await conn.close()
    print(f"removed synthetic users: {result}")


def write_tokens(keys: Path, count: int, hours: float) -> None:
    if not 0 < hours <= MAX_HOURS:
        sys.exit(f"--hours must be between 0 and {MAX_HOURS}")
    private = (keys / "private.pem").read_bytes()
    users = [
        {"n": n, "token": sign(private, subject(n), hours), "analysis": runs_analyses(n)}
        for n in range(1, count + 1)
    ]
    admin = sign(private, ADMIN_SUBJECT, hours)
    _write_private(keys / "tokens.json", json.dumps({"admin": admin, "users": users}).encode())
    print(f"wrote {keys / 'tokens.json'} ({count} tokens, valid {hours} h)")


def corpus_files() -> list[Path]:
    """The documents the question pool asks about: Markdown where it exists, else the PDF/Word file."""
    slugs = json.loads(POOL_FILE.read_text(encoding="utf-8"))["documents"]
    found = []
    for slug in slugs:
        md = CORPUS / "md" / f"{slug}.md"
        matches = [md] if md.exists() else sorted((CORPUS / "docs").rglob(f"{slug}.*"))
        if not matches:
            sys.exit(f"document for {slug!r} not found under {CORPUS}")
        found.append(matches[0])
    return found


MIME = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def upload(api_url: str, keys: Path) -> None:
    import httpx

    tokens = json.loads((keys / "tokens.json").read_text())
    with httpx.Client(base_url=api_url.rstrip("/"), timeout=120) as http:
        admin = {"Authorization": f"Bearer {tokens['admin']}"}
        files = corpus_files()
        for path in files:
            resp = http.post(
                "/v1/documents",
                headers=admin,
                data={"scope": "enterprise"},
                files={
                    "file": (
                        path.name,
                        path.read_bytes(),
                        MIME.get(path.suffix, "application/octet-stream"),
                    )
                },
            )
            if resp.status_code not in (200, 201, 202, 409):  # 409 = already uploaded
                print(f"document {path.name}: {resp.status_code} {resp.text[:200]}")
        print(f"{len(files)} enterprise documents submitted for indexing")
        analysts = [u for u in tokens["users"] if u["analysis"]]
        voyage = VOYAGE_DATA.read_bytes()
        for u in analysts:
            resp = http.post(
                "/v1/datasets",
                headers={"Authorization": f"Bearer {u['token']}"},
                files={"file": ("vessel_fuel_and_emissions.csv", voyage, "text/csv")},
            )
            if resp.status_code not in (201, 409):
                print(f"user {u['n']} data file: {resp.status_code} {resp.text[:200]}")
        print(f"data files uploaded for {len(analysts)} users")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="key and token folder")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keys")
    users = sub.add_parser("users")
    users.add_argument("--count", type=int, default=500)
    users.add_argument("--hours", type=float, default=4.0)
    tokens = sub.add_parser("tokens")
    tokens.add_argument("--count", type=int, default=2000)
    tokens.add_argument("--hours", type=float, default=4.0)
    remove = sub.add_parser("remove-users")
    video = sub.add_parser("video-accounts")
    video.add_argument("--admin-clerk-id", required=True)
    video.add_argument("--member-clerk-id", required=True)
    for p in (users, remove, video):
        p.add_argument("--confirm-db-host", required=True, help="the load-test database host")
    uploads = sub.add_parser("uploads")
    uploads.add_argument("--api-url", required=True)
    args = parser.parse_args()

    _refuse_unless_loadtest()
    from eagleeye_core.config import get_settings

    database_url = get_settings().database_url
    if args.cmd == "keys":
        make_keys(args.dir)
    elif args.cmd == "tokens":
        write_tokens(args.dir, args.count, args.hours)
    elif args.cmd == "users":
        _refuse_unless_confirmed(database_url, args.confirm_db_host)
        asyncio.run(create_users(database_url, args.count))
        write_tokens(args.dir, args.count, args.hours)
    elif args.cmd == "video-accounts":
        _refuse_unless_confirmed(database_url, args.confirm_db_host)
        asyncio.run(video_accounts(database_url, args.admin_clerk_id, args.member_clerk_id))
    elif args.cmd == "remove-users":
        _refuse_unless_confirmed(database_url, args.confirm_db_host)
        asyncio.run(remove_users(database_url))
    else:
        upload(args.api_url, args.dir)


if __name__ == "__main__":
    main()
