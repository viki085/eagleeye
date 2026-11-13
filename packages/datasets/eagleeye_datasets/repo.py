"""Dataset persistence (parameterised SQL only). Every read is scoped to the owner.

Connections must have the jsonb codec registered (as every EagleEye pool does), so jsonb
columns take and return plain Python objects.
"""

import hashlib
import json
from typing import Any

import asyncpg

from eagleeye_datasets.models import Dataset

MAX_ERROR_CHARS = 500
MAX_CODE_CHARS = 20_000
_COLUMNS = """
    id, owner_id, origin, title, filename, sheet, s3_key_original, s3_key, status, error,
    columns, column_map, row_count, size_bytes, sha256, profile, summary, created_at
"""
Db = asyncpg.Pool | asyncpg.Connection


def _obj(raw: Any, default: Any) -> Any:
    """Tolerates a connection without the jsonb codec (text comes back as str)."""
    if raw is None:
        return default
    return json.loads(raw) if isinstance(raw, str) else raw


def to_dataset(row: asyncpg.Record) -> Dataset:
    return Dataset(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]),
        origin=row["origin"],
        title=row["title"],
        filename=row["filename"],
        sheet=row["sheet"],
        s3_key_original=row["s3_key_original"],
        s3_key=row["s3_key"],
        status=row["status"],
        error=row["error"],
        columns=tuple(_obj(row["columns"], [])),
        column_map=_obj(row["column_map"], {}),
        row_count=row["row_count"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        profile=_obj(row["profile"], {}),
        summary=row["summary"],
        created_at=row["created_at"],
    )


class DatasetRepo:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def create(
        self,
        *,
        dataset_id: str,
        owner_id: str,
        origin: str,
        title: str,
        filename: str,
        sheet: str,
        s3_key_original: str,
        size_bytes: int,
        sha256: str,
    ) -> bool:
        """False when this owner already has the same file/sheet (unique constraint)."""
        status = await self._db.execute(
            """
            INSERT INTO datasets (id, owner_id, origin, title, filename, sheet,
                                  s3_key_original, size_bytes, sha256)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (owner_id, sha256, sheet) DO NOTHING
            """,
            dataset_id,
            owner_id,
            origin,
            title,
            filename,
            sheet,
            s3_key_original,
            size_bytes,
            sha256,
        )
        return status.endswith(" 1")

    async def get(self, dataset_id: str, owner_id: str) -> Dataset | None:
        row = await self._db.fetchrow(
            f"SELECT {_COLUMNS} FROM datasets WHERE id = $1 AND owner_id = $2",  # noqa: S608
            dataset_id,
            owner_id,
        )
        return to_dataset(row) if row else None

    async def get_for_worker(self, dataset_id: str) -> Dataset | None:
        """Unscoped: only the ingest worker, which acts on a job the API created."""
        row = await self._db.fetchrow(
            f"SELECT {_COLUMNS} FROM datasets WHERE id = $1",  # noqa: S608
            dataset_id,
        )
        return to_dataset(row) if row else None

    async def list_for(self, owner_id: str, ready_only: bool = False) -> list[Dataset]:
        rows = await self._db.fetch(
            f"SELECT {_COLUMNS} FROM datasets WHERE owner_id = $1 "  # noqa: S608
            "AND ($2 = false OR status = 'READY') ORDER BY created_at DESC LIMIT 200",
            owner_id,
            ready_only,
        )
        return [to_dataset(r) for r in rows]

    async def set_status(self, dataset_id: str, status: str, error: str | None = None) -> None:
        await self._db.execute(
            "UPDATE datasets SET status = $2, error = $3, updated_at = now() WHERE id = $1",
            dataset_id,
            status,
            error[:MAX_ERROR_CHARS] if error else None,
        )

    async def mark_ready(
        self,
        dataset_id: str,
        *,
        title: str,
        sheet: str,
        s3_key: str,
        columns: list[dict[str, str]],
        column_map: dict[str, str],
        row_count: int,
        profile: dict[str, Any],
        summary: str,
    ) -> None:
        await self._db.execute(
            """
            UPDATE datasets
               SET status = 'READY', error = NULL, title = $2, sheet = $3, s3_key = $4,
                   columns = $5, column_map = $6, row_count = $7, profile = $8, summary = $9,
                   updated_at = now()
             WHERE id = $1
            """,
            dataset_id,
            title,
            sheet,
            s3_key,
            columns,
            column_map,
            row_count,
            profile,
            summary,
        )

    async def delete(self, dataset_id: str, owner_id: str) -> bool:
        status = await self._db.execute(
            "DELETE FROM datasets WHERE id = $1 AND owner_id = $2", dataset_id, owner_id
        )
        return status.endswith(" 1")

    async def table_artifact(self, artifact_id: str, user_id: str) -> asyncpg.Record | None:
        """A table artifact the user owns (query or analysis result), usable as an input."""
        return await self._db.fetchrow(
            """
            SELECT id, title, s3_key, columns, row_count FROM artifacts
             WHERE id = $1 AND user_id = $2 AND type = 'table'
            """,
            artifact_id,
            user_id,
        )

    async def log_sandbox_run(
        self,
        *,
        run_id: str | None,
        user_id: str,
        mode: str,
        code: str,
        status: str,
        duration_ms: int,
        error: str | None,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO sandbox_runs (run_id, user_id, mode, code_hash, code_text, status,
                                      duration_ms, error)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            run_id,
            user_id,
            mode,
            hashlib.sha256(code.encode()).hexdigest(),
            code[:MAX_CODE_CHARS],
            status,
            duration_ms,
            error[:MAX_ERROR_CHARS] if error else None,
        )

    async def sandbox_runs_last_hour(self, user_id: str) -> int:
        return await self._db.fetchval(
            "SELECT COUNT(*) FROM sandbox_runs "
            "WHERE user_id = $1 AND created_at > now() - interval '1 hour'",
            user_id,
        )
