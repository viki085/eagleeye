"""Text-to-SQL golden-set eval: execution accuracy of the real SQL sub-agent (C5 §7).

Run from the repo root with the warehouse, gateway and Supabase up (costs a few cents):
  uv run --package eagleeye-agent-worker python evals/sql_eval.py [model ...]

For each answerable case the agent's result is compared with the reference query's result:
every reference column must match some result column (as a multiset, numbers rounded to
2 dp, timestamps to dates) and row counts must be equal — extra columns are allowed.
Refusal cases pass when no result was produced and no forbidden column was returned.
Runs as the first `member` user; the gateway enforces that role's grants.
"""

import asyncio
import json
import pathlib
import statistics
import sys
import time
from collections import Counter
from decimal import Decimal
from typing import Any

import asyncpg
from eagleeye_agents.context import AgentSettings, RunContext
from eagleeye_agents.control import CancelToken
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_agents.sql.agent import run_sql_agent
from eagleeye_agents.sql.gateway_client import HttpGateway
from eagleeye_catalog.repo import CatalogRepo
from eagleeye_catalog.service import CatalogService
from eagleeye_core.config import get_settings
from eagleeye_core.service_auth import resolve_secret
from eagleeye_llm.embeddings import LiteLLMEmbedder
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.litellm_adapter import LiteLLMGateway

GOLDEN = pathlib.Path(__file__).with_name("sql_golden.jsonl")
CONCURRENCY = 4


class NullSink:
    async def emit(self, event: str, data: dict) -> None:
        return None


class NullStore:
    async def visible_ready_documents(self, user_id: str) -> list:
        return []

    async def record_security_event(self, *args: Any) -> None:
        return None


def norm(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float | Decimal):
        return round(float(value), 2)
    text = str(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]  # timestamps / dates → date
    try:
        return round(float(text), 2)
    except ValueError:
        return text.strip().lower()


def columns_of(rows: list[tuple]) -> list[Counter]:
    width = len(rows[0]) if rows else 0
    return [Counter(norm(r[i]) for r in rows) for i in range(width)]


def matches(reference: list[tuple], got_rows: list[tuple]) -> bool:
    if len(reference) == 1 and len(got_rows) > 1:
        # "Which X has the most…": a ranked list whose first row is the answer is correct
        got_rows = got_rows[:1]
    if len(reference) != len(got_rows):
        return False
    got_cols = columns_of(got_rows)
    return all(any(ref == g for g in got_cols) for ref in columns_of(reference))


async def evaluate_case(ctx_factory, wh: asyncpg.Pool, case: dict) -> dict:  # noqa: ANN001
    ctx = ctx_factory()
    started = time.perf_counter()
    outcome = await run_sql_agent(ctx, case["question"], None, None)
    secs = time.perf_counter() - started
    rows = [tuple(r) for r in outcome.llm_preview]
    cols = [c["name"].lower() for c in outcome.artifact.columns] if outcome.artifact else []
    reference: list[tuple] = []
    if case.get("refuse"):
        leaked = any(f in c for c in cols for f in case.get("forbidden", []))
        ok = outcome.artifact is None or (not leaked and bool(case.get("forbidden")))
    else:
        reference = [tuple(r.values()) for r in await wh.fetch(case["sql"])]
        ok = outcome.status == "ok" and matches(reference, rows)
    return {
        "id": case["id"],
        "ok": ok,
        "status": outcome.status,
        "attempts": outcome.attempts,
        "secs": secs,
        "cost": ctx.usage.cost_usd,
        "cols": cols,
        "sql": outcome.artifact.sql if outcome.artifact else "",
        "got": rows[:3],
        "want": reference[:3],
    }


async def run_model(model: str, cases: list[dict]) -> list[dict]:
    s = get_settings()
    meta = await asyncpg.create_pool(s.database_url, min_size=1, max_size=4)
    wh = await asyncpg.create_pool(s.warehouse_dsn, min_size=1, max_size=4)
    user_id = str(
        await meta.fetchval(
            "SELECT id FROM users WHERE role = 'member' ORDER BY created_at LIMIT 1"
        )
    )
    llm = LiteLLMGateway(model, model, reasoning_fast="none", reasoning_capable="none")
    catalog = CatalogService(CatalogRepo(meta), LiteLLMEmbedder(s.embed_model, s.embed_dim))
    gateway = HttpGateway(s.gateway_url, resolve_secret(s.gateway_hmac_secret, s.app_env))

    async def never() -> bool:
        return False

    def ctx_factory() -> RunContext:
        ctx = RunContext.create(
            run_id="",
            chat_id="eval",
            user_id=user_id,
            llm=llm,
            retriever=None,
            store=NullStore(),
            sink=NullSink(),
            cancel=CancelToken(never),
            prompts=load_prompts(),
            settings=AgentSettings(),
        )
        ctx.gateway, ctx.catalog, ctx.sql_available = gateway, catalog, True
        return ctx

    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(case: dict) -> dict:
        async with sem:
            return await evaluate_case(ctx_factory, wh, case)

    try:
        return await asyncio.gather(*(one(c) for c in cases))
    finally:
        await gateway.aclose()
        await meta.close()
        await wh.close()


def report(model: str, results: list[dict]) -> None:
    answerable = [r for r in results if not r["id"].startswith("r")]
    refusals = [r for r in results if r["id"].startswith("r")]
    acc = sum(r["ok"] for r in answerable)
    corrected = sum(1 for r in answerable if r["ok"] and r["attempts"] > 1)
    print(f"\n{model}")
    print(f"  execution accuracy : {acc}/{len(answerable)} = {acc / len(answerable):.0%}")
    print(f"  refusals correct   : {sum(r['ok'] for r in refusals)}/{len(refusals)}")
    print(f"  self-corrected     : {corrected} answered correctly after a retry")
    print(f"  latency p50        : {statistics.median(r['secs'] for r in results):.1f}s")
    print(f"  cost               : ${sum(r['cost'] for r in results):.4f} for {len(results)} cases")
    for r in results:
        if not r["ok"]:
            print(
                f"    FAIL {r['id']} status={r['status']} attempts={r['attempts']} cols={r['cols']}"
            )
            if r["sql"]:
                print(f"         sql : {' '.join(r['sql'].split())}")
                print(f"         got : {r['got']}")
                print(f"         want: {r['want']}")


async def main(models: list[str]) -> None:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    cases = [json.loads(x) for x in GOLDEN.read_text("utf-8").splitlines() if x.strip()]
    for model in models:
        report(model, await run_model(model, cases))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or [get_settings().model_capable]))
