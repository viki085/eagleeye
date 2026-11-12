from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.health_checks import ServiceHealth


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_live_returns_up(client: TestClient) -> None:
    resp = client.get("/v1/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "up"
    assert body["error"] is None


def test_health_all_up(client: TestClient) -> None:
    services = [
        ServiceHealth("redis", "up", 2),
        ServiceHealth("qdrant", "up", 3),
        ServiceHealth("minio", "up", 4),
        ServiceHealth("supabase-pg", "up", 5),
    ]
    with patch("app.routers.health.check_all", new=AsyncMock(return_value=services)):
        resp = client.get("/v1/health")
    body = resp.json()
    assert resp.status_code == 200
    assert body["data"]["overall"] == "up"
    assert len(body["data"]["services"]) == 4


def test_health_degraded_when_any_service_down(client: TestClient) -> None:
    services = [
        ServiceHealth("redis", "up", 2),
        ServiceHealth("qdrant", "down", detail="ConnectError"),
    ]
    with patch("app.routers.health.check_all", new=AsyncMock(return_value=services)):
        resp = client.get("/v1/health")
    body = resp.json()
    assert body["data"]["overall"] == "degraded"
    assert body["data"]["services"][1]["status"] == "down"


def test_envelope_shape(client: TestClient) -> None:
    resp = client.get("/v1/health/live")
    body = resp.json()
    assert set(body.keys()) == {"success", "data", "error", "meta"}
