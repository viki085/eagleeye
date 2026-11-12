"""Head-to-head model benchmark on EagleEye's own workloads (costs well under $1).

Run from the repo root:
  uv run --package eagleeye-agents python evals/model_bench.py [fast|capable|all]

fast tier    -> the guard corpus (safety + intent JSON classification)
capable tier -> grounded answers with [n] citations, and supervisor tool calling
Every call goes through LiteLLMGateway, so parameter incompatibilities surface as errors.
"""

import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field

from eagleeye_agents.guard.classifier import classify
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_agents.tools.registry import default_registry
from eagleeye_core.config import get_settings
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.gateway import ChatMessage
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from guard_smoke import CORPUS, DOC_TITLES

# (model, reasoning_effort). Effort is ignored for classic models like gpt-4o.
FAST_CANDIDATES = [
    ("gpt-4o-mini", ""),
    ("gpt-6-luna", "none"),
    ("gpt-6-luna", "low"),
    ("gpt-5-nano", "minimal"),
    ("gpt-5.4-nano", "none"),
]
CAPABLE_CANDIDATES = [
    ("gpt-4o", ""),
    ("gpt-6.1-terra", "none"),
    ("gpt-6.1-terra", "low"),
    ("gpt-6.1-sol", "none"),
    ("gpt-6-luna", "none"),
]
REPEATS = 2

CONTEXT = """<context>
[1] Acme Customer Policy › 1 RETURNS POLICY (p. 1)
Customers may return most items within 30 days of delivery for a full refund. Electronics such as
laptops, tablets and headphones have a shorter return window of 14 days. Opened electronics incur
a 15 percent restocking fee unless the device is defective.

[2] Acme Customer Policy › 2 SHIPPING POLICY (p. 2)
Standard shipping is free for orders above 50 euros and takes 3 to 5 business days. Express
shipping costs 12 euros and arrives the next business day when ordered before 2 pm CET.

[3] Engineering Handbook › On-call rotation
The on-call engineer receives a stipend of 400 euros per week and must acknowledge pages within
15 minutes. Friday deploys require approval from the VP of Engineering.
</context>"""

RAG_CASES = [
    ("What restocking fee applies to opened headphones?", ["15"], {1}),
    ("How much does express shipping cost and when does it arrive?", ["12"], {2}),
    ("Who must approve a Friday deploy?", ["VP"], {3}),
    ("What is the warranty period for laptops?", [], set()),  # not in context → must decline
]
TOOL_CASES = [
    "Compare the electronics return window with the on-call acknowledgement time.",
    "Which of my documents mention shipping, and what does express shipping cost?",
]


@dataclass
class Stats:
    model: str
    latencies: list[float] = field(default_factory=list)
    ttfts: list[float] = field(default_factory=list)
    cost: float = 0.0
    calls: int = 0
    errors: list[str] = field(default_factory=list)
    passed: int = 0
    total: int = 0

    def line(self, extra: str = "") -> str:
        p50 = statistics.median(self.latencies) if self.latencies else float("nan")
        ttft = f"{statistics.median(self.ttfts):5.2f}s" if self.ttfts else "   -  "
        per_call = self.cost / self.calls if self.calls else 0
        return (
            f"{self.model:20s} quality {self.passed:>2}/{self.total:<2} | p50 {p50:5.2f}s | "
            f"TTFT {ttft} | ${per_call * 1000:7.3f} per 1k calls | "
            f"errors {len(self.errors)} {extra}"
        )


def _gateway(model: str, effort: str) -> LiteLLMGateway:
    return LiteLLMGateway(model, model, reasoning_fast=effort, reasoning_capable=effort)


def _label(model: str, effort: str) -> str:
    return f"{model}/{effort}" if effort else model


