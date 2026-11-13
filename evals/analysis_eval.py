"""Analysis golden-set eval: numeric accuracy of the real analysis sub-agent (C6 §8).

Run from the repo root with Docker and the sandbox image available (costs a few cents):
  uv run --package eagleeye-agent-worker python evals/analysis_eval.py [model ...]

Inputs are the fixtures in evals/fixtures (converted and profiled exactly like uploads) plus
a deterministic synthetic orders table. Expected numbers are computed here with pandas/scipy
from the same data; a case passes when every expected number appears in the agent's result
tables or stats (relative tolerance 0.5 %, absolute 0.005 for small values). Cases marked
`expect_status` pass when the agent declines with that status.
"""

import asyncio
import io
import json
import pathlib
import statistics
import sys
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from eagleeye_agents.analysis.agent import run_analysis_agent
from eagleeye_agents.analysis.types import LoadedInput
from eagleeye_agents.checks.numbers import numbers_in
from eagleeye_agents.context import AgentSettings, RunContext
from eagleeye_agents.control import CancelToken
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_core.config import get_settings
from eagleeye_datasets.convert import convert_csv, convert_xlsx
from eagleeye_datasets.profile import profile_parquet
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from eagleeye_sandbox.docker_executor import DockerExecutor
from scipy import stats

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE / "fixtures"
GOLDEN = HERE / "analysis_golden.jsonl"
CONCURRENCY = 3
REL_TOL, ABS_TOL = 0.005, 0.005


class NullSink:
    async def emit(self, event: str, data: dict) -> None:
        return None


class NullStore:
    async def visible_ready_documents(self, user_id: str) -> list:
        return []

    async def record_security_event(self, *args: Any) -> None:
        return None


def orders_parquet() -> bytes:
    rng = np.random.default_rng(7)
    web = rng.gamma(4.0, 400.0, 240)
    store = rng.gamma(4.0, 450.0, 160)
    frame = pd.DataFrame(
        {
            "order_id": np.arange(1, 401),
            "channel": ["web"] * 240 + ["store"] * 160,
            "order_value": np.round(np.concatenate([web, store]), 2),
        }
    )
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), buf)
    return buf.getvalue()


def loaded(name: str, parquet: bytes, column_map: dict[str, str] | None = None) -> LoadedInput:
    profile = profile_parquet(parquet, column_map)
    columns = tuple({"name": c["name"], "type": c["type"]} for c in profile["columns"])
    pii = frozenset(c["name"] for c in profile["columns"] if "pii" in c["flags"])
    return LoadedInput(name, "dataset", name, parquet, columns, profile["row_count"], pii, profile)


def build_inputs() -> dict[str, LoadedInput]:
    targets = convert_csv((FIXTURES / "targets.csv").read_bytes())
    revenue = convert_csv((FIXTURES / "monthly_revenue.csv").read_bytes())
    sheets = {s.sheet: s for s in convert_xlsx((FIXTURES / "regional_plan.xlsx").read_bytes())}
    return {
        "targets": loaded("targets", targets.parquet, targets.column_map),
        "revenue": loaded("revenue", revenue.parquet, revenue.column_map),
        "region_targets": loaded("region_targets", sheets["Region targets"].parquet),
        "headcount": loaded("headcount", sheets["Headcount"].parquet),
        "orders": loaded("orders", orders_parquet()),
    }


def frame(item: LoadedInput) -> pd.DataFrame:
    return pq.read_table(io.BytesIO(item.parquet)).to_pandas()


def references(inputs: dict[str, LoadedInput]) -> dict[str, Callable[[], list[float]]]:
    t, r = frame(inputs["targets"]), frame(inputs["revenue"])
    t["key"] = t["month"].str[:7]
    r["key"] = pd.to_datetime(r["month"]).dt.strftime("%Y-%m")
    j = r.merge(t, on="key")
    j["gap"] = j["net_revenue"] - j["target_eur"]
    reg, hc, o = (
        frame(inputs["region_targets"]),
        frame(inputs["headcount"]),
        frame(inputs["orders"]),
    )
    per_rep = reg["c_2026_target_eur"] / reg["sales_reps"]
    hc["net"] = hc["hires"] - hc["leavers"]
    web, store = o[o.channel == "web"].order_value, o[o.channel == "store"].order_value
    below = j[j.gap < 0]
    worst = j.loc[j.gap.idxmin()]
    hires_by_q = hc.groupby("quarter").hires.sum()
    return {
        "avg_target": lambda: [t.target_eur.mean()],
        "h1_target": lambda: [t[t.key <= "2026-06"].target_eur.sum()],
        "below_target": lambda: [*below.gap.tolist(), float(len(below))][:4],
        "total_gap": lambda: [j.gap.sum()],
        "largest_shortfall": lambda: [abs(worst.gap)],
        "october_ratio": lambda: [
            float(j[j.key == "2026-10"].eval("net_revenue / target_eur").iloc[0])
        ],
        "unmatched_months": lambda: [float(len(set(t.key) - set(r.key)))],
        "target_per_rep": lambda: [per_rep.max()],
        "target_rep_corr": lambda: [reg["c_2026_target_eur"].corr(reg["sales_reps"])],
        "net_hires": lambda: hc.groupby("region").net.sum().astype(float).tolist(),
        "top_quarter": lambda: [float(hires_by_q.max())],
        "welch_p": lambda: [float(stats.ttest_ind(web, store, equal_var=False).pvalue)],
        "median_by_channel": lambda: [web.median(), store.median()],
        "share_above_2000": lambda: [float((o.order_value > 2000).mean())],
        "revenue_slope": lambda: [float(np.polyfit(np.arange(1, len(r) + 1), r.net_revenue, 1)[0])],
    }


