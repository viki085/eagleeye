"""LLM writer: turns a brief plus exact facts into a Markdown document, and checks the facts.

Each document's Markdown is cached under out/md, so re-running never pays twice. A document
that leaves out a required figure is retried once; if it is still missing, the facts are
appended as a "Key facts" section so the document can never contradict the warehouse.
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from eagleeye_core.config import get_settings
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.gateway import ChatMessage
from eagleeye_llm.litellm_adapter import LiteLLMGateway

SYSTEM = """You write internal business documents for Grand Line Shipping Company, a fictional \
container shipping line headquartered in Rotterdam with regional offices in Singapore, Dubai, \
New York, Santos and Shanghai. It runs 8 weekly services (AEX Asia - North Europe, AMX Asia - \
Mediterranean, TPX Transpacific, AUX Asia - US East Coast, ESX Asia - South America East Coast, \
TAX Transatlantic, MEX Asia - Middle East and India, IAX Intra-Asia) with about 60 ships.

Rules:
- Write realistic, specific, professional English, as a real carrier would. No marketing tone.
- Output Markdown only: '## ' for sections, '### ' for subsections, '-' bullets, numbered steps,
  and Markdown tables where they help. Do not repeat the document title as a heading.
- Every fact listed under FACTS must appear in the document with the exact same numbers,
  dates, codes and names. Do not change or round them.
- Do not invent other statistics, money amounts or dates. You may add procedural detail,
  responsibilities, examples and context that do not contradict the facts.
- Never mention real shipping companies by name. Grand Line is the only carrier named."""


@dataclass(frozen=True)
class Brief:
    slug: str
    title: str
    kind: str  # e.g. "policy", "incident investigation report"
    audience: str
    sections: tuple[str, ...]
    facts: tuple[str, ...]
    words: int


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(fact: str) -> set[str]:
    return {n.replace(",", "") for n in NUMBER.findall(fact) if len(n.replace(",", "")) >= 2}


def missing_facts(text: str, facts: tuple[str, ...]) -> list[str]:
    flat = text.replace(",", "")
    return [f for f in facts if not all(n in flat for n in _numbers(f))]


class Writer:
    def __init__(self, cache: Path, concurrency: int = 8) -> None:
        s = get_settings()
        export_provider_keys(s.openai_api_key, s.anthropic_api_key)
        self._llm = LiteLLMGateway(s.model_fast, s.model_capable,
                                   fallback_fast=s.model_fast_fallback,
                                   reasoning_fast=s.reasoning_effort_fast)
        self._cache = cache
        self._cache.mkdir(parents=True, exist_ok=True)
        self._sem = asyncio.Semaphore(concurrency)
        self.cost_usd = 0.0
        self.calls = 0

    async def write(self, brief: Brief) -> str:
        path = self._cache / f"{brief.slug}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        async with self._sem:
            text = await self._ask(brief, reminder=None)
            gaps = missing_facts(text, brief.facts)
            if gaps:
                text = await self._ask(brief, reminder=gaps)
                gaps = missing_facts(text, brief.facts)
            if gaps:
                text += "\n\n## Key facts\n\n" + "\n".join(f"- {f}" for f in gaps) + "\n"
        path.write_text(text, encoding="utf-8")
        return text

    async def _ask(self, brief: Brief, reminder: list[str] | None) -> str:
        facts = "\n".join(f"- {f}" for f in brief.facts) or "- (none)"
        prompt = (f"Write the {brief.kind} titled \"{brief.title}\" for {brief.audience}.\n"
                  f"Length: about {brief.words} words.\n"
                  f"Sections, in this order: {'; '.join(brief.sections)}.\n\nFACTS:\n{facts}\n")
        if reminder:
            prompt += ("\nYour previous draft left out or changed these facts. Include each of "
                       "them exactly:\n" + "\n".join(f"- {f}" for f in reminder))
        text, usage = await self._llm.complete(
            "fast", [ChatMessage("system", SYSTEM), ChatMessage("user", prompt)],
            max_tokens=min(8000, int(brief.words * 2.2) + 400))
        self.cost_usd += usage.cost_usd
        self.calls += 1
        return text.strip()
