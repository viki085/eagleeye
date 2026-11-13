from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnRule:
    data_type: str
    pii: bool = False


@dataclass(frozen=True)
class SqlPolicy:
    """What ONE user may query on ONE source. Built from grants + catalog, never from the model.

    `tables` keys are "schema.table" (lower-case); only granted, enabled tables appear.
    """

    tables: Mapping[str, Mapping[str, ColumnRule]]
    can_see_pii: bool = False
    dialect: str = "postgres"
    default_schema: str = "sales"
    default_limit: int = 10_000
    max_limit: int = 10_000
    max_sql_chars: int = 8_000
    max_selects: int = 20
    extra_functions: frozenset[str] = field(default_factory=frozenset)

    def sqlglot_schema(self) -> dict[str, dict[str, dict[str, str]]]:
        """{schema: {table: {column: type}}} for sqlglot's qualifier."""
        out: dict[str, dict[str, dict[str, str]]] = {}
        for key, columns in self.tables.items():
            schema, table = key.split(".", 1)
            out.setdefault(schema, {})[table] = {c: r.data_type for c, r in columns.items()}
        return out

    def pii_columns(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (key, column)
            for key, columns in self.tables.items()
            for column, rule in columns.items()
            if rule.pii
        )
