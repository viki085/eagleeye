import io
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.services.artifact_reader import csv_lines, page, safe_cell
from fastapi.testclient import TestClient

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")
ART = str(uuid.uuid4())


def _parquet(n: int = 120) -> bytes:
    buf = io.BytesIO()
    pq.write_table(
        pa.table({"channel": [f"c{i}" for i in range(n)], "orders": list(range(n))}), buf
    )
    return buf.getvalue()


class FakePool:
    def __init__(self, owner: str) -> None:
        self.owner = owner

    async def fetchrow(self, sql, artifact_id, user_id):  # noqa: ANN001, ANN201
        if user_id != self.owner:
            return None
        return {
            "id": artifact_id,
            "title": "Orders by channel",
            "s3_key": "k",
            "columns": [],
            "row_count": 120,
            "truncated": False,
            "source_refs": {"sql": "SELECT 1"},
            "created_at": None,
        }


class FakeStore:
    async def get(self, key):  # noqa: ANN001, ANN201
        return _parquet()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.pool = FakePool(ME.id)
    app.state.artifact_store = FakeStore()
    return TestClient(app)


def test_paging(client: TestClient) -> None:
    data = client.get(f"/v1/artifacts/{ART}?offset=100&limit=50").json()["data"]
    assert data["total"] == 120 and len(data["rows"]) == 20 and data["rows"][0] == ["c100", 100]
    assert data["sql"] == "SELECT 1"


def test_double_encoded_source_refs_are_tolerated() -> None:
    from app.routers.artifacts import _as_dict

    assert _as_dict('{"sql": "SELECT 1"}') == {"sql": "SELECT 1"}
    assert _as_dict({"sql": "x"}) == {"sql": "x"}
    assert _as_dict("not json") == {} and _as_dict(None) == {}


def test_page_limit_bounded(client: TestClient) -> None:
    assert client.get(f"/v1/artifacts/{ART}?limit=5000").status_code == 422


def test_other_users_artifact_is_404(client: TestClient) -> None:
    client.app.state.pool = FakePool("someone-else")
    assert client.get(f"/v1/artifacts/{ART}").status_code == 404
    assert client.get(f"/v1/artifacts/{ART}/csv").status_code == 404


def test_csv_download(client: TestClient) -> None:
    resp = client.get(f"/v1/artifacts/{ART}/csv")
    assert (
        resp.status_code == 200 and "Orders_by_channel.csv" in resp.headers["content-disposition"]
    )
    lines = resp.text.strip().splitlines()
    assert lines[0] == "channel,orders" and len(lines) == 121


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('=HYPERLINK("x")', '\'=HYPERLINK("x")'),
        ("+1", "'+1"),
        ("-2", "'-2"),
        ("@SUM", "'@SUM"),
        ("normal", "normal"),
        (None, ""),
        (5, "5"),
    ],
)
def test_formula_injection_escaped(value, expected: str) -> None:  # noqa: ANN001
    assert safe_cell(value) == expected


def test_page_and_csv_helpers() -> None:
    table = pa.table({"a": [1, 2, 3]})
    assert page(table, 2, 10).rows == [[3]]
    assert page(table, 99, 10).rows == []
    assert "".join(csv_lines(table)).splitlines() == ["a", "1", "2", "3"]
