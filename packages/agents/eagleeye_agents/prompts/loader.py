"""Prompts live in markdown files, reviewed like code; each run records their versions."""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

PROMPT_NAMES = (
    "guard",
    "simple",
    "rag",
    "supervisor",
    "refusal",
    "unavailable",
    "sql_generate",
    "sql_answer",
)


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str
    version: str  # first 8 hex chars of sha256(text)


@dataclass(frozen=True)
class Prompts:
    by_name: dict[str, Prompt]

    def text(self, name: str) -> str:
        return self.by_name[name].text

    def versions(self) -> dict[str, str]:
        return {name: p.version for name, p in self.by_name.items()}


def _load_one(name: str) -> Prompt:
    text = resources.files("eagleeye_agents.prompts").joinpath(f"{name}.md").read_text("utf-8")
    text = text.strip()
    return Prompt(name, text, hashlib.sha256(text.encode()).hexdigest()[:8])


@lru_cache
def load_prompts() -> Prompts:
    return Prompts({name: _load_one(name) for name in PROMPT_NAMES})
