"""Behind CloudFront (Phase 7B): only requests carrying CloudFront's secret header are served,
and the visitor's address comes from CloudFront-Viewer-Address, never from the client."""

import asyncio

from app.origin import OriginGuardMiddleware, viewer_ip

SECRET = "s" * 32  # noqa: S105 - test value


def run(headers: dict[str, str], path: str = "/v1/me", secret: str = SECRET) -> tuple[int, tuple]:
    seen: dict = {}

    async def app(scope, receive, send) -> None:  # noqa: ANN001
        seen["client"] = scope.get("client")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    async def receive() -> dict:
        return {"type": "http.request", "body": b""}

    scope = {
        "type": "http",
        "path": path,
        "client": ("10.0.0.9", 51000),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(OriginGuardMiddleware(app, secret=secret)(scope, receive, send))
    return sent[0]["status"], seen.get("client", ())


def test_off_when_no_secret_is_configured() -> None:
    assert run({}, secret="") == (200, ("10.0.0.9", 51000))


def test_requests_without_the_secret_are_refused() -> None:
    assert run({})[0] == 403
    assert run({"x-origin-verify": "wrong"})[0] == 403


def test_the_secret_lets_the_request_through_with_the_viewer_address() -> None:
    status, client = run(
        {"x-origin-verify": SECRET, "cloudfront-viewer-address": "198.51.100.10:46532"}
    )
    assert status == 200 and client == ("198.51.100.10", 46532)


def test_a_client_sent_forwarded_header_is_ignored() -> None:
    _, client = run({"x-origin-verify": SECRET, "x-forwarded-for": "6.6.6.6"})
    assert client == ("10.0.0.9", 51000)


def test_health_checks_need_no_secret() -> None:
    assert run({}, path="/v1/health/live")[0] == 200


def test_viewer_ip_parses_ipv4_and_ipv6() -> None:
    assert viewer_ip("198.51.100.10:46532") == ("198.51.100.10", 46532)
    assert viewer_ip("2001:db8::8a2e:370:7334:443") == ("2001:db8::8a2e:370:7334", 443)
    assert viewer_ip("not an address") is None
    assert viewer_ip("") is None
