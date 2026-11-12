"""Cheap first layer: obvious attacks are blocked without spending an LLM call.

Patterns are deliberately narrow (low false positives); the LLM classifier
handles everything subtler.
"""

import re
import unicodedata
from dataclasses import dataclass

from eagleeye_agents.guard.verdict import GuardVerdict, Safety

MAX_INPUT_CHARS = 8000

_INJECTION = [
    (
        "ignore_instructions",
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|all|earlier|preceding|"
        r"your|the)\b.{0,30}\b(instructions?|prompts?|rules|directions|guidelines)\b",
    ),
    (
        "reveal_prompt",
        r"\b(reveal|show|print|repeat|output|display|dump|leak|tell me)\b.{0,40}"
        r"\b(system|hidden|initial|developer|original)\s+(prompt|instructions?|message|rules)\b",
    ),
    (
        "role_override",
        r"\byou are (now|no longer)\b.{0,40}\b(unrestricted|jailbroken|unfiltered|dan|"
        r"developer mode|without (rules|restrictions|filters))\b",
    ),
    ("jailbreak_mode", r"\b(do anything now|developer mode enabled|jailbreak mode)\b"),
    ("fake_delimiter", r"<\s*/?\s*(system|tool_data|context|assistant)\s*>"),
    (
        "no_restrictions",
        r"\b(act|behave|respond|pretend)\b.{0,30}\b(no|without)\s+(restrictions|filters|rules|"
        r"guidelines|limits)\b",
    ),
]
_EXFIL = [
    (
        "credential_dump",
        r"\b(list|show|give|dump|print|export)\b.{0,40}\b(all\s+)?(api[\s_-]?keys?|passwords?|"
        r"credentials|secret keys?|access tokens?)\b",
    ),
    (
        "other_users_data",
        r"\b(other|every|all)\s+users?'?s?\b.{0,30}\b(chats?|messages|documents|files|data|history)\b",
    ),
]
_COMPILED: list[tuple[str, Safety, re.Pattern[str]]] = [
    *(
        (name, "prompt_injection", re.compile(p, re.IGNORECASE | re.DOTALL))
        for name, p in _INJECTION
    ),
    *(
        (name, "sensitive_exfiltration", re.compile(p, re.IGNORECASE | re.DOTALL))
        for name, p in _EXFIL
    ),
]


@dataclass(frozen=True)
class RuleHit:
    name: str
    safety: Safety

    def verdict(self) -> GuardVerdict:
        return GuardVerdict(self.safety, "other", "uncertain", "rules", self.name)


def normalise(text: str) -> str:
    """NFKC folds look-alike characters; zero-width characters are dropped."""
    folded = unicodedata.normalize("NFKC", text)
    return re.sub(r"[​-‏⁠﻿]", "", folded)


def check_rules(text: str, denied_topics: tuple[str, ...] = ()) -> RuleHit | None:
    if len(text) > MAX_INPUT_CHARS:
        return RuleHit("too_long", "uncertain")
    clean = normalise(text)
    for name, safety, pattern in _COMPILED:
        if pattern.search(clean):
            return RuleHit(name, safety)
    lowered = clean.lower()
    for topic in denied_topics:
        if topic and re.search(rf"\b{re.escape(topic.lower())}\b", lowered):
            return RuleHit(f"denied_topic:{topic}", "harmful")
    return None