def close(expected: float, got: list[float]) -> bool:
    for g in got:
        for cand in (g, g * 100, g / 100):  # fractions vs percentages
            if abs(abs(cand) - abs(expected)) <= max(ABS_TOL, abs(expected) * REL_TOL):
                return True
    return False


def found_numbers(outcome: Any) -> list[float]:
    values: list[Any] = []
    for ref, rows in zip(outcome.artifacts, outcome.llm_previews, strict=True):
        values += [v for row in rows for v in row]
        values.append(ref.row_count)

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        else:
            values.append(x)

    walk(outcome.stats)
    return numbers_in(values)


class EvalWorkspace:
    def __init__(self, inputs: dict[str, LoadedInput]) -> None:
        self.inputs = inputs

    async def list_datasets(self, user_id: str) -> list:
        return []

    async def load(self, user_id: str, ref_id: str) -> LoadedInput | None:
        return self.inputs.get(ref_id)

    async def save_result(self, **kw: Any) -> str:
        return f"eval-{kw['title']}"

    async def sandbox_runs_last_hour(self, user_id: str) -> int:
        return 0

    async def log_sandbox_run(self, **kw: Any) -> None:
        return None


async def run_model(model: str, cases: list[dict], inputs: dict[str, LoadedInput]) -> list[dict]:
    s = get_settings()
    llm = LiteLLMGateway(model, model, reasoning_fast="none", reasoning_capable="none")
    executor = DockerExecutor(s.sandbox_image, s.sandbox_mem_mb, s.sandbox_timeout_s)
    workspace = EvalWorkspace(inputs)
    refs = references(inputs)

    async def never() -> bool:
        return False

    async def one(case: dict) -> dict:
        ctx = RunContext.create(
            run_id="",
            chat_id="eval",
            user_id="eval",
            llm=llm,
            retriever=None,
            store=NullStore(),
            sink=NullSink(),
            cancel=CancelToken(never),
            prompts=load_prompts(),
            settings=AgentSettings(),
        )
        ctx.workspace, ctx.executor, ctx.analysis_available = workspace, executor, True
        started = time.perf_counter()
        outcome = await run_analysis_agent(ctx, case["question"], case["inputs"], None)
        secs = time.perf_counter() - started
        if case.get("expect_status"):
            ok, missing = outcome.status == case["expect_status"], []
        else:
            got = found_numbers(outcome) if outcome.status == "ok" else []
            missing = [e for e in refs[case["ref"]]() if not close(float(e), got)]
            ok = outcome.status == "ok" and not missing
        return {
            "id": case["id"],
            "ok": ok,
            "status": outcome.status,
            "mode": outcome.mode,
            "attempts": outcome.attempts,
            "secs": secs,
            "cost": ctx.usage.cost_usd,
            "missing": [round(float(m), 4) for m in missing],
        }

    sem = asyncio.Semaphore(CONCURRENCY)

    async def limited(case: dict) -> dict:
        async with sem:
            return await one(case)

    return await asyncio.gather(*(limited(c) for c in cases))


def report(model: str, results: list[dict]) -> None:
    answerable = [r for r in results if r["id"].startswith("a")]
    declines = [r for r in results if not r["id"].startswith("a")]
    acc = sum(r["ok"] for r in answerable)
    modes = {m: sum(1 for r in answerable if r["mode"] == m) for m in ("sql", "python")}
    retried = sum(1 for r in answerable if r["ok"] and r["attempts"] > 1)
    print(f"\n{model}")
    print(f"  numeric accuracy : {acc}/{len(answerable)} = {acc / len(answerable):.0%}")
    print(f"  declines correct : {sum(r['ok'] for r in declines)}/{len(declines)}")
    print(f"  mode used        : DuckDB SQL {modes['sql']}, Python {modes['python']}")
    print(f"  self-corrected   : {retried} correct after a retry")
    print(f"  latency p50      : {statistics.median(r['secs'] for r in results):.1f}s")
    print(f"  cost             : ${sum(r['cost'] for r in results):.4f} for {len(results)} cases")
    for r in results:
        if not r["ok"]:
            print(
                f"    FAIL {r['id']} status={r['status']} mode={r['mode']} missing={r['missing']}"
            )


async def main(models: list[str]) -> None:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    cases = [json.loads(x) for x in GOLDEN.read_text("utf-8").splitlines() if x.strip()]
    inputs = build_inputs()
    for model in models:
        report(model, await run_model(model, cases, inputs))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or [get_settings().model_capable]))
