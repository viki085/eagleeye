"""Fakes for the SQL sub-agent: catalog with real policy building, scripted gateway."""

import json
from dataclasses import dataclass, field

from eagleeye_agents.sql.types import GatewayResult
from eagleeye_catalog.models import ColumnInfo, Grant, SchemaContext, SourceInfo, TableInfo
from eagleeye_catalog.policy import build_policy
from eagleeye_catalog.service import SourceAccess

SOURCE = SourceInfo("src-1", "grandline_ops", "Grand Line operations", "postgres", "WAREHOUSE_DSN")
TABLES = (
    TableInfo(
        "sales",
        "orders",
        (
            ColumnInfo("order_id", "integer", is_pk=True),
            ColumnInfo("channel", "text"),
            ColumnInfo("status", "text"),
        ),
        enabled=True,
    ),
    TableInfo(
        "sales",
        "customers",
        (
            ColumnInfo("customer_id", "integer", is_pk=True),
            ColumnInfo("email", "text", pii=True),
        ),
        enabled=True,
    ),
)


def draft(
    sql: str = "SELECT channel, COUNT(*) AS orders FROM sales.orders GROUP BY channel",
    clarification: str = "",
    title: str = "Orders by channel",
    unavailable: str = "",
) -> str:
    return json.dumps(
        {
            "sql": sql,
            "assumptions": "all orders",
            "clarification": clarification,
            "unavailable": unavailable,
            "title": title,
        }
    )


class FakeCatalog:
    def __init__(self, can_see_pii: bool = False) -> None:
        grant = Grant("member", None, can_see_pii)
        self.acc = SourceAccess(SOURCE, grant, TABLES, build_policy(SOURCE, TABLES, grant))

    async def resolve_source(self, role, name):  # noqa: ANN001, ANN201
        return self.acc if name in (None, SOURCE.name) else None

    async def schema_context(self, acc, question):  # noqa: ANN001, ANN201
        return SchemaContext(acc.source, acc.tables, can_see_pii=acc.grant.can_see_pii)

    async def accessible_sources(self, role):  # noqa: ANN001, ANN201
        return [self.acc]


def ok_result(
    rows: list[list] | None = None,
    columns: tuple[str, ...] = ("channel", "orders"),
    artifact_id: str = "art-1",
) -> GatewayResult:
    rows = rows if rows is not None else [["web", 20], ["store", 10]]
    return GatewayResult(
        True,
        artifact_id=artifact_id,
        sql="SELECT ... LIMIT 10001",
        columns=tuple({"name": c, "type": "text"} for c in columns),
        row_count=len(rows),
        preview=tuple(tuple(r) for r in rows),
        duration_ms=5,
    )


def db_error(msg: str = 'column "chanel" does not exist') -> GatewayResult:
    return GatewayResult(False, code="DB_ERROR", error=msg, retryable=True)


@dataclass
class FakeGateway:
    results: list[GatewayResult] = field(default_factory=lambda: [ok_result()])
    calls: list[str] = field(default_factory=list)

    async def execute(self, user_id, run_id, source_id, sql, title):  # noqa: ANN001, ANN201
        self.calls.append(sql)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def enable_sql(ctx, gateway: FakeGateway | None = None, catalog: FakeCatalog | None = None):  # noqa: ANN001, ANN201
    ctx.gateway = gateway or FakeGateway()
    ctx.catalog = catalog or FakeCatalog()
    ctx.sql_available = True
    return ctx.gateway
