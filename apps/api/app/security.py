"""Response hardening: security headers and a size limit on JSON request bodies."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.request_context import current_request_id

MAX_JSON_BODY_BYTES = 64 * 1024
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in SECURITY_HEADERS if k not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class JsonBodyLimitMiddleware:
    """Refuses JSON bodies over 64 KB before they are read (uploads keep their own limit)."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_JSON_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        content_type = headers.get(b"content-type", b"").decode().lower()
        length = headers.get(b"content-length", b"").decode()
        if "multipart/form-data" not in content_type and length.isdigit():
            if int(length) > self.max_bytes:
                await _too_large(send)
                return
        await self.app(scope, receive, send)


class UnhandledErrorMiddleware:
    """Turns a crash into the standard 500 envelope INSIDE the CORS layer, so the browser
    receives a readable error (with request id) instead of an opaque CORS failure. Starlette's
    own catch-all runs outside CORS and stays as the last resort."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            import logging

            logging.getLogger("app.errors").exception(
                "unhandled error on %s %s", scope.get("method"), scope.get("path")
            )
            if started:  # a streaming response already began; nothing safe to send
                return
            await _send_json(send, 500, "INTERNAL_ERROR", INTERNAL_ERROR_MESSAGE)


INTERNAL_ERROR_MESSAGE = (
    "Something went wrong. Try again, and quote the request id if it keeps happening."
)


async def _send_json(send: Send, status: int, code: str, message: str) -> None:
    import json

    request_id = current_request_id()
    body = json.dumps(
        {
            "success": False,
            "data": None,
            "error": {"code": code, "message": message, "request_id": request_id},
            "meta": None,
        }
    ).encode()
    # x-request-id is added by the (outer) RequestIdMiddleware
    headers = [(b"content-type", b"application/json"), *SECURITY_HEADERS]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _too_large(send: Send) -> None:
    import json

    body = json.dumps(
        {
            "success": False,
            "data": None,
            "error": {
                "code": "PAYLOAD_TOO_LARGE",
                "message": "The request is too large.",
                "request_id": current_request_id(),
            },
            "meta": None,
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), *SECURITY_HEADERS],
        }
    )
    await send({"type": "http.response.body", "body": body})
