"""Grant + catalog → SqlPolicy. Used identically by the agent worker and the data gateway."""

from collections.abc import Iterable

from eagleeye_sqlsafe.policy import ColumnRule, SqlPolicy

from eagleeye_catalog.models import Grant, SourceInfo, TableInfo


def granted_tables(tables: Iterable[TableInfo], grant: Grant | None) -> tuple[TableInfo, ...]:
    """Enabled tables the grant covers. No grant → nothing."""
    if grant is None:
        return ()
    allowed = set(grant.allowed_tables) if grant.allowed_tables is not None else None
    return tuple(t for t in tables if t.enabled and (allowed is None or t.key in allowed))


def build_policy(source: SourceInfo, tables: Iterable[TableInfo], grant: Grant | None) -> SqlPolicy:
    visible = granted_tables(tables, grant)
    return SqlPolicy(
        tables={
            t.key: {c.name: ColumnRule(c.data_type, c.pii) for c in t.columns} for t in visible
        },
        can_see_pii=bool(grant and grant.can_see_pii),
        dialect=source.engine,
        default_schema=visible[0].schema if visible else "public",
        default_limit=source.max_rows,
        max_limit=source.max_rows,
    )
