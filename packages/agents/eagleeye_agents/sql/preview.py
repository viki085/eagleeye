"""What the MODEL sees of a result: ≤ 50 rows, PII masked, long cells clipped (C5 §6).

The user sees real values in the UI (the gateway only returned what their grant allows);
the LLM provider never needs personal data to describe an aggregate.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Any

LLM_PREVIEW_ROWS = 50
MAX_CELL_CHARS = 80
MASK = "***"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.IGNORECASE)
_PHONE_CHARS = re.compile(r"^\+?[\d\s().-]+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
MIN_PHONE_DIGITS = 9


def looks_like_phone(text: str) -> bool:
    """Phone-shaped: only phone characters and ≥ 9 digits — but never an ISO date/time."""
    s = text.strip()
    if _ISO_DATE.match(s) or not _PHONE_CHARS.match(s):
        return False
    return sum(ch.isdigit() for ch in s) >= MIN_PHONE_DIGITS


def _mask_cell(value: Any, pii_column: bool) -> Any:
    if value is None:
        return None
    if pii_column:
        return MASK
    if isinstance(value, str):
        if _EMAIL.search(value) or looks_like_phone(value):
            return MASK
        return value if len(value) <= MAX_CELL_CHARS else value[: MAX_CELL_CHARS - 1] + "…"
    return value


def masked_preview(
    columns: Sequence[dict[str, str]],
    rows: Iterable[Sequence[Any]],
    pii_names: set[str],
    limit: int = LLM_PREVIEW_ROWS,
) -> tuple[tuple[Any, ...], ...]:
    flags = [c["name"].lower() in pii_names for c in columns]
    out = []
    for i, row in enumerate(rows):
        if i >= limit:
            break
        out.append(
            tuple(_mask_cell(v, flags[j] if j < len(flags) else False) for j, v in enumerate(row))
        )
    return tuple(out)


def format_result(
    sql: str,
    assumptions: str,
    columns: Sequence[dict[str, str]],
    rows: Sequence[Sequence[Any]],
    row_count: int,
    truncated: bool,
) -> str:
    """Compact text block for the model (pipe-separated rows)."""
    header = " | ".join(c["name"] for c in columns)
    body = "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in rows)
    shown = f"first {len(rows)} of {row_count}" if len(rows) < row_count else f"all {row_count}"
    lines = [
        f"SQL:\n{sql}",
        f"Assumptions: {assumptions or 'none'}",
        f"Rows: {row_count}{' (truncated at the row cap)' if truncated else ''} — showing {shown}",
        header,
        body or "(no rows)",
    ]
    if any(v == MASK for r in rows for v in r):
        lines.append(
            f"Note: {MASK} marks personal data hidden from you but visible to the user in the "
            "result table shown below your answer. Refer the user to that table; do not say the "
            "data is unavailable."
        )
    return "\n".join(lines)
