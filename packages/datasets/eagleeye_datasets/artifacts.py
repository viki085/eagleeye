"""Table artifacts: Parquet in the object store + an `artifacts` row.

Shared by the data gateway (SQL results) and the analysis agent (sandbox results), so both
kinds of result are stored, paged and exported the same way.
"""

import uuid
from typing import Any

import asyncpg
from eagleeye_core.storage import ObjectStore

from eagleeye_datasets.models import PARQUET_MIME

MAX_TITLE_CHARS = 200


def artifact_key(user_id: str, artifact_id: str) -> str:
    return f"artifacts/{user_id}/{artifact_id}.parquet"


async def save_table_artifact(
    store: ObjectStore,
    pool: asyncpg.Pool,
    *,
    user_id: str,
    run_id: str | None,
    title: str,
    parquet: bytes,
    columns: list[dict[str, str]],
    row_count: int,
    truncated: bool,
    source_refs: dict[str, Any],
) -> str:
    artifact_id = str(uuid.uuid4())
    key = artifact_key(user_id, artifact_id)
    await store.put(key, parquet, PARQUET_MIME)
    await pool.execute(
        """
        INSERT INTO artifacts (id, run_id, user_id, type, title, s3_key, columns, row_count,
                               truncated, source_refs)
        VALUES ($1, $2, $3, 'table', $4, $5, $6, $7, $8, $9)
        """,
        artifact_id,
        run_id,
        user_id,
        title[:MAX_TITLE_CHARS] or "Result",
        key,
        # plain objects: the pool's jsonb codec encodes them (json.dumps here double-encodes)
        columns,
        row_count,
        truncated,
        source_refs,
    )
    return artifact_id
