"""SourceAdapter port + Postgres adapter: read structure from the live source DB.

Runs with the gateway's read-only account, so it only sees what that account may read.
Keys come from pg_catalog (information_schema hides constraints from non-owners).
"""

from collections import defaultdict
from typing import Protocol

import asyncpg

from eagleeye_catalog.models import ColumnInfo, TableInfo

MAX_SAMPLE_VALUES = 12

_COLUMNS = """
SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.ordinal_position
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
 AND t.table_type = 'BASE TABLE'
WHERE c.table_schema = ANY($1::text[])
ORDER BY 1, 2, 5
"""

_KEYS = """
SELECT n.nspname AS schema, cl.relname AS tbl, a.attname AS col,
       con.contype::text AS kind,  -- "char" type would decode as bytes in asyncpg
       fn.nspname AS f_schema, fcl.relname AS f_tbl, fa.attname AS f_col
FROM pg_constraint con
JOIN pg_class cl ON cl.oid = con.conrelid
JOIN pg_namespace n ON n.oid = cl.relnamespace
JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = k.attnum
LEFT JOIN pg_class fcl ON fcl.oid = con.confrelid
LEFT JOIN pg_namespace fn ON fn.oid = fcl.relnamespace
LEFT JOIN pg_attribute fa ON fa.attrelid = con.confrelid AND fa.attnum = con.confkey[k.ord]
WHERE con.contype IN ('p', 'f') AND n.nspname = ANY($1::text[])
"""

_ROWS = """
SELECT n.nspname AS schema, c.relname AS tbl, GREATEST(c.reltuples, 0)::bigint AS rows
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = ANY($1::text[])
"""


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SourceAdapter(Protocol):
    async def introspect(self, schemas: list[str]) -> list[TableInfo]: ...

    async def sample_values(self, schema: str, table: str, column: str) -> tuple[str, ...]: ...


class PostgresAdapter:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def introspect(self, schemas: list[str]) -> list[TableInfo]:
        cols = await self._conn.fetch(_COLUMNS, schemas)
        keys = await self._conn.fetch(_KEYS, schemas)
        rows = {(r["schema"], r["tbl"]): r["rows"] for r in await self._conn.fetch(_ROWS, schemas)}
        pks = {(k["schema"], k["tbl"], k["col"]) for k in keys if k["kind"] == "p"}
        fks = {
            (k["schema"], k["tbl"], k["col"]): f"{k['f_schema']}.{k['f_tbl']}.{k['f_col']}"
            for k in keys
            if k["kind"] == "f"
        }
        grouped: dict[tuple[str, str], list[ColumnInfo]] = defaultdict(list)
        for c in cols:
            ident = (c["table_schema"], c["table_name"], c["column_name"])
            grouped[(c["table_schema"], c["table_name"])].append(
                ColumnInfo(
                    name=c["column_name"],
                    data_type=c["data_type"],
                    is_pk=ident in pks,
                    fk_ref=fks.get(ident),
                )
            )
        return [
            TableInfo(schema=s, name=t, columns=tuple(cs), row_estimate=rows.get((s, t)))
            for (s, t), cs in grouped.items()
        ]

    async def sample_values(self, schema: str, table: str, column: str) -> tuple[str, ...]:
        """Distinct values for low-cardinality columns only (≤ MAX_SAMPLE_VALUES)."""
        sql = (
            f"SELECT DISTINCT {quote_ident(column)}::text AS v "  # noqa: S608 - quoted identifiers
            f"FROM {quote_ident(schema)}.{quote_ident(table)} "
            f"WHERE {quote_ident(column)} IS NOT NULL LIMIT {MAX_SAMPLE_VALUES + 1}"
        )
        values = [r["v"] for r in await self._conn.fetch(sql)]
        return tuple(sorted(values)) if len(values) <= MAX_SAMPLE_VALUES else ()
