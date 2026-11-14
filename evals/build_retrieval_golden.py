"""Build the Grand Line retrieval golden set from the generated documents (one-off, ~USD 0.05).

  uv run --package eagleeye-ingest-worker python evals/build_retrieval_golden.py

For a sample of documents, the LLM turns one required fact into a natural question (worded
differently from the document) plus a short answer span. A span is kept only if it appears
verbatim in the document's text, so every question has a checkable answer. Every third
question is held out ("test").
"""

import asyncio
import json
import random
import re
import sys
from pathlib import Path

from eagleeye_core.config import get_settings
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.gateway import ChatMessage
from eagleeye_llm.litellm_adapter import LiteLLMGateway

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "grandline" / "out"
GOLDEN = Path(__file__).with_name("retrieval_golden.jsonl")
PER_CATEGORY = {"policies": 30, "incident-reports": 20, "monthly-reports": 14, "port-profiles": 10,
                "board-and-strategy": 10, "meeting-minutes": 6, "customer-contracts": 10}
PROMPT = """Document title: {title}
Fact stated in the document: {fact}

Write one question an employee might ask that this fact answers. Word it differently from
the fact (paraphrase, no copied phrases longer than three words) but include enough context
(month, port, vessel, policy topic, contract or customer) that it has exactly one answer.
Then give the shortest exact substring of the fact (2 to 8 words, usually a number with its
unit) that answers it.
Reply as JSON: {{"question": "...", "span": "..."}}"""


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def doc_text(entry: dict) -> str:
    md = OUT / "md" / f"{entry['slug']}.md"
    if md.exists():
        return md.read_text(encoding="utf-8")
    return ""


async def main() -> int:
    s = get_settings()
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    llm = LiteLLMGateway(s.model_fast, s.model_capable, reasoning_fast=s.reasoning_effort_fast)
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    rng = random.Random(7)  # noqa: S311 - sampling, not security
    picks = []
    for cat, n in PER_CATEGORY.items():
        docs = [d for d in manifest if d["category"] == cat and d["facts"]]
        picks += rng.sample(docs, min(n, len(docs)))
    sem = asyncio.Semaphore(8)

    async def one(entry: dict) -> dict | None:
        fact = rng.choice(entry["facts"])
        text = doc_text(entry)
        async with sem:
            raw, _ = await llm.complete("fast", [ChatMessage("user", PROMPT.format(
                title=entry["title"], fact=fact))], max_tokens=200, json_mode=True)
        try:
            item = json.loads(raw)
        except ValueError:
            return None
        span = str(item.get("span", "")).strip().rstrip(".")
        haystack = norm(text) if text else norm(fact)
        if not span or norm(span) not in haystack or norm(span) not in norm(fact):
            return None
        return {"doc": entry["slug"], "kind": entry["category"], "title": entry["title"],
                "question": item["question"].strip(), "span": span}

    rows = [r for r in await asyncio.gather(*(one(e) for e in picks)) if r]
    with GOLDEN.open("w", encoding="utf-8", newline="\n") as f:
        for i, r in enumerate(rows, start=1):
            r = {"id": f"q{i:03d}", **r, "split": "test" if i % 3 == 0 else "dev"}
            f.write(json.dumps(r) + "\n")
    print(f"{len(rows)} questions from {len(picks)} documents -> {GOLDEN}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
