from dataclasses import asdict, dataclass
from typing import Literal

Safety = Literal["allowed", "harmful", "prompt_injection", "sensitive_exfiltration", "uncertain"]
Intent = Literal["chitchat", "docs", "sql", "analysis", "mixed", "other"]
Complexity = Literal["simple", "complex", "uncertain"]
VerdictSource = Literal["rules", "llm", "error"]


@dataclass(frozen=True)
class GuardVerdict:
    safe: Safety
    intent: Intent
    complexity: Complexity
    source: VerdictSource
    detail: str = ""  # rule name / error class — logged, never shown to the user

    @property
    def allowed(self) -> bool:
        return self.safe == "allowed"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def unavailable(detail: str) -> GuardVerdict:
    """Fail closed: an unclassifiable message is treated as not allowed."""
    return GuardVerdict("uncertain", "other", "uncertain", "error", detail)
