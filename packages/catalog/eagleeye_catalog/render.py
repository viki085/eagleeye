"""Compact, DDL-like schema text for the SQL generation prompt (≈ 1–3k tokens)."""

from eagleeye_catalog.models import ColumnInfo, SchemaContext, TableInfo

MAX_CHARS = 10_000  # ≈ 2.5k tokens


def _column_line(c: ColumnInfo, can_see_pii: bool) -> str:
    parts = [f"  {c.name} {c.data_type}"]
    if c.is_pk:
        parts.append("PK")
    if c.fk_ref:
        parts.append(f"→ {c.fk_ref}")
    if c.pii:
        parts.append(
            "[personal data — this user IS allowed to see it; include it when asked]"
            if can_see_pii
            else "[PII — not accessible]"
        )
    line = " ".join(parts)
    if c.description:
        line += f" — {c.description}"
    if c.sample_values and not c.pii:
        line += f" (e.g. {', '.join(c.sample_values[:8])})"
    return line


def render_table(t: TableInfo, can_see_pii: bool) -> str:
    rows = f" (≈{t.row_estimate:,} rows)" if t.row_estimate else ""
    head = f"TABLE {t.key}{rows}" + (f" — {t.description}" if t.description else "")
    return "\n".join([head, *(_column_line(c, can_see_pii) for c in t.columns)])


def render_context(ctx: SchemaContext) -> str:
    sections = [f"Database: {ctx.source.name} ({ctx.source.engine}). {ctx.source.description}"]
    sections += [render_table(t, ctx.can_see_pii) for t in ctx.tables]
    if ctx.metrics:
        sections.append(
            "BUSINESS DEFINITIONS\n"
            + "\n".join(f"- {m.name}: {m.description} = {m.definition_sql}" for m in ctx.metrics)
        )
    if ctx.examples:
        sections.append(
            "EXAMPLE QUERIES\n"
            + "\n\n".join(f"-- Q: {e.question}\n{e.sql.strip()}" for e in ctx.examples)
        )
    text = "\n\n".join(sections)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n… (schema truncated)"
