"""Catalog persistence in the metadata DB (Supabase). Parameterised SQL only."""

import json
from collections.abc import Sequence
from typing import Any

import asyncpg

from eagleeye_catalog.models import ColumnInfo, Example, Grant, Metric, SourceInfo, TableInfo


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _samples(raw: Any) -> tuple[str, ...]:
    """jsonb arrives as a list with a JSON codec on the pool, or as text without one."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return ()
    return tuple(str(v) for v in raw) if isinstance(raw, list) else ()


def _source(row: asyncpg.Record) -> SourceInfo:
    return SourceInfo(
        id=str(row["id"]),
        name=row["name"],
        description=row["description"],
        engine=row["engine"],
        dsn_env=row["dsn_env"],
        max_rows=row["max_rows"],
        timeout_s=row["timeout_s"],
        schema_version=row["schema_version"],
    )


class CatalogRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # --- reads ---------------------------------------------------------------------------

    async def get_source(self, source_id: str) -> SourceInfo | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM data_sources WHERE id = $1 AND status = 'active'", source_id
        )
        return _source(row) if row else None

    async def get_source_by_name(self, name: str) -> SourceInfo | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM data_sources WHERE name = $1 AND status = 'active'", name
        )
        return _source(row) if row else None

    async def sources_for_role(self, role: str) -> list[tuple[SourceInfo, Grant]]:
        rows = await self._pool.fetch(
            """
            SELECT s.*, g.allowed_tables, g.can_see_pii, g.role
            FROM data_sources s JOIN source_grants g ON g.data_source_id = s.id
            WHERE s.status = 'active' AND g.role = $1 ORDER BY s.name
            """,
            role,
        )
        return [
            (
                _source(r),
                Grant(
                    r["role"],
                    tuple(r["allowed_tables"]) if r["allowed_tables"] is not None else None,
                    r["can_see_pii"],
                ),
            )
            for r in rows
        ]

    async def get_grant(self, source_id: str, role: str) -> Grant | None:
        row = await self._pool.fetchrow(
            "SELECT role, allowed_tables, can_see_pii FROM source_grants "
            "WHERE data_source_id = $1 AND role = $2",
            source_id,
            role,
        )
        if row is None:
            return None
        allowed = tuple(row["allowed_tables"]) if row["allowed_tables"] is not None else None
        return Grant(row["role"], allowed, row["can_see_pii"])

    async def load_tables(self, source_id: str) -> list[TableInfo]:
        tables = await self._pool.fetch(
            "SELECT * FROM catalog_tables WHERE data_source_id = $1 "
            "ORDER BY schema_name, table_name",
            source_id,
        )
        columns = await self._pool.fetch(
            """
            SELECT c.* FROM catalog_columns c JOIN catalog_tables t ON t.id = c.table_id
            WHERE t.data_source_id = $1 ORDER BY c.table_id, c.ordinal
            """,
            source_id,
        )
        by_table: dict[str, list[ColumnInfo]] = {}
        for c in columns:
            by_table.setdefault(str(c["table_id"]), []).append(
                ColumnInfo(
                    name=c["name"],
                    data_type=c["data_type"],
                    description=c["description"],
                    is_pk=c["is_pk"],
                    fk_ref=c["fk_ref"],
                    pii=c["pii"],
                    sample_values=_samples(c["sample_values"]),
                )
            )
        return [
            TableInfo(
                schema=t["schema_name"],
                name=t["table_name"],
                columns=tuple(by_table.get(str(t["id"]), [])),
                description=t["description"],
                row_estimate=t["row_estimate"],
                sensitivity=t["sensitivity"],
                enabled=t["enabled"],
            )
            for t in tables
        ]

    async def table_scores(self, source_id: str, vector: Sequence[float]) -> dict[str, float]:
        rows = await self._pool.fetch(
            """
            SELECT schema_name || '.' || table_name AS key, 1 - (embedding <=> $2::vector) AS score
            FROM catalog_tables WHERE data_source_id = $1 AND embedding IS NOT NULL
            """,
            source_id,
            vector_literal(vector),
        )
        return {r["key"]: float(r["score"]) for r in rows}

    async def top_metrics(self, source_id: str, vector: Sequence[float], k: int) -> list[Metric]:
        rows = await self._pool.fetch(
            """
            SELECT name, description, definition_sql FROM catalog_metrics
            WHERE data_source_id = $1 ORDER BY embedding <=> $2::vector LIMIT $3
            """,
            source_id,
            vector_literal(vector),
            k,
        )
        return [Metric(r["name"], r["description"], r["definition_sql"]) for r in rows]

    async def top_examples(self, source_id: str, vector: Sequence[float], k: int) -> list[Example]:
        rows = await self._pool.fetch(
            """
            SELECT question, sql FROM catalog_examples
            WHERE data_source_id = $1 ORDER BY embedding <=> $2::vector LIMIT $3
            """,
            source_id,
            vector_literal(vector),
            k,
        )
        return [Example(r["question"], r["sql"]) for r in rows]

    # --- writes (onboarding) ----------------------------------------------------------------

    async def upsert_source(self, spec: dict[str, Any]) -> str:
        return str(
            await self._pool.fetchval(
                """
            INSERT INTO data_sources (name, description, engine, dsn_env, max_rows, timeout_s)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description,
                engine = EXCLUDED.engine, dsn_env = EXCLUDED.dsn_env,
                max_rows = EXCLUDED.max_rows, timeout_s = EXCLUDED.timeout_s, updated_at = now()
            RETURNING id
            """,
                spec["name"],
                spec.get("description", ""),
                spec["engine"],
                spec["dsn_env"],
                int(spec.get("max_rows", 10_000)),
                int(spec.get("timeout_s", 15)),
            )
        )

    async def replace_catalog(
        self,
        source_id: str,
        tables: Sequence[TableInfo],
        table_vectors: dict[str, Sequence[float]],
        metrics: Sequence[tuple[Metric, Sequence[float]]],
        examples: Sequence[tuple[Example, Sequence[float]]],
        grants: Sequence[Grant],
    ) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM catalog_tables WHERE data_source_id = $1", source_id)
            for t in tables:
                await self._insert_table(conn, source_id, t, table_vectors.get(t.key))
            await conn.execute("DELETE FROM catalog_metrics WHERE data_source_id = $1", source_id)
            for m, v in metrics:
                await conn.execute(
                    "INSERT INTO catalog_metrics "
                    "(data_source_id, name, definition_sql, description, "
                    "embedding) VALUES ($1, $2, $3, $4, $5::vector)",
                    source_id,
                    m.name,
                    m.definition_sql,
                    m.description,
                    vector_literal(v),
                )
            await conn.execute("DELETE FROM catalog_examples WHERE data_source_id = $1", source_id)
            for e, v in examples:
                await conn.execute(
                    "INSERT INTO catalog_examples (data_source_id, question, sql, embedding) "
                    "VALUES ($1, $2, $3, $4::vector)",
                    source_id,
                    e.question,
                    e.sql,
                    vector_literal(v),
                )
            await conn.execute("DELETE FROM source_grants WHERE data_source_id = $1", source_id)
            for g in grants:
                await conn.execute(
                    "INSERT INTO source_grants (data_source_id, role, allowed_tables, can_see_pii) "
                    "VALUES ($1, $2, $3, $4)",
                    source_id,
                    g.role,
                    list(g.allowed_tables) if g.allowed_tables else None,
                    g.can_see_pii,
                )
            await conn.execute(
                "UPDATE data_sources SET schema_version = schema_version + 1, updated_at = now() "
                "WHERE id = $1",
                source_id,
            )

    async def _insert_table(
        self, conn: asyncpg.Connection, source_id: str, t: TableInfo, vector: Sequence[float] | None
    ) -> None:
        table_id = await conn.fetchval(
            """
            INSERT INTO catalog_tables (data_source_id, schema_name, table_name, description,
                row_estimate, sensitivity, enabled, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector) RETURNING id
            """,
            source_id,
            t.schema,
            t.name,
            t.description,
            t.row_estimate,
            t.sensitivity,
            t.enabled,
            vector_literal(vector) if vector is not None else None,
        )
        await conn.executemany(
            """
            INSERT INTO catalog_columns (table_id, name, data_type, description, sample_values,
                is_pk, fk_ref, pii, ordinal)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
            """,
            [
                (
                    table_id,
                    c.name,
                    c.data_type,
                    c.description,
                    json.dumps(list(c.sample_values)),
                    c.is_pk,
                    c.fk_ref,
                    c.pii,
                    i,
                )
                for i, c in enumerate(t.columns)
            ],
        )
