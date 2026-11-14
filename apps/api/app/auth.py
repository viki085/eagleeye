import base64
import logging
import time
from dataclasses import dataclass
from typing import Annotated

import jwt
from eagleeye_core.config import Settings, get_settings
from fastapi import Depends, Header, HTTPException, Request
from jwt import PyJWKClient

from app.services import rate_limit
from app.services.rate_limit import Limit

logger = logging.getLogger(__name__)

JWKS_CACHE_TTL_S = 3600
USER_CACHE_TTL_S = 60


@dataclass(frozen=True)
class AuthedUser:
    id: str  # internal uuid
    clerk_user_id: str
    email: str
    display_name: str | None
    role: str
    is_demo: bool = False
    usage_limit_usd: float | None = None  # None = the organisation default


def usage_limit_for(user: "AuthedUser", default: float) -> float:
    """The user's lifetime LLM spend cap: their own, else the organisation default."""
    return default if user.usage_limit_usd is None else user.usage_limit_usd


def derive_issuer(publishable_key: str) -> str:
    """Clerk publishable keys encode the frontend API domain: pk_test_<b64(domain$)>."""
    encoded = publishable_key.split("_")[-1]
    padded = encoded + "=" * (-len(encoded) % 4)
    domain = base64.b64decode(padded).decode("utf-8").rstrip("$")
    return f"https://{domain}"


class ClerkVerifier:
    def __init__(self, settings: Settings) -> None:
        issuer = settings.clerk_issuer or derive_issuer(settings.clerk_publishable_key)
        self._issuer = issuer
        self._web_origin = settings.web_origin
        self._jwk_client = PyJWKClient(
            f"{issuer}/.well-known/jwks.json", cache_keys=True, lifespan=JWKS_CACHE_TTL_S
        )

    def verify(self, token: str) -> dict:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub"]},
                leeway=5,
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        azp = claims.get("azp")
        if azp is not None and azp != self._web_origin:
            raise HTTPException(status_code=401, detail="Token not issued for this origin")
        return claims


class _TtlCache:
    def __init__(self, ttl_s: float) -> None:
        self._ttl = ttl_s
        self._items: dict[str, tuple[float, AuthedUser]] = {}

    def get(self, key: str) -> AuthedUser | None:
        entry = self._items.get(key)
        if entry is None or entry[0] < time.monotonic():
            self._items.pop(key, None)
            return None
        return entry[1]

    def put(self, key: str, value: AuthedUser) -> None:
        self._items[key] = (time.monotonic() + self._ttl, value)

    def drop(self, key: str) -> None:
        self._items.pop(key, None)


_user_cache = _TtlCache(USER_CACHE_TTL_S)
_verifier: ClerkVerifier | None = None

NOT_PROVISIONED = "Your account hasn't been set up for EagleEye. Ask your administrator for access."


def forget_user(clerk_user_id: str) -> None:
    """Drop a cached identity (after a delete/role change) so it takes effect immediately."""
    _user_cache.drop(clerk_user_id)


def get_verifier() -> ClerkVerifier:
    global _verifier
    if _verifier is None:
        _verifier = ClerkVerifier(get_settings())
    return _verifier


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser:
    redis = getattr(request.app.state, "redis", None)
    settings = get_settings()
    if redis is not None:  # bound unauthenticated / token-guessing traffic per client IP
        client_ip = request.client.host if request.client else "unknown"
        await rate_limit.hit(redis, Limit("ip", settings.rate_limit_ip_per_min), client_ip)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    claims = get_verifier().verify(token)
    clerk_user_id: str = claims["sub"]

    cached = _user_cache.get(clerk_user_id)
    if cached is not None:
        if redis is not None:
            await rate_limit.hit(
                redis, Limit("user", settings.rate_limit_general_per_min), cached.id
            )
        await _note_demo(request, cached, claims)
        return cached

    from app.repos import users as users_repo  # local import avoids cycle

    # enterprise: accounts exist only if an admin provisioned them; a Clerk sign-in alone
    # (e.g. if self-signup were left on in Clerk) never creates one
    row = await users_repo.touch_signed_in_user(request.app.state.pool, clerk_user_id)
    if row is None:
        raise HTTPException(status_code=403, detail=NOT_PROVISIONED)
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="This account has been disabled.")
    user = AuthedUser(
        id=str(row["id"]),
        clerk_user_id=clerk_user_id,
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        is_demo=bool(row.get("is_demo", False)),
        usage_limit_usd=_float_or_none(row.get("usage_limit_usd")),
    )
    _user_cache.put(clerk_user_id, user)
    if redis is not None:
        await rate_limit.hit(redis, Limit("user", settings.rate_limit_general_per_min), user.id)
    await _note_demo(request, user, claims)
    return user


def _float_or_none(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


async def _note_demo(request: Request, user: AuthedUser, claims: dict) -> None:
    """Demo account only: email the owner on each new sign-in session."""
    if not user.is_demo:
        return
    from app.services import demo_login  # local import keeps auth light for everyone else

    await demo_login.note_request(
        getattr(request.app.state, "redis", None),
        get_settings(),
        claims,
        request.client.host if request.client else "unknown",
        request.headers.get("user-agent", ""),
    )


CurrentUser = Annotated[AuthedUser, Depends(get_current_user)]
