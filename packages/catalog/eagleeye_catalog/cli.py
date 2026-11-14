"""Onboard a data source into the catalog (idempotent).

uv run --package eagleeye-catalog python -m eagleeye_catalog.cli onboard grandline_ops
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import replace

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_llm.embeddings import LiteLLMEmbedder
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.litellm_adapter import LiteLLMGateway

from eagleeye_catalog.describe import draft_description, needs_description
from eagleeye_catalog.introspect import PostgresAdapter
from eagleeye_catalog.models import TableInfo
from eagleeye_catalog.repo import CatalogRepo
from eagleeye_catalog.seed import load_seed, merge

logger = logging.getLogger("catalog.onboard")
TEXT_TYPES = {"text", "character varying", "character"}


def resolve_dsn(dsn_env: str) -> str:
    """DSNs live in settings/env under the name the catalog stores — never in the DB."""
    value = getattr(get_settings(), dsn_env.lower(), None) or os.environ.get(dsn_env)
    if not value:
        raise SystemExit(f"{dsn_env} is not configured")
    return str(value)


def table_embedding_text(t: TableInfo) -> str:
    cols = ", ".join(f"{c.name} ({c.description})" if c.description else c.name for c in t.columns)
    return f"{t.key}: {t.description}. Columns: {cols}"


async def _add_samples(adapter: PostgresAdapter, t: TableInfo) -> TableInfo:
    if not t.enabled:
        return t
    columns = []
    for c in t.columns:
        if c.pii or c.data_type not in TEXT_TYPES or c.is_pk or c.fk_ref:
            columns.append(c)
            continue
        columns.append(
            replace(c, sample_values=await adapter.sample_values(t.schema, t.name, c.name))
        )
    return replace(t, columns=tuple(columns))


async def onboard(seed_name: str) -> dict:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    seed = load_seed(seed_name)
    source_conn = await asyncpg.connect(resolve_dsn(seed.source["dsn_env"]))
    try:
        adapter = PostgresAdapter(source_conn)
        tables = merge(await adapter.introspect(list(seed.source["schemas"])), seed)
        tables = [await _add_samples(adapter, t) for t in tables]
    finally:
        await source_conn.close()

    llm = LiteLLMGateway(s.model_fast, s.model_capable, reasoning_fast=s.reasoning_effort_fast)
    tables = [
        await draft_description(llm, t) if t.enabled and needs_description(t) else t for t in tables
    ]
    embedder = LiteLLMEmbedder(s.embed_model, s.embed_dim)
    table_vecs = await embedder.embed([table_embedding_text(t) for t in tables])
    metric_vecs = await embedder.embed([f"{m.name}: {m.description}" for m in seed.metrics])
    example_vecs = await embedder.embed([e.question for e in seed.examples])

    pool = await asyncpg.create_pool(s.database_url, min_size=1, max_size=2)
    try:
        repo = CatalogRepo(pool)
        source_id = await repo.upsert_source(seed.source)
        await repo.replace_catalog(
            source_id,
            tables,
            {t.key: v for t, v in zip(tables, table_vecs, strict=True)},
            list(zip(seed.metrics, metric_vecs, strict=True)),
            list(zip(seed.examples, example_vecs, strict=True)),
            seed.grants,
        )
    finally:
        await pool.close()
    return {
        "source_id": source_id,
        "tables": len(tables),
        "enabled": sorted(t.key for t in tables if t.enabled),
        "disabled": sorted(t.key for t in tables if not t.enabled),
        "metrics": len(seed.metrics),
        "examples": len(seed.examples),
        "grants": [g.role for g in seed.grants],
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="eagleeye_catalog")
    sub = parser.add_subparsers(dest="cmd", required=True)
    onboard_cmd = sub.add_parser("onboard", help="introspect + curate + embed a data source")
    onboard_cmd.add_argument("seed", help="seed name (e.g. grandline_ops) or path to a YAML file")
    args = parser.parse_args()
    summary = asyncio.run(onboard(args.seed))
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
