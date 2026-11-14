import uuid
from types import SimpleNamespace

from app.auth import AuthedUser, get_current_user
from app.main import create_app
from eagleeye_catalog.models import ColumnInfo, Grant, SourceInfo, TableInfo
from fastapi.testclient import TestClient

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")
CUSTOMERS = TableInfo(
    "commercial",
    "customers",
    (
        ColumnInfo("customer_id", "integer", "Customer identifier.", is_pk=True),
        ColumnInfo("contact_email", "text", "Main contact email.", pii=True),
    ),
    description="Shipper accounts.",
    row_estimate=8000,
    enabled=True,
)


class FakeCatalog:
    def __init__(self, can_see_pii: bool) -> None:
        self.grant = Grant("member", None, can_see_pii)

    async def accessible_sources(self, role: str) -> list:
        source = SourceInfo("s1", "grandline_ops", "Operations warehouse", "postgres", "DSN")
        return [SimpleNamespace(source=source, grant=self.grant, tables=(CUSTOMERS,))]


def _client(can_see_pii: bool) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.catalog = FakeCatalog(can_see_pii)
    return TestClient(app)


def test_sources_list_tables_with_their_columns() -> None:
    body = _client(can_see_pii=False).get("/v1/sources").json()["data"]
    table = body[0]["tables"][0]
    assert table["name"] == "commercial.customers" and table["row_estimate"] == 8000
    cols = {c["name"]: c for c in table["columns"]}
    assert cols["customer_id"] == {
        "name": "customer_id",
        "type": "integer",
        "description": "Customer identifier.",
        "pii": False,
        "masked": False,
    }
    assert cols["contact_email"]["pii"] is True and cols["contact_email"]["masked"] is True


def test_pii_columns_are_not_masked_for_roles_that_may_see_them() -> None:
    body = _client(can_see_pii=True).get("/v1/sources").json()["data"]
    cols = {c["name"]: c for c in body[0]["tables"][0]["columns"]}
    assert cols["contact_email"]["masked"] is False
