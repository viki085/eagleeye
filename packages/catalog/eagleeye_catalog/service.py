"""CatalogService: grant-aware policy + schema context for a question (C5 §2)."""

import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol

from eagleeye_llm.embeddings import Embedder
from eagleeye_sqlsafe.errors import SqlRejected
from eagleeye_sqlsafe.policy import SqlPolicy
from eagleeye_sqlsafe.validator import validate

from eagleeye_catalog.models import (
    Example,
    Grant,
    Metric,
    SchemaContext,
    SourceInfo,
    TableInfo,
)
from eagleeye_catalog.policy import build_policy, granted_tables

logger = logging.getLogger(__name__)

MAX_TABLES_IN_PROMPT = 10
TOP_METRICS = 5
TOP_EXAMPLES = 3
CACHE_TTL_S = 60.0
_TABLE_REF = re.compile(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b", re.IGNORECASE)


class CatalogStore(Protocol):
    async def get_source(self, source_id: str) -> SourceInfo | None: ...
    async def get_source_by_name(self, name: str) -> SourceInfo | None: ...
    async def sources_for_role(self, role: str) -> list[tuple[SourceInfo, Grant]]: ...
    async def get_grant(self, source_id: str, role: str) -> Grant | None: ...
    async def load_tables(self, source_id: str) -> list[TableInfo]: ...
    async def table_scores(self, source_id: str, vector: list[float]) -> dict[str, float]: ...
    async def top_metrics(self, source_id: str, vector: list[float], k: int) -> list[Metric]: ...
    async def top_examples(self, source_id: str, vector: list[float], k: int) -> list[Example]: ...


@dataclass(frozen=True)
class SourceAccess:
    source: SourceInfo
    grant: Grant
    tables: tuple[TableInfo, ...]  # granted + enabled
    policy: SqlPolicy


class CatalogService:
    def __init__(self, store: CatalogStore, embedder: Embedder | None = None) -> None:
        self._store = store
        self._embedder = embedder
        self._tables: dict[str, tuple[float, list[TableInfo]]] = {}

    async def _tables_for(self, source_id: str) -> list[TableInfo]:
        cached = self._tables.get(source_id)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_S:
            return cached[1]
        tables = await self._store.load_tables(source_id)
        self._tables[source_id] = (time.monotonic(), tables)
        return tables

    async def access(self, source_id: str, role: str) -> SourceAccess | None:
        """Everything a role may do on a source. None = no access (or unknown source)."""
        source = await self._store.get_source(source_id)
        if source is None:
            return None
        grant = await self._store.get_grant(source_id, role)
        tables = granted_tables(await self._tables_for(source_id), grant)
        if grant is None or not tables:
            return None
        return SourceAccess(source, grant, tables, build_policy(source, tables, grant))

    async def accessible_sources(self, role: str) -> list[SourceAccess]:
        out: list[SourceAccess] = []
        for source, _grant in await self._store.sources_for_role(role):
            acc = await self.access(source.id, role)
            if acc is not None:
                out.append(acc)
        return out

    async def resolve_source(self, role: str, name: str | None) -> SourceAccess | None:
        sources = await self.accessible_sources(role)
        if name:
            return next((s for s in sources if s.source.name == name), None)
        return sources[0] if len(sources) == 1 else None

    async def schema_context(self, acc: SourceAccess, question: str) -> SchemaContext:
        if self._embedder is None:
            return SchemaContext(acc.source, acc.tables, can_see_pii=acc.grant.can_see_pii)
        vector = (await self._embedder.embed([question[:2000]]))[0]
        tables = await self._rank_tables(acc, vector)
        metrics = await self._store.top_metrics(acc.source.id, vector, TOP_METRICS)
        examples = await self._store.top_examples(acc.source.id, vector, TOP_EXAMPLES * 2)
        allowed = {t.key for t in acc.tables}
        return SchemaContext(
            source=acc.source,
            tables=tables,
            metrics=tuple(m for m in metrics if _refs_allowed(m.definition_sql, allowed)),
            examples=tuple(_usable_examples(examples, acc.policy))[:TOP_EXAMPLES],
            can_see_pii=acc.grant.can_see_pii,
        )

    async def _rank_tables(self, acc: SourceAccess, vector: list[float]) -> tuple[TableInfo, ...]:
        if len(acc.tables) <= MAX_TABLES_IN_PROMPT:
            return acc.tables
        scores = await self._store.table_scores(acc.source.id, vector)
        ranked = sorted(acc.tables, key=lambda t: -scores.get(t.key, 0.0))
        top = list(ranked[:MAX_TABLES_IN_PROMPT])
        # add FK neighbours of the chosen tables so joins stay possible
        keys = {t.key for t in top}
        for t in list(top):
            for c in t.columns:
                ref = ".".join(c.fk_ref.split(".")[:2]) if c.fk_ref else None
                if ref and ref not in keys:
                    neighbour = next((x for x in acc.tables if x.key == ref), None)
                    if neighbour:
                        top.append(neighbour)
                        keys.add(ref)
        return tuple(top)


def _refs_allowed(definition: str, allowed: set[str]) -> bool:
    refs = {f"{a}.{b}".lower() for a, b in _TABLE_REF.findall(definition)}
    table_refs = {r for r in refs if r.split(".")[0] in {k.split(".")[0] for k in allowed}}
    return table_refs <= allowed


def _usable_examples(examples: list[Example], policy: SqlPolicy) -> list[Example]:
    """Few-shot examples must themselves pass this user's policy (no leaking hidden tables)."""
    usable = []
    for e in examples:
        try:
            validate(e.sql, policy)
        except SqlRejected:
            continue
        usable.append(e)
    return usable
