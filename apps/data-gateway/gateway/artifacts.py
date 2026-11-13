"""Query results → Parquet in the object store + `artifacts` row (C5 §5)."""

import io
import uuid

import asyncpg
import pyarrow as pa
import pyarrow.parquet as pq
from eagleeye_core.storage import ObjectStore

from gateway.executor import QueryResult, jsonable

PARQUET_MIME = "application/vnd.apache.parquet"


def to_parquet(result: QueryResult) -> bytes:
    names = [n for n, _ in result.columns]
    columns = {name: [row[i] for row in result.rows] for i, name in enumerate(names)}
    try:
        table = pa.table(columns)
    except (pa.ArrowInvalid, pa.ArrowTypeError):
        # mixed/unsupported types: fall back to JSON-safe values (always representable)
        table = pa.table({n: [jsonable(v) for v in vals] for n, vals in columns.items()})
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def artifact_key(user_id: str, artifact_id: str) -> str:
    return f"artifacts/{user_id}/{artifact_id}.parquet"


async def save_artifact(
    store: ObjectStore,
    pool: asyncpg.Pool,
    *,
    user_id: str,
    run_id: str | None,
    title: str,
    result: QueryResult,
    sql: str,
    source_id: str,
) -> str:
    artifact_id = str(uuid.uuid4())
    key = artifact_key(user_id, artifact_id)
    await store.put(key, to_parquet(result), PARQUET_MIME)
    await pool.execute(
        """
        INSERT INTO artifacts (id, run_id, user_id, type, title, s3_key, columns, row_count,
                               truncated, source_refs)
        VALUES ($1, $2, $3, 'table', $4, $5, $6, $7, $8, $9)
        """,
        artifact_id,
        run_id,
        user_id,
        title[:200] or "Query result",
        key,
        # plain objects: the pool's jsonb codec encodes them (json.dumps here double-encodes)
        [{"name": n, "type": t} for n, t in result.columns],
        len(result.rows),
        result.truncated,
        {"sql": sql, "source_id": source_id},
    )
    return artifact_id
