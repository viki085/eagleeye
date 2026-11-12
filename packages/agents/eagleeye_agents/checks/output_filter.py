"""Output filter (C3 §2.6 / C8 layer 6): secrets, system-prompt leakage, unsafe links."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

SAFE_FALLBACK = (
    "I generated a response that may have contained sensitive information, so I've withheld it. "
    "Please rephrase your request."
)
MIN_LEAK_LINE_CHARS = 40

_SECRETS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}")),
    ("clerk_key", re.compile(r"\bsk_(?:test|live)_[A-Za-z0-9]{20,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
]
_JS_LINK = re.compile(r"\]\(\s*(?:javascript|vbscript|data):(?:[^()]|\([^()]*\))*\)", re.IGNORECASE)


@dataclass(frozen=True)
class FilterResult:
    text: str
    findings: tuple[str, ...]  # rule names; empty when clean
    blocked: bool  # True → text was replaced by the safe fallback


def _leaked_prompt_lines(answer: str, system_prompts: Iterable[str]) -> list[str]:
    flat_answer = " ".join(answer.split()).lower()
    leaks: list[str] = []
    for prompt in system_prompts:
        for line in prompt.splitlines():
            flat = " ".join(line.split()).lower().lstrip("- ")
            if len(flat) >= MIN_LEAK_LINE_CHARS and flat in flat_answer:
                leaks.append(flat[:60])
    return leaks


def filter_output(answer: str, system_prompts: Iterable[str]) -> FilterResult:
    findings = [name for name, pattern in _SECRETS if pattern.search(answer)]
    if _leaked_prompt_lines(answer, system_prompts):
        findings.append("system_prompt_leak")
    if findings:
        return FilterResult(SAFE_FALLBACK, tuple(findings), blocked=True)
    sanitised = _JS_LINK.sub("](#)", answer)
    if sanitised != answer:
        return FilterResult(sanitised, ("unsafe_link",), blocked=False)
    return FilterResult(answer, (), blocked=False)
