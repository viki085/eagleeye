"""Compact, DDL-like schema text for the SQL generation prompt (≈ 1–4k tokens)."""

from eagleeye_catalog.models import ColumnInfo, SchemaContext, TableInfo

MAX_CHARS = 16_000  # ≈ 4k tokens
MAX_EXAMPLE_CHARS = 4_000  # example queries help but never crowd out tables


def _column_line(c: ColumnInfo, can_see_pii: bool, compact: bool = False) -> str:
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
    if compact:
        return line
    if c.description:
        line += f" — {c.description}"
    if c.sample_values and not c.pii:
        line += f" (e.g. {', '.join(c.sample_values[:8])})"
    return line


def render_table(t: TableInfo, can_see_pii: bool, compact: bool = False) -> str:
    """`compact`: column names, types and keys only (no descriptions or sample values)."""
    rows = f" (≈{t.row_estimate:,} rows)" if t.row_estimate else ""
    head = f"TABLE {t.key}{rows}" + (f" — {t.description}" if t.description else "")
    return "\n".join([head, *(_column_line(c, can_see_pii, compact) for c in t.columns)])


def _examples(ctx: SchemaContext) -> str:
    kept: list[str] = []
    size = 0
    for e in ctx.examples:
        text = f"-- Q: {e.question}\n{e.sql.strip()}"
        if kept and size + len(text) > MAX_EXAMPLE_CHARS:
            break
        kept.append(text)
        size += len(text) + 2
    return "EXAMPLE QUERIES\n" + "\n\n".join(kept) if kept else ""


def _tables(ctx: SchemaContext, budget: int) -> tuple[list[str], list[str]]:
    """Tables in relevance order, whole: full, else compact, else left out (never cut mid-way)."""
    shown: list[str] = []
    omitted: list[str] = []
    used = 0
    for t in ctx.tables:
        for text in (render_table(t, ctx.can_see_pii), render_table(t, ctx.can_see_pii, True)):
            if used + len(text) + 2 <= budget:
                shown.append(text)
                used += len(text) + 2
                break
        else:
            omitted.append(t.key)
    return shown, omitted


def render_context(ctx: SchemaContext) -> str:
    """Within MAX_CHARS. The business definitions are always kept (a cut at the end used to drop
    them, and the SQL writer then refused: "the official on-time definition is truncated");
    tables are kept whole in relevance order, shortened, or left out and named."""
    head = f"Database: {ctx.source.name} ({ctx.source.engine}). {ctx.source.description}"
    definitions = (
        "BUSINESS DEFINITIONS\n"
        + "\n".join(f"- {m.name}: {m.description} = {m.definition_sql}" for m in ctx.metrics)
        if ctx.metrics
        else ""
    )
    fixed = [x for x in (definitions, _examples(ctx)) if x]
    budget = MAX_CHARS - len(head) - sum(len(x) + 2 for x in fixed) - 300
    tables, omitted = _tables(ctx, budget)
    if not tables and ctx.tables:  # one table bigger than everything: its start still helps
        tables = [render_table(ctx.tables[0], ctx.can_see_pii, True)[: max(budget, 1000)]]
        omitted = [t.key for t in ctx.tables[1:]]
    note = (
        [f"(Left out for length; ask about them in a separate question: {', '.join(omitted)})"]
        if omitted
        else []
    )
    text = "\n\n".join([head, *tables, *note, *fixed])
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n… (schema truncated)"
