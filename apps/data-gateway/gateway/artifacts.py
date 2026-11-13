"""Query results → Parquet in the object store + `artifacts` row (C5 §5)."""

import io

import asyncpg
import pyarrow as pa
import pyarrow.parquet as pq
from eagleeye_core.storage import ObjectStore
from eagleeye_datasets.artifacts import save_table_artifact

from gateway.executor import QueryResult, jsonable


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
    return await save_table_artifact(
        store,
        pool,
        user_id=user_id,
        run_id=run_id,
        title=title or "Query result",
        parquet=to_parquet(result),
        columns=[{"name": n, "type": t} for n, t in result.columns],
        row_count=len(result.rows),
        truncated=result.truncated,
        source_refs={"sql": sql, "source_id": source_id},
    )
