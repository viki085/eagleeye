"""Analysis golden-set eval: numeric accuracy of the real analysis sub-agent (C6 §8).

Run from the repo root with Docker and the sandbox image available (costs a few cents):
  uv run --package eagleeye-agent-worker --with scipy python evals/analysis_eval.py [model ...]

Inputs are the Grand Line data files from data/grandline/make_files.py, converted and profiled
exactly like uploads. Expected numbers are computed here with pandas/scipy
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

import pandas as pd
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
FILES = HERE.parent / "data" / "grandline" / "out" / "files"  # data/grandline/make_files.py
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


def loaded(name: str, parquet: bytes, column_map: dict[str, str] | None = None) -> LoadedInput:
    profile = profile_parquet(parquet, column_map)
    columns = tuple({"name": c["name"], "type": c["type"]} for c in profile["columns"])
    pii = frozenset(c["name"] for c in profile["columns"] if "pii" in c["flags"])
    return LoadedInput(name, "dataset", name, parquet, columns, profile["row_count"], pii, profile)


def build_inputs() -> dict[str, LoadedInput]:
    out: dict[str, LoadedInput] = {}
    for name, file in (
        ("survey", "customer_survey_2026.csv"),
        ("fuel", "vessel_fuel_and_emissions.csv"),
        ("utilisation", "voyage_utilisation_by_week.csv"),
        ("brent", "brent_crude_daily.csv"),
        ("congestion", "port_congestion_weekly.csv"),
    ):
        c = convert_csv((FILES / file).read_bytes())
        out[name] = loaded(name, c.parquet, c.column_map)
    sheets = {
        x.sheet: x for x in convert_xlsx((FILES / "demand_forecast_2027_by_lane.xlsx").read_bytes())
    }
    out["forecast"] = loaded("forecast", sheets["Forecast"].parquet)
    return out


def frame(item: LoadedInput) -> pd.DataFrame:
    return pq.read_table(io.BytesIO(item.parquet)).to_pandas()


def references(inputs: dict[str, LoadedInput]) -> dict[str, Callable[[], list[float]]]:
    sv, fu, ut = frame(inputs["survey"]), frame(inputs["fuel"]), frame(inputs["utilisation"])
    br, cg = frame(inputs["brent"]), frame(inputs["congestion"])
    fc = frame(inputs["forecast"])
    fa, ft = fc[fc.trade_lane == "AEU"], fc[fc.trade_lane == "TPW"]
    ltr = sv["likelihood_to_recommend_0_10"]
    fu_year = pd.to_datetime(fu["departure_date"]).dt.year
    ut_year = pd.to_datetime(ut["week_start"]).dt.year
    br_year = pd.to_datetime(br["date"]).dt.year
    ut26 = ut[ut_year == 2026].groupby("service_code").utilisation.mean()
    strategic = ltr[sv.segment == "strategic"]
    sme = ltr[sv.segment == "sme"]
    return {
        "avg_ltr": lambda: [ltr.mean()],
        "nps": lambda: [float(((ltr >= 9).mean() - (ltr <= 6).mean()) * 100)],
        "ltr_by_segment": lambda: (
            sv.groupby("segment").likelihood_to_recommend_0_10.mean().tolist()
        ),
        "comment_share": lambda: [float((sv["comment"].fillna("").str.len() > 0).mean())],
        "ltr_welch": lambda: [float(stats.ttest_ind(strategic, sme, equal_var=False).pvalue)],
        "fuel_2025": lambda: [fu[fu_year == 2025].fuel_consumed_mt.sum()],
        "intensity_by_fuel": lambda: fu.groupby("fuel_type").co2_grams_per_teu_km.mean().tolist(),
        "distance_by_routing": lambda: fu.groupby("routing").distance_nm.mean().tolist(),
        "speed_intensity_corr": lambda: [fu["avg_speed_knots"].corr(fu["co2_grams_per_teu_km"])],
        "util_by_direction": lambda: ut.groupby("direction").utilisation.mean().tolist(),
        "top_service_2026": lambda: [float(ut26.max())],
        "aeu_base_2027": lambda: [fa.base_teu.sum()],
        "tpw_range": lambda: [float((ft.high_teu - ft.low_teu).sum())],
        "two_lanes_base": lambda: [float(fa.base_teu.sum() + ft.base_teu.sum())],
        "brent_avg_2025": lambda: [br[br_year == 2025].brent_usd_per_barrel.mean()],
        "brent_max_2024": lambda: [br[br_year == 2024].brent_usd_per_barrel.max()],
        "worst_port_delay": lambda: [float(cg.groupby("port").avg_delay_hours.mean().max())],
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
