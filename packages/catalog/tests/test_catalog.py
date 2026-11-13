from dataclasses import replace

import pytest
from eagleeye_catalog.models import ColumnInfo, Example, Grant, Metric, SourceInfo, TableInfo
from eagleeye_catalog.policy import build_policy, granted_tables
from eagleeye_catalog.render import MAX_CHARS, render_context
from eagleeye_catalog.seed import load_seed, merge
from eagleeye_catalog.service import CatalogService

SOURCE = SourceInfo("s1", "acme", "Acme sales", "postgres", "WAREHOUSE_DSN", max_rows=500)
ORDERS = TableInfo(
    "sales",
    "orders",
    (
        ColumnInfo("order_id", "integer", is_pk=True),
        ColumnInfo("status", "text", sample_values=("completed",)),
    ),
    description="Orders",
    enabled=True,
)
CUSTOMERS = TableInfo(
    "sales",
    "customers",
    (ColumnInfo("customer_id", "integer", is_pk=True), ColumnInfo("email", "text", pii=True)),
    enabled=True,
)
DISABLED = TableInfo("sales", "secret", (ColumnInfo("x", "integer"),), enabled=False)
TABLES = [ORDERS, CUSTOMERS, DISABLED]


def test_granted_tables_respects_enabled_and_allow_list() -> None:
    assert {t.key for t in granted_tables(TABLES, Grant("member", None, False))} == {
        "sales.orders",
        "sales.customers",
    }
    only = granted_tables(TABLES, Grant("member", ("sales.orders",), False))
    assert [t.key for t in only] == ["sales.orders"]
    assert granted_tables(TABLES, None) == ()


def test_build_policy_carries_pii_and_limits() -> None:
    policy = build_policy(SOURCE, TABLES, Grant("member", None, False))
    assert set(policy.tables) == {"sales.orders", "sales.customers"}
    assert policy.tables["sales.customers"]["email"].pii is True
    assert policy.can_see_pii is False and policy.max_limit == 500
    assert build_policy(SOURCE, TABLES, Grant("admin", None, True)).can_see_pii is True


def test_seed_merge_applies_meaning_and_disables_unknown_tables() -> None:
    seed = load_seed("acme_warehouse")
    raw = [
        TableInfo(
            "sales", "customers", (ColumnInfo("email", "text"), ColumnInfo("segment", "text"))
        ),
        TableInfo("sales", "brand_new", (ColumnInfo("x", "integer"),)),
    ]
    merged = {t.key: t for t in merge(raw, seed)}
    customers = merged["sales.customers"]
    assert customers.enabled and customers.description
    assert next(c for c in customers.columns if c.name == "email").pii is True
    assert merged["sales.brand_new"].enabled is False
    assert {g.role for g in seed.grants} == {"member", "knowledge_admin", "data_admin", "admin"}


def test_render_marks_pii_and_includes_samples() -> None:
    from eagleeye_catalog.models import SchemaContext

    text = render_context(SchemaContext(SOURCE, (ORDERS, CUSTOMERS), can_see_pii=False))
    assert "TABLE sales.orders" in text and "e.g. completed" in text
    assert "[PII — not accessible]" in text


def test_samples_decode_from_list_or_json_text() -> None:
    from eagleeye_catalog.repo import _samples

    assert _samples(["a", "b"]) == ("a", "b")
    assert _samples('["consumer", "smb"]') == ("consumer", "smb")
    assert _samples("[]") == () and _samples("not json") == () and _samples(None) == ()


def test_render_tells_privileged_users_pii_is_allowed() -> None:
    from eagleeye_catalog.models import SchemaContext

    text = render_context(SchemaContext(SOURCE, (CUSTOMERS,), can_see_pii=True))
    assert "IS allowed" in text and "not accessible" not in text


