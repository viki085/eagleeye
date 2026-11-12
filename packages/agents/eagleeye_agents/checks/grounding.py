"""Citation grounding (C3 §2.5): every [n] must map to a source this run retrieved."""

import re
from dataclasses import dataclass

from eagleeye_agents.sources import SourceRegistry, strip_invalid_markers

_NOT_FOUND = re.compile(
    r"\b(couldn'?t|could not|can'?t|cannot|unable to|don'?t|do not|does not|doesn'?t|no)\b.{0,40}"
    r"\b(find|found|contain|cover|information|mention|answer)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GroundingResult:
    text: str  # answer with invalid markers removed
    changed: bool
    cited: int
    uncited_grounded: bool  # expected citations, found none, and no "not found" statement


def check_grounding(answer: str, sources: SourceRegistry, expected: bool) -> GroundingResult:
    cleaned = strip_invalid_markers(answer, sources.numbers)
    cited = len(sources.citations_for(cleaned))
    uncited = expected and len(sources) > 0 and cited == 0 and not _NOT_FOUND.search(cleaned)
    return GroundingResult(cleaned, cleaned != answer, cited, uncited)
