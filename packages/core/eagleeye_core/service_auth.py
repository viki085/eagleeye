"""Short-lived HMAC context tokens between the agent worker and the data gateway (LLD §5).

The token says only WHO is asking and FOR WHICH source; the gateway looks up everything
else (role, grants, catalog) itself. Phase 2 replaces this with SigV4 / mTLS.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

TOKEN_TTL_S = 30
LOCAL_DEV_SECRET = "eagleeye-local-gateway-secret"  # noqa: S105 — accepted ONLY when APP_ENV=local


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class ContextToken:
    user_id: str
    source_id: str
    run_id: str | None
    exp: int


def resolve_secret(configured: str, app_env: str) -> str:
    if configured:
        return configured
    if app_env == "local":
        return LOCAL_DEV_SECRET
    raise RuntimeError("GATEWAY_HMAC_SECRET must be set outside APP_ENV=local")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(secret: str, user_id: str, source_id: str, run_id: str | None = None,
         now: float | None = None) -> str:
    payload = {
        "u": user_id, "s": source_id, "r": run_id,
        "exp": int((now if now is not None else time.time()) + TOKEN_TTL_S),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def verify(secret: str, token: str, now: float | None = None) -> ContextToken:
    try:
        body, mac = token.split(".", 1)
    except ValueError as exc:
        raise TokenError("malformed token") from exc
    expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(mac, expected):
        raise TokenError("bad signature")
    try:
        data = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("malformed payload") from exc
    if int(data.get("exp", 0)) < (now if now is not None else time.time()):
        raise TokenError("expired")
    if not data.get("u") or not data.get("s"):
        raise TokenError("missing claims")
    return ContextToken(str(data["u"]), str(data["s"]), data.get("r"), int(data["exp"]))
