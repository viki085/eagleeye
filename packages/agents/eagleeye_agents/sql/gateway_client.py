"""GatewayPort + HTTP adapter. Each call carries a fresh 30 s HMAC context token."""

import logging
from typing import Protocol

import httpx
from eagleeye_core.service_auth import sign

from eagleeye_agents.sql.types import GatewayResult

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 45.0


class GatewayPort(Protocol):
    async def execute(
        self, user_id: str, run_id: str, source_id: str, sql: str, title: str
    ) -> GatewayResult: ...


class HttpGateway:
    def __init__(self, base_url: str, secret: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = base_url.rstrip("/") + "/execute"
        self._secret = secret
        self._client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S)

    async def execute(
        self, user_id: str, run_id: str, source_id: str, sql: str, title: str
    ) -> GatewayResult:
        token = sign(self._secret, user_id, source_id, run_id or None)
        try:
            resp = await self._client.post(
                self._url,
                json={"source_id": source_id, "sql": sql, "title": title},
                headers={"X-Context-Token": token},
            )
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("data gateway unreachable", exc_info=True)
            return GatewayResult(
                False, code="GATEWAY_UNAVAILABLE", error="The data gateway is unavailable."
            )
        if not data.get("ok"):
            return GatewayResult(
                False,
                code=str(data.get("code", "ERROR")),
                error=str(data.get("user_safe_error", "Query failed.")),
                retryable=bool(data.get("retryable")),
            )
        return GatewayResult(
            True,
            artifact_id=data["artifact_id"],
            sql=data["sql"],
            columns=tuple(data["columns"]),
            row_count=int(data["row_count"]),
            truncated=bool(data["truncated"]),
            preview=tuple(tuple(r) for r in data["preview"]),
            duration_ms=int(data.get("duration_ms", 0)),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
