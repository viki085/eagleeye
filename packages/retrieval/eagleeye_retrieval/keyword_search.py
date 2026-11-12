"""Keyword (tsvector) search over both scopes in Postgres.

The query is OR-ed lexemes so natural-language questions still match; each
lexeme is quote_literal-ed so punctuation inside a lexeme can't break to_tsquery.
"""

import re

import asyncpg

from eagleeye_retrieval.access import access_args, access_predicate
from eagleeye_retrieval.types import AccessScope

KEYWORD_TOP_N = 20
_WORD = re.compile(r"\w")


async def keyword_search(
    pool: asyncpg.Pool, query: str, scope: AccessScope, limit: int = KEYWORD_TOP_N
) -> list[str]:
    if not _WORD.search(query):
        return []
    doc_param = 4 if scope.doc_ids else None
    rows = await pool.fetch(
        f"""
        WITH q AS (
            SELECT to_tsquery('simple', array_to_string(array(
                SELECT quote_literal(l)
                FROM unnest(tsvector_to_array(to_tsvector('english', $1))) AS l
            ), ' | ')) AS query
        )
        SELECT c.id, ts_rank_cd(c.tsv, q.query) AS rank
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        CROSS JOIN q
        WHERE c.tsv @@ q.query AND {access_predicate(3, doc_param)}
        ORDER BY rank DESC, c.id
        LIMIT $2
        """,  # noqa: S608 — predicate is built from constants, values are bound
        query,
        limit,
        *access_args(scope),
    )
    return [str(r["id"]) for r in rows]
