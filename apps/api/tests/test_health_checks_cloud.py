"""Health checks with cloud settings (Phase 7B): Qdrant Cloud needs its key; on AWS the object
store has no endpoint (the machine's role is used), so it is checked through the S3 client."""

import asyncio

import httpx
import pytest
from app.services import health_checks as hc
from eagleeye_core.config import Settings


def settings(**kw: object) -> Settings:
    base = {"s3_access_key": "", "s3_secret_key": ""}
    return Settings(_env_file=None, **{**base, **kw})


def test_qdrant_check_sends_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("api-key")
        return httpx.Response(200 if seen["key"] == "k-123" else 401)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        hc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(
        hc, "get_settings", lambda: settings(qdrant_url="https://q:6333", qdrant_api_key="k-123")
    )
    assert asyncio.run(hc._check_qdrant()).status == "up" and seen["key"] == "k-123"


def test_qdrant_check_sends_no_key_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["has_key"] = "api-key" in request.headers
        return httpx.Response(200)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        hc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(hc, "get_settings", lambda: settings(qdrant_url="http://localhost:6333"))
    assert asyncio.run(hc._check_qdrant()).status == "up" and seen["has_key"] is False


class FakeStore:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def reachable(self) -> None:
        if self.fail:
            raise OSError("no route")


def test_aws_object_store_is_checked_through_the_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hc, "get_settings", lambda: settings(s3_endpoint_url=""))
    monkeypatch.setattr(hc, "_aws_store", lambda s: FakeStore())
    assert asyncio.run(hc._check_object_store()).status == "up"
    monkeypatch.setattr(hc, "_aws_store", lambda s: FakeStore(fail=True))
    down = asyncio.run(hc._check_object_store())
    assert down.status == "down" and down.detail == "OSError"


def test_the_real_aws_store_is_built_once_per_bucket() -> None:
    s = settings(s3_endpoint_url="", docs_bucket="b-1", aws_region="us-east-1")
    assert hc._aws_store(s) is hc._aws_store(s)
