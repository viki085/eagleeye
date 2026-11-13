"""Compact text of a profile for prompts and tool results (never raw rows beyond the sample)."""

from typing import Any

MAX_DIGEST_CHARS = 6000


def _column_line(c: dict[str, Any]) -> str:
    parts = [f"null {c['null_pct']}%", f"distinct {c['distinct']}"]
    if c["kind"] == "numeric":
        parts.append(
            f"min {c.get('min')}, max {c.get('max')}, mean {c.get('mean')}, "
            f"median {c.get('median')}, std {c.get('std')}"
        )
        if c.get("outliers"):
            parts.append(f"{c['outliers']} outliers (IQR)")
    elif c["kind"] == "temporal":
        parts.append(f"from {c.get('min')} to {c.get('max')}")
    if c.get("top"):
        parts.append("top: " + ", ".join(f"{t['value']} ({t['count']})" for t in c["top"]))
    flags = f" [{', '.join(c['flags'])}]" if c.get("flags") else ""
    return f"- {c['name']} ({c['type']}): {'; '.join(parts)}{flags}"


def schema_line(columns: list[dict[str, str]] | tuple[dict[str, str], ...]) -> str:
    return ", ".join(f"{c['name']} {c['type']}" for c in columns)


def profile_digest(title: str, profile: dict[str, Any], with_sample: bool = False) -> str:
    if not profile:
        return f"Dataset '{title}': no profile available."
    lines = [
        f"Dataset '{title}': {profile['row_count']:,} rows × {profile['column_count']} columns; "
        f"{profile['duplicate_rows']:,} duplicated rows.",
        "COLUMNS",
        *(_column_line(c) for c in profile["columns"]),
    ]
    if profile.get("correlations"):
        lines.append("STRONGEST CORRELATIONS (Pearson r)")
        lines += [f"- {c['a']} ~ {c['b']}: {c['r']}" for c in profile["correlations"]]
    if profile.get("warnings"):
        lines.append("DATA QUALITY")
        lines += [f"- {w}" for w in profile["warnings"]]
    if with_sample and profile.get("sample", {}).get("rows"):
        sample = profile["sample"]
        lines.append("SAMPLE ROWS (*** = personal data, hidden)")
        lines.append(" | ".join(sample["columns"]))
        lines += [" | ".join("" if v is None else str(v) for v in r) for r in sample["rows"][:5]]
    text = "\n".join(lines)
    return text if len(text) <= MAX_DIGEST_CHARS else text[:MAX_DIGEST_CHARS] + "\n… (truncated)"
