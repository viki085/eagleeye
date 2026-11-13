import datetime as dt
import io
from decimal import Decimal

import pyarrow.parquet as pq
import pytest
from eagleeye_catalog.models import ColumnInfo, Grant, SourceInfo, TableInfo
from eagleeye_catalog.service import CatalogService
from eagleeye_core.service_auth import ContextToken
from gateway import service as gw
from gateway.artifacts import to_parquet
from gateway.executor import QueryResult, _max_plan_rows, jsonable, unique_names

SOURCE = SourceInfo("s1", "acme", "", "postgres", "WAREHOUSE_DSN", max_rows=100)
TABLES = [
    TableInfo(
        "sales",
        "orders",
        (ColumnInfo("order_id", "integer"), ColumnInfo("status", "text")),
        enabled=True,
    ),
    TableInfo(
        "sales",
        "customers",
        (ColumnInfo("customer_id", "integer"), ColumnInfo("email", "text", pii=True)),
        enabled=True,
    ),
]


def test_unique_names_and_jsonable() -> None:
    assert unique_names(["count", "count", "x"]) == ["count", "count_2", "x"]
    assert jsonable(Decimal("1.50")) == 1.5
    assert jsonable(dt.date(2026, 1, 2)) == "2026-01-02"
    assert jsonable(b"\x00") == "<binary>"


def test_max_plan_rows_walks_children() -> None:
    plan = {"Plan Rows": 10, "Plans": [{"Plan Rows": 5}, {"Plan Rows": 900, "Plans": []}]}
    assert _max_plan_rows(plan) == 900


def test_parquet_round_trip_with_mixed_types() -> None:
    result = QueryResult(
        (("n", "int4"), ("amt", "numeric"), ("d", "date")),
        [(1, Decimal("2.50"), dt.date(2026, 1, 1)), (2, None, None)],
        False,
        3,
    )
    table = pq.read_table(io.BytesIO(to_parquet(result)))
    assert table.num_rows == 2 and table.column_names == ["n", "amt", "d"]


class FakeStore:
    async def get_source(self, source_id):  # noqa: ANN001, ANN201
        return SOURCE if source_id == "s1" else None

    async def get_grant(self, source_id, role):  # noqa: ANN001, ANN201
        return {"member": Grant("member", None, False), "admin": Grant("admin", None, True)}.get(
            role
        )

    async def load_tables(self, source_id):  # noqa: ANN001, ANN201
        return TABLES


class FakePool:
    def __init__(self, role: str | None) -> None:
        self.role = role
        self.logged: list[tuple] = []

    async def fetchrow(self, sql, *args):  # noqa: ANN001, ANN201
        return None if self.role is None else {"role": self.role, "status": "active"}

    async def execute(self, sql, *args):  # noqa: ANN001, ANN201
        self.logged.append(args)


@pytest.fixture
def deps_for(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    executed: list[str] = []

    async def fake_run(deps, source, sql, max_rows, log):  # noqa: ANN001
        executed.append(sql)
        return QueryResult((("status", "text"), ("n", "int8")), [("completed", 5)], False, 4)

    async def fake_save(store, pool, **kw):  # noqa: ANN001, ANN003
        return "art-1"

    monkeypatch.setattr(gw, "_run", fake_run)
    monkeypatch.setattr(gw, "save_artifact", fake_save)

    def make(role: str | None) -> tuple[gw.GatewayDeps, FakePool, list[str]]:
        pool = FakePool(role)
        deps = gw.GatewayDeps(pool, CatalogService(FakeStore()), None, None, 1000)  # type: ignore[arg-type]
        return deps, pool, executed

    return make


TOKEN = ContextToken("u1", "s1", "r1", 9999999999)


async def test_valid_query_returns_preview_and_audits(deps_for) -> None:  # noqa: ANN001
    deps, pool, executed = deps_for("member")
    out = await gw.execute(deps, TOKEN, "SELECT status, COUNT(*) AS n FROM orders GROUP BY 1", "t")
    assert out["ok"] and out["artifact_id"] == "art-1" and out["preview"] == [["completed", 5]]
    assert "LIMIT 101" in executed[0]  # max_rows + 1 to detect truncation
    assert pool.logged[-1][7] is True  # validated=True


async def test_role_comes_from_db_not_token(deps_for) -> None:  # noqa: ANN001
    deps, _, _ = deps_for(None)
    with pytest.raises(gw.GatewayError) as exc:
        await gw.execute(deps, TOKEN, "SELECT 1 FROM orders", "t")
    assert exc.value.status == 403


async def test_no_grant_is_403(deps_for) -> None:  # noqa: ANN001
    deps, _, _ = deps_for("knowledge_admin")
    with pytest.raises(gw.GatewayError) as exc:
        await gw.execute(deps, TOKEN, "SELECT 1 FROM orders", "t")
    assert exc.value.code == "NO_ACCESS"


async def test_rejection_is_logged_and_retryable(deps_for) -> None:  # noqa: ANN001
    deps, pool, executed = deps_for("member")
    with pytest.raises(gw.GatewayError) as exc:
        await gw.execute(deps, TOKEN, "SELECT email FROM customers", "t")
    assert exc.value.code == "COLUMN_RESTRICTED" and exc.value.retryable
    assert executed == [] and pool.logged[-1][7] is False


async def test_pii_allowed_for_admin(deps_for) -> None:  # noqa: ANN001
    deps, _, executed = deps_for("admin")
    await gw.execute(deps, TOKEN, "SELECT email FROM customers", "t")
    assert "email" in executed[-1]
