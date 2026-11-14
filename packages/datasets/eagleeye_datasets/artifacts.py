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


JSON_MIME = "application/json"
PNG_MIME = "image/png"


def notebook_prefix(user_id: str, notebook_id: str) -> str:
    return f"artifacts/{user_id}/notebooks/{notebook_id}"


def notebook_figure_key(user_id: str, notebook_id: str, figure: str) -> str:
    return f"{notebook_prefix(user_id, notebook_id)}/{figure}.png"


async def save_notebook_artifact(
    store: ObjectStore,
    pool: asyncpg.Pool,
    *,
    notebook_id: str,
    user_id: str,
    run_id: str | None,
    title: str,
    manifest: dict[str, Any],
    figures: list[tuple[str, bytes]],
) -> str:
    """Figures first, then the manifest, then the row: a row always points at complete data."""
    import json

    for name, png in figures:
        await store.put(notebook_figure_key(user_id, notebook_id, name), png, PNG_MIME)
    key = f"{notebook_prefix(user_id, notebook_id)}/notebook.json"
    await store.put(key, json.dumps(manifest).encode("utf-8"), JSON_MIME)
    await pool.execute(
        """
        INSERT INTO artifacts (id, run_id, user_id, type, title, s3_key, source_refs)
        VALUES ($1, $2, $3, 'notebook', $4, $5, $6)
        """,
        notebook_id,
        run_id,
        user_id,
        title[:MAX_TITLE_CHARS] or "Notebook",
        key,
        {"figures": [name for name, _ in figures]},
    )
    return notebook_id
