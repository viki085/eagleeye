"""The shared public demo account: create it, seed its data files, and reset it.

A reset removes what visitors left behind (chats, uploaded documents, extra data files),
puts the seed files back and restores the public password, so every visitor starts from the
same clean account. Spend history (usage_ledger) is never touched, so a reset cannot raise
the demo's lifetime budget.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import asyncpg
from eagleeye_core.config import Settings
from eagleeye_datasets.models import original_key
from eagleeye_datasets.repo import DatasetRepo

logger = logging.getLogger(__name__)

DATA_EXTENSIONS = {".csv": ("csv_upload", "text/csv")}


class Store(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def delete(self, key: str) -> None: ...


class Queue(Protocol):
    async def enqueue_dataset(self, dataset_id: str) -> None: ...


@dataclass(frozen=True)
class SeedFile:
    path: Path
    sha256: str
    data: bytes


@dataclass(frozen=True)
class ResetReport:
    chats: int
    documents: int
    datasets_removed: int
    datasets_added: int


def seed_files(files_dir: Path) -> list[SeedFile]:
    """The CSV files to give the demo account, in name order."""
    if not files_dir.is_dir():
        raise FileNotFoundError(f"Demo files folder not found: {files_dir}")
    out = []
    for path in sorted(files_dir.iterdir()):
        if path.suffix.lower() in DATA_EXTENSIONS and path.is_file():
            data = path.read_bytes()
            out.append(SeedFile(path, hashlib.sha256(data).hexdigest(), data))
    return out


def _title(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()


async def upsert_demo_user(pool: asyncpg.Pool, clerk_user_id: str, settings: Settings) -> str:
    """The EagleEye account for the demo sign-in: a member, flagged as demo, with its cap."""
    row = await pool.fetchrow(
        """
        UPDATE users SET is_demo = true, usage_limit_usd = $2, role = 'member',
                         status = 'active', username = $3, updated_at = now()
         WHERE clerk_user_id = $1 RETURNING id
        """,
        clerk_user_id,
        settings.demo_usage_limit_usd,
        settings.demo_username,
    )
    if row is None:
        row = await pool.fetchrow(
            """
            INSERT INTO users (clerk_user_id, email, display_name, role, username,
                               is_demo, usage_limit_usd)
            VALUES ($1, $2, 'Demo visitor', 'member', $3, true, $4) RETURNING id
            """,
            clerk_user_id,
            settings.demo_email,
            settings.demo_username,
            settings.demo_usage_limit_usd,
        )
    return str(row["id"])


async def demo_user_id(pool: asyncpg.Pool) -> str | None:
    value = await pool.fetchval(
        "SELECT id FROM users WHERE is_demo AND status = 'active' ORDER BY created_at LIMIT 1"
    )
    return None if value is None else str(value)


async def add_missing_files(
    pool: asyncpg.Pool, store: Store, queue: Queue, user_id: str, files: list[SeedFile]
) -> int:
    """Uploads each seed file the account doesn't have (matched by content); returns the count."""
    repo = DatasetRepo(pool)
    have = {d.sha256 for d in await repo.list_for(user_id)}
    added = 0
    for f in files:
        if f.sha256 in have:
            continue
        origin, mime = DATA_EXTENSIONS[f.path.suffix.lower()]
        dataset_id = str(uuid.uuid4())
        key = original_key(user_id, dataset_id, f.path.suffix.lower())
        created = await repo.create(
            dataset_id=dataset_id,
            owner_id=user_id,
            origin=origin,
            title=_title(f.path.name),
            filename=f.path.name,
            sheet="",
            s3_key_original=key,
            size_bytes=len(f.data),
            sha256=f.sha256,
        )
        if not created:
            continue
        await store.put(key, f.data, mime)
        await queue.enqueue_dataset(dataset_id)
        added += 1
    return added


async def _delete_objects(store: Store, keys: list[str]) -> None:
    for key in keys:
        try:
            await store.delete(key)
        except Exception:
            logger.warning("demo reset: object %s not removed", key, exc_info=True)


async def clear_visitor_data(
    pool: asyncpg.Pool, store: Store, user_id: str, keep_sha256: set[str]
) -> tuple[int, int, int]:
    """Deletes the account's chats, personal documents and non-seed data files."""
    chats = await pool.execute("DELETE FROM chats WHERE user_id = $1", user_id)
    docs = await pool.fetch(
        "DELETE FROM documents WHERE uploaded_by = $1 AND scope = 'personal' RETURNING s3_key",
        user_id,
    )
    await _delete_objects(store, [r["s3_key"] for r in docs if r["s3_key"]])
    repo = DatasetRepo(pool)
    removed = 0
    for ds in await repo.list_for(user_id):
        if ds.sha256 in keep_sha256 and ds.status != "FAILED":
            continue
        await repo.delete(ds.id, user_id)
        await _delete_objects(store, [k for k in (ds.s3_key, ds.s3_key_original) if k])
        removed += 1
    return int(chats.split()[-1]), len(docs), removed


async def reset(
    pool: asyncpg.Pool, store: Store, queue: Queue, clerk: Any, settings: Settings
) -> ResetReport | None:
    """Back to the seeded state; None when there is no demo account."""
    user_id = await demo_user_id(pool)
    if user_id is None:
        return None
    files = seed_files(Path(settings.demo_files_dir))
    chats, docs, removed = await clear_visitor_data(pool, store, user_id, {f.sha256 for f in files})
    added = await add_missing_files(pool, store, queue, user_id, files)
    if settings.demo_password:
        clerk_id = await pool.fetchval("SELECT clerk_user_id FROM users WHERE id = $1", user_id)
        await clerk.set_password(clerk_id, settings.demo_password)
    report = ResetReport(chats, docs, removed, added)
    logger.info("demo account reset: %s", report)
    return report


async def setup(
    pool: asyncpg.Pool, store: Store, queue: Queue, clerk: Any, settings: Settings
) -> tuple[str, int]:
    """Creates (or repairs) the demo sign-in and account and seeds its files."""
    if not settings.demo_password:
        raise ValueError("Set DEMO_PASSWORD first (it is shown on the sign-in page).")
    files = seed_files(Path(settings.demo_files_dir))
    clerk_id = await clerk.ensure_password_user(
        settings.demo_username, settings.demo_email, settings.demo_password
    )
    await clerk.add_to_organization(clerk_id)
    user_id = await upsert_demo_user(pool, clerk_id, settings)
    added = await add_missing_files(pool, store, queue, user_id, files)
    return user_id, added
