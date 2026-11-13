from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    description: str = ""
    is_pk: bool = False
    fk_ref: str | None = None  # "schema.table.column"
    pii: bool = False
    sample_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableInfo:
    schema: str
    name: str
    columns: tuple[ColumnInfo, ...]
    description: str = ""
    row_estimate: int | None = None
    sensitivity: str = "internal"
    enabled: bool = False

    @property
    def key(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    definition_sql: str


@dataclass(frozen=True)
class Example:
    question: str
    sql: str


@dataclass(frozen=True)
class Grant:
    role: str
    allowed_tables: tuple[str, ...] | None  # None = every enabled table
    can_see_pii: bool


@dataclass(frozen=True)
class SourceInfo:
    id: str
    name: str
    description: str
    engine: str
    dsn_env: str
    max_rows: int = 10_000
    timeout_s: int = 15
    schema_version: int = 0


@dataclass(frozen=True)
class SchemaContext:
    """What the SQL agent sees for one question: only granted tables, ranked by relevance."""

    source: SourceInfo
    tables: tuple[TableInfo, ...]
    metrics: tuple[Metric, ...] = ()
    examples: tuple[Example, ...] = ()
    can_see_pii: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)
