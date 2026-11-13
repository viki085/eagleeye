import io
import uuid
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from fastapi.testclient import TestClient

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")
OTHER = str(uuid.uuid4())


def _parquet(n: int = 75) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table({"month": list(range(n)), "target": [i * 10 for i in range(n)]}), buf)
    return buf.getvalue()


def _row(dataset_id: str, owner: str, **kw: object) -> dict:
    base = {
        "id": dataset_id,
        "owner_id": owner,
        "origin": "csv_upload",
        "title": "targets",
        "filename": "targets.csv",
        "sheet": "",
        "s3_key_original": f"datasets/{owner}/o.csv",
        "s3_key": f"datasets/{owner}/{dataset_id}/data.parquet",
        "status": "READY",
        "error": None,
        "columns": [{"name": "month", "type": "BIGINT"}],
        "column_map": {},
        "row_count": 75,
        "size_bytes": 10,
        "sha256": "abc",
        "profile": {"row_count": 75},
        "summary": "",
        "created_at": datetime(2026, 11, 13, tzinfo=UTC),
    }
    return {**base, **kw}


class FakePool:
    """Just enough of asyncpg for DatasetRepo + the router's own queries."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.deleted: list[str] = []

    async def fetchrow(self, sql: str, dataset_id: str, owner: str | None = None):  # noqa: ANN201
        row = self.rows.get(dataset_id)
        return row if row and (owner is None or row["owner_id"] == owner) else None

    async def fetch(self, sql: str, owner: str, ready_only: bool):  # noqa: ANN201
        return [r for r in self.rows.values() if r["owner_id"] == owner]

    async def fetchval(self, sql: str, *args: object):  # noqa: ANN201
        if "sha256" in sql:
            owner, sha = args
            hit = [r for r in self.rows.values() if r["owner_id"] == owner and r["sha256"] == sha]
            return hit[0]["title"] if hit else None
        return None  # original no longer used

    async def execute(self, sql: str, *args: object) -> str:
        if sql.lstrip().startswith("INSERT"):
            dataset_id, owner, origin, title, filename, sheet, key, size, sha = args
            self.rows[dataset_id] = _row(
                dataset_id,
                owner,
                origin=origin,
                title=title,
                filename=filename,
                sheet=sheet,
                s3_key_original=key,
                s3_key="",
                size_bytes=size,
                sha256=sha,
                status="UPLOADED",
                columns=[],
                row_count=0,
                profile={},
            )
            return "INSERT 0 1"
        if sql.lstrip().startswith("DELETE"):
            dataset_id = args[0]
            self.deleted.append(dataset_id)
            self.rows.pop(dataset_id, None)
            return "DELETE 1"
        dataset_id, status, error = args
        self.rows[dataset_id].update(status=status, error=error)
        return "UPDATE 1"


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.removed: list[str] = []

    async def put(self, key: str, data: bytes, mime: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        return _parquet()

    async def delete(self, key: str) -> None:
        self.removed.append(key)


class FakeQueue:
    def __init__(self) -> None:
        self.datasets: list[str] = []

    async def enqueue_dataset(self, dataset_id: str) -> None:
        self.datasets.append(dataset_id)


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.pool = FakePool()
    app.state.store = FakeStore()
    app.state.task_queue = FakeQueue()
    return TestClient(app)


def _upload(client: TestClient, name: str = "targets.csv", body: bytes = b"a,b\n1,2\n"):  # noqa: ANN202
    return client.post("/v1/datasets", files={"file": (name, body, "text/csv")})


def test_upload_stores_original_and_enqueues_profiling(client: TestClient) -> None:
    resp = _upload(client)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "UPLOADED" and data["title"] == "targets"
    assert "sha256" not in data and "s3_key_original" not in data
    assert client.app.state.task_queue.datasets == [data["id"]]
    (key,) = client.app.state.store.objects
    assert key == f"datasets/{ME.id}/{data['id']}/original.csv"  # never the user's filename


@pytest.mark.parametrize("name", ["report.pdf", "macro.xlsm", "noext", "data.xls"])
def test_unsupported_types_are_rejected(client: TestClient, name: str) -> None:
    assert _upload(client, name).status_code == 415


def test_duplicate_upload_is_409(client: TestClient) -> None:
    assert _upload(client).status_code == 201
    resp = _upload(client, "copy.csv")
    assert resp.status_code == 409 and "targets" in resp.json()["error"]["message"]


def test_other_users_dataset_is_404_everywhere(client: TestClient) -> None:
    ds = str(uuid.uuid4())
    client.app.state.pool.rows[ds] = _row(ds, OTHER)
    assert client.get(f"/v1/datasets/{ds}").status_code == 404
    assert client.get(f"/v1/datasets/{ds}/rows").status_code == 404
    assert client.delete(f"/v1/datasets/{ds}").status_code == 404
    assert client.get("/v1/datasets").json()["data"] == []
    assert client.app.state.pool.deleted == []


def test_profile_and_paged_rows(client: TestClient) -> None:
    ds = str(uuid.uuid4())
    client.app.state.pool.rows[ds] = _row(ds, ME.id)
    detail = client.get(f"/v1/datasets/{ds}").json()["data"]
    assert detail["profile"] == {"row_count": 75} and detail["column_count"] == 1
    page = client.get(f"/v1/datasets/{ds}/rows?offset=70&limit=50").json()["data"]
    assert page["total"] == 75 and len(page["rows"]) == 5 and page["rows"][0] == [70, 700]
    assert client.get(f"/v1/datasets/{ds}/rows?limit=500").status_code == 422


def test_rows_of_a_file_still_processing_is_409(client: TestClient) -> None:
    ds = str(uuid.uuid4())
    client.app.state.pool.rows[ds] = _row(ds, ME.id, status="PROFILING", s3_key="")
    assert client.get(f"/v1/datasets/{ds}/rows").status_code == 409


def test_delete_removes_row_and_objects(client: TestClient) -> None:
    ds = str(uuid.uuid4())
    row = _row(ds, ME.id)
    client.app.state.pool.rows[ds] = row
    assert client.delete(f"/v1/datasets/{ds}").json()["data"]["deleted"] is True
    assert set(client.app.state.store.removed) == {row["s3_key"], row["s3_key_original"]}
