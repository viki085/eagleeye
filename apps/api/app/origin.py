"""The API behind CloudFront (Phase 7B demo machine).

The machine's firewall admits only CloudFront's address ranges, but every CloudFront
distribution shares them. CloudFront therefore adds a secret header (ORIGIN_VERIFY_SECRET) to
every request it forwards, and anything without it is refused. On those verified requests the
visitor's address is taken from CloudFront-Viewer-Address, which CloudFront sets itself; a
client-sent X-Forwarded-For is never used. Off when no secret is configured (the laptop).
"""

import hmac
import ipaddress
import json

from starlette.types import ASGIApp, Receive, Scope, Send

SECRET_HEADER = b"x-origin-verify"
VIEWER_HEADER = b"cloudfront-viewer-address"
UNGUARDED = ("/v1/health/live",)  # the container's own health check, from inside the machine


def viewer_ip(value: str) -> tuple[str, int] | None:
    """'198.51.100.10:46532' or '2001:db8::1:443' (IPv6 is not bracketed) → (ip, port)."""
    host, _, port = value.rpartition(":")
    try:
        return str(ipaddress.ip_address(host)), int(port)
    except ValueError:
        return None


class OriginGuardMiddleware:
    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self._secret = secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._secret or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope.get("path") in UNGUARDED:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        if not hmac.compare_digest(headers.get(SECRET_HEADER, b""), self._secret):
            await _refuse(scope, send)
            return
        viewer = viewer_ip(headers.get(VIEWER_HEADER, b"").decode("latin-1"))
        if viewer is not None:
            scope = {**scope, "client": viewer}
        await self.app(scope, receive, send)


async def _refuse(scope: Scope, send: Send) -> None:
    if scope["type"] != "http":
        await send({"type": "websocket.close", "code": 1008})
        return
    body = json.dumps(
        {"success": False, "data": None, "error": {"code": "FORBIDDEN", "message": "Forbidden"}}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