def test_render_is_capped() -> None:
    from eagleeye_catalog.models import SchemaContext

    wide = replace(
        ORDERS, columns=tuple(ColumnInfo(f"c{i}", "text", "x" * 200) for i in range(200))
    )
    assert len(render_context(SchemaContext(SOURCE, (wide,)))) <= MAX_CHARS + 40


class FakeStore:
    def __init__(self, grant: Grant | None) -> None:
        self.grant = grant

    async def get_source(self, source_id):  # noqa: ANN001, ANN201
        return SOURCE if source_id == "s1" else None

    async def get_source_by_name(self, name):  # noqa: ANN001, ANN201
        return SOURCE

    async def sources_for_role(self, role):  # noqa: ANN001, ANN201
        return [(SOURCE, self.grant)] if self.grant else []

    async def get_grant(self, source_id, role):  # noqa: ANN001, ANN201
        return self.grant

    async def load_tables(self, source_id):  # noqa: ANN001, ANN201
        return TABLES

    async def table_scores(self, source_id, vector):  # noqa: ANN001, ANN201
        return {}

    async def top_metrics(self, source_id, vector, k):  # noqa: ANN001, ANN201
        return [
            Metric("order count", "orders", "COUNT(*) FROM sales.orders"),
            Metric("salary", "hidden", "AVG(salary) FROM sales.secret"),
        ]

    async def top_examples(self, source_id, vector, k):  # noqa: ANN001, ANN201
        return [
            Example("orders by status", "SELECT status, COUNT(*) FROM sales.orders GROUP BY 1"),
            Example("emails", "SELECT email FROM sales.customers"),  # PII → filtered for member
            Example("secret", "SELECT x FROM sales.secret"),  # disabled table → filtered
        ]


class FakeEmbedder:
    dim = 3

    async def embed(self, texts):  # noqa: ANN001, ANN201
        return [[0.1, 0.2, 0.3] for _ in texts]


async def test_no_grant_means_no_access() -> None:
    svc = CatalogService(FakeStore(None))
    assert await svc.access("s1", "member") is None
    assert await svc.accessible_sources("member") == []


async def test_schema_context_filters_examples_and_metrics_by_policy() -> None:
    svc = CatalogService(FakeStore(Grant("member", None, False)), FakeEmbedder())
    acc = await svc.access("s1", "member")
    assert acc is not None
    ctx = await svc.schema_context(acc, "orders by status")
    assert [e.question for e in ctx.examples] == ["orders by status"]
    assert [m.name for m in ctx.metrics] == ["order count"]
    assert {t.key for t in ctx.tables} == {"sales.orders", "sales.customers"}


async def test_resolve_source_by_name_or_single() -> None:
    svc = CatalogService(FakeStore(Grant("member", None, False)))
    assert (await svc.resolve_source("member", None)).source.name == "acme"
    assert await svc.resolve_source("member", "other") is None


class DraftLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply

    async def complete(self, tier, messages, max_tokens=1024, json_mode=False, temperature=None):  # noqa: ANN001, ANN201
        if isinstance(self.reply, Exception):
            raise self.reply
        from eagleeye_llm.gateway import Usage

        return self.reply, Usage()


async def test_draft_fills_only_missing_descriptions() -> None:
    from eagleeye_catalog.describe import draft_description, needs_description

    t = TableInfo("sales", "t", (ColumnInfo("a", "int", "kept"), ColumnInfo("b", "int")))
    assert needs_description(t)
    out = await draft_description(
        DraftLLM('{"table": "One row per thing", "columns": {"a": "new", "b": "drafted"}}'), t
    )
    assert out.description == "One row per thing"
    assert [c.description for c in out.columns] == ["kept", "drafted"]
    same = await draft_description(DraftLLM(RuntimeError("down")), t)
    assert same == t


@pytest.mark.parametrize("role_pii", [True, False])
async def test_access_policy_matches_grant(role_pii: bool) -> None:
    svc = CatalogService(FakeStore(Grant("x", None, role_pii)))
    acc = await svc.access("s1", "x")
    assert acc is not None and acc.policy.can_see_pii is role_pii