async def bench_fast(model: str, effort: str) -> Stats:
    s = Stats(_label(model, effort))
    llm = _gateway(model, effort)
    prompt = load_prompts().text("guard")
    rows = [json.loads(x) for x in CORPUS.read_text("utf-8").splitlines() if x.strip()]
    sem = asyncio.Semaphore(6)

    async def one(row: dict) -> None:
        async with sem:
            started = time.perf_counter()
            try:
                verdict, usage = await classify(llm, prompt, row["text"], [], DOC_TITLES, False)
            except Exception as exc:  # noqa: BLE001 - record and continue
                s.errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
                return
            s.latencies.append(time.perf_counter() - started)
            s.cost += usage.cost_usd
            s.calls += 1
            s.total += 1
            safe_ok = verdict.allowed == row["safe"]
            intent_ok = not row["intent"] or verdict.intent == row["intent"]
            s.passed += int(safe_ok and intent_ok)

    await asyncio.gather(*(one(r) for r in rows))
    return s


async def _stream(llm: LiteLLMGateway, messages: list[ChatMessage], tools=None):  # noqa: ANN001, ANN202
    started = time.perf_counter()
    first: float | None = None
    text, done = [], None
    async for chunk in llm.stream("capable", messages, max_tokens=1024, tools=tools):
        if chunk.done:
            done = chunk
        elif chunk.text:
            first = first or time.perf_counter() - started
            text.append(chunk.text)
    return "".join(text), done, time.perf_counter() - started, first


async def bench_capable(model: str, effort: str) -> Stats:
    s = Stats(_label(model, effort))
    llm = _gateway(model, effort)
    prompts = load_prompts()
    specs = default_registry().specs()
    for _ in range(REPEATS):
        for question, must, cites in RAG_CASES:
            msgs = [
                ChatMessage("system", f"{prompts.text('rag')}\n\n{CONTEXT}"),
                ChatMessage("user", question),
            ]
            try:
                text, done, secs, ttft = await _stream(llm, msgs)
            except Exception as exc:  # noqa: BLE001
                s.errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
                continue
            used = {n for n in range(1, 10) if f"[{n}]" in text}
            if must:
                ok = all(m in text for m in must) and cites <= used and used <= {1, 2, 3}
            else:
                ok = not used and any(w in text.lower() for w in ("not", "no ", "don't", "doesn"))
            s.total += 1
            s.passed += int(ok)
            s.latencies.append(secs)
            if ttft:
                s.ttfts.append(ttft)
            s.cost += done.usage.cost_usd if done else 0
            s.calls += 1
        for question in TOOL_CASES:
            msgs = [
                ChatMessage("system", prompts.text("supervisor")),
                ChatMessage("user", question),
            ]
            try:
                _text, done, secs, _ = await _stream(llm, msgs, tools=specs)
            except Exception as exc:  # noqa: BLE001
                s.errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
                continue
            calls = done.tool_calls if done else ()
            valid = all(_valid_args(c.arguments_json) for c in calls)
            s.total += 1
            s.passed += int(len(calls) >= 1 and valid)
            s.latencies.append(secs)
            s.cost += done.usage.cost_usd if done else 0
            s.calls += 1
    return s


def _valid_args(raw: str) -> bool:
    try:
        return isinstance(json.loads(raw or "{}"), dict)
    except json.JSONDecodeError:
        return False


async def main(which: str) -> None:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    if which in ("fast", "all"):
        print("FAST TIER — guard corpus (40 prompts: safety + intent)")
        for stats in await asyncio.gather(*(bench_fast(m, e) for m, e in FAST_CANDIDATES)):
            print(" ", stats.line())
            for e in sorted(set(stats.errors))[:2]:
                print("     ERR", e)
    if which in ("capable", "all"):
        print(f"\nCAPABLE TIER — {len(RAG_CASES)} grounded answers + {len(TOOL_CASES)} tool-call "
              f"plans, ×{REPEATS}")
        for stats in await asyncio.gather(
            *(bench_capable(m, e) for m, e in CAPABLE_CANDIDATES)
        ):
            print(" ", stats.line())
            for e in sorted(set(stats.errors))[:2]:
                print("     ERR", e)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
