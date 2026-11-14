"""Guard smoke eval against the real fast model (costs a few cents).

Run from the repo root:
  uv run --package eagleeye-agents python evals/guard_smoke.py

Reports block rate on attacks, false-positive rate on benign prompts, intent accuracy
(for rows with a labelled intent) and latency. Rows with intent=null only check safety.
"""

import asyncio
import json
import pathlib
import statistics
import sys
import time

from eagleeye_agents.errors import GuardUnavailableError
from eagleeye_agents.guard.classifier import classify
from eagleeye_agents.guard.rules import check_rules
from eagleeye_agents.guard.verdict import GuardVerdict
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_core.config import get_settings
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.litellm_adapter import LiteLLMGateway

CORPUS = pathlib.Path(__file__).with_name("guard_corpus.jsonl")
DOC_TITLES = ["Reefer Cargo Handling SOP", "Customs Clearance Procedure"]
CONCURRENCY = 6


async def judge(llm: LiteLLMGateway, prompt: str, text: str) -> tuple[GuardVerdict, float, str]:
    started = time.perf_counter()
    hit = check_rules(text)
    if hit is not None:
        return hit.verdict(), time.perf_counter() - started, "rules"
    try:
        verdict, _ = await classify(llm, prompt, text, [], DOC_TITLES, False)
    except GuardUnavailableError:
        return GuardVerdict("uncertain", "other", "uncertain", "error"), 0.0, "error"
    return verdict, time.perf_counter() - started, "llm"


async def main() -> int:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    llm = LiteLLMGateway(
        s.model_fast,
        s.model_capable,
        reasoning_fast=s.reasoning_effort_fast,
        reasoning_capable=s.reasoning_effort_capable,
    )
    print(f"guard model: {s.model_fast} (reasoning_effort={s.reasoning_effort_fast or 'default'})")
    prompt = load_prompts().text("guard")
    rows = [json.loads(line) for line in CORPUS.read_text("utf-8").splitlines() if line.strip()]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(row: dict) -> tuple[dict, GuardVerdict, float, str]:
        async with sem:
            verdict, secs, layer = await judge(llm, prompt, row["text"])
            return row, verdict, secs, layer

    results = await asyncio.gather(*(one(r) for r in rows))
    attacks = [(r, v) for r, v, _, _ in results if not r["safe"]]
    benign = [(r, v) for r, v, _, _ in results if r["safe"]]
    labelled = [(r, v) for r, v in benign if r["intent"]]
    blocked = sum(not v.allowed for _, v in attacks)
    false_pos = [(r, v) for r, v in benign if not v.allowed]
    intent_ok = sum(v.intent == r["intent"] for r, v in labelled)
    llm_latency = [secs for _, _, secs, layer in results if layer == "llm"]
    by_rules = sum(layer == "rules" for _, _, _, layer in results)

    print(f"rows: {len(rows)}  (attacks {len(attacks)}, benign {len(benign)})")
    print(
        f"attack block rate:   {blocked}/{len(attacks)} = {blocked / len(attacks):.0%}"
        f"   ({by_rules} caught by rules without an LLM call)"
    )
    print(
        f"false positives:     {len(false_pos)}/{len(benign)} = {len(false_pos) / len(benign):.0%}"
    )
    print(f"intent accuracy:     {intent_ok}/{len(labelled)} = {intent_ok / len(labelled):.0%}")
    if llm_latency:
        p95 = sorted(llm_latency)[int(0.95 * (len(llm_latency) - 1))]
        print(f"LLM guard latency:   p50 {statistics.median(llm_latency):.2f}s  p95 {p95:.2f}s")
    for r, v in [(r, v) for r, v in attacks if v.allowed]:
        print(f"  MISSED ATTACK: {r['text'][:70]!r} -> {v.safe}")
    for r, v in false_pos:
        print(f"  FALSE POSITIVE: {r['text'][:70]!r} -> {v.safe} ({v.source} {v.detail})")
    for r, v in [(r, v) for r, v in labelled if v.intent != r["intent"]]:
        print(f"  INTENT: {r['text'][:60]!r} expected {r['intent']} got {v.intent}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
