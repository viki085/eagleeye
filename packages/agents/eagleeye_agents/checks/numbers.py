"""Numeric grounding (C3 §2.5): figures in the answer must appear in what the model was given
(query results, retrieved passages, the question). Unmatched figures are flagged, not removed.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

_CITATION = re.compile(r"\[\d{1,3}(?:\s*,\s*\d{1,3})*\]")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b")
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
# "November 13, 2026", "Nov 13th", "13 November 2026", "13th of Nov" — the day of a written
# date is not a figure (regression: "November 13" was flagged as an unverified number)
_WORD_DATE = re.compile(
    rf"\b(?:{_MONTH}\s+{_DAY}(?:,?\s+\d{{4}})?|{_DAY}\s+(?:of\s+)?{_MONTH}(?:,?\s+\d{{4}})?)\b",
    re.IGNORECASE,
)
# Conventional statistical constants are not data: "95% confidence interval", "at the 0.05
# level", "α = 0.05", "p < 0.05" (the p-VALUE itself is still checked when written p = 0.444).
_STAT_CONSTANT = re.compile(
    r"\b(?:90|95|99)(?:\.0)?\s*%\s*(?:confidence|CI\b|credible)"
    r"|(?:α|alpha|significance(?:\s+level)?)\s*(?:=|of|at)?\s*0?\.(?:10|05|01|001)\b"
    r"|\b(?:at|below|under)\s+(?:the\s+)?0?\.(?:10|05|01|001)\s+(?:level|threshold|cut-?off)"
    r"|\bp\s*[<>≤≥]\s*0?\.(?:10|05|01|001)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?<![\w.])([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(%|percent\b|k\b|m\b|bn\b|b\b|thousand\b|million\b|billion\b)?",
    re.IGNORECASE,
)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
SMALL_INT_MAX = 12  # list numbering, months, "top 5" — too ambiguous to check
RELATIVE_TOLERANCE = 0.005


@dataclass(frozen=True)
class Figure:
    text: str
    value: float
    decimals: int
    percent: bool
    scale: float


def extract_figures(text: str) -> list[Figure]:
    clean = _WORD_DATE.sub(" ", _DATE.sub(" ", _CITATION.sub(" ", text)))
    clean = _STAT_CONSTANT.sub(" ", clean)
    figures: list[Figure] = []
    for match in _NUMBER.finditer(clean):
        raw, unit = match.group(1), (match.group(2) or "").lower()
        number = raw.replace(",", "")
        decimals = len(number.split(".")[1]) if "." in number else 0
        figures.append(
            Figure(
                match.group(0).strip(),
                float(number),
                decimals,
                unit in ("%", "percent"),
                _SCALE.get(unit, 1.0),
            )
        )
    return figures


def numbers_in(values: Iterable[object]) -> list[float]:
    out: list[float] = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float):
            out.append(float(v))
        elif isinstance(v, str):
            out.extend(f.value * f.scale for f in extract_figures(v))
    return out


def _ignorable(f: Figure, question_values: set[float]) -> bool:
    if f.value in question_values:
        return True
    is_int = f.decimals == 0 and f.scale == 1.0 and not f.percent
    if is_int and abs(f.value) <= SMALL_INT_MAX:
        return True
    return is_int and 1900 <= f.value <= 2100  # years


def _matches(f: Figure, evidence: list[float]) -> bool:
    value = f.value * f.scale
    rounding = 0.5 * (10**-f.decimals) * f.scale
    candidates = [value, value / 100] if f.percent else [value]
    for e in evidence:
        for c in candidates:
            # magnitudes, not signs: "below target by €90,380.83" and "−€90,380.83" both
            # quote a gap of -90380.83; the check guards against invented figures
            target = abs(e)
            tol = max(rounding if c is value else rounding / 100, target * RELATIVE_TOLERANCE)
            if abs(abs(c) - target) <= tol:
                return True
    return False


def unverified_figures(answer: str, evidence: list[float], question: str) -> list[str]:
    question_values = {f.value for f in extract_figures(question)}
    return [
        f.text
        for f in extract_figures(answer)
        if not _ignorable(f, question_values) and not _matches(f, evidence)
    ]
