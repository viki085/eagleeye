import base64
import logging
import time
from dataclasses import dataclass
from typing import Annotated

import jwt
from eagleeye_core.config import LOADTEST_ENV, Settings, get_settings
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
    session_id: str | None = None  # demo visits: the Clerk session the visit was resolved from


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


LOADTEST_ISSUER = "eagleeye-loadtest"
LOADTEST_SUBJECT_PREFIX = "loadtest:"  # synthetic users' clerk_user_id, set by the seed script
LOADTEST_MAX_TOKEN_LIFETIME_S = 6 * 3600


class LoadTestVerifier:
    """Synthetic users' tokens (APP_ENV=loadtest only, ADR-34): RS256, signed by the load
    generator's private key, issuer `eagleeye-loadtest`, subject `loadtest:<n>`. Anything
    else is handed to the Clerk verifier unchanged."""

    def __init__(self, public_key_pem: str, fallback: "ClerkVerifier") -> None:
        # an env var often carries the PEM on one line with literal "\n"
        self._key = public_key_pem.replace("\\n", "\n")
        self._fallback = fallback

    def verify(self, token: str) -> dict:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        if unverified.get("iss") != LOADTEST_ISSUER:
            return self._fallback.verify(token)
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["RS256"],
                issuer=LOADTEST_ISSUER,
                options={"require": ["exp", "iat", "sub"]},
                leeway=5,
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        if not str(claims["sub"]).startswith(LOADTEST_SUBJECT_PREFIX):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        lifetime = int(claims["exp"]) - int(claims["iat"])
        if lifetime > LOADTEST_MAX_TOKEN_LIFETIME_S or (
            int(claims["exp"]) - time.time() > LOADTEST_MAX_TOKEN_LIFETIME_S
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
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
_verifier: "ClerkVerifier | LoadTestVerifier | None" = None

NOT_PROVISIONED = "Your account hasn't been set up for EagleEye. Ask your administrator for access."


def forget_user(clerk_user_id: str) -> None:
    """Drop a cached identity (after a delete/role change) so it takes effect immediately."""
    _user_cache.drop(clerk_user_id)


def build_verifier(settings: Settings) -> "ClerkVerifier | LoadTestVerifier":
    clerk = ClerkVerifier(settings)
    if not settings.loadtest_token_public_key:
        return clerk
    if settings.app_env != LOADTEST_ENV:  # Settings already refuses this; checked again
        raise RuntimeError("LOADTEST_TOKEN_PUBLIC_KEY is only allowed when APP_ENV=loadtest")
    logger.warning("load-test sign-in is ON: synthetic users can sign in (APP_ENV=loadtest)")
    return LoadTestVerifier(settings.loadtest_token_public_key, clerk)


def get_verifier() -> "ClerkVerifier | LoadTestVerifier":
    global _verifier
    if _verifier is None:
        _verifier = build_verifier(get_settings())
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
        resolved = await _as_demo_visit(request, cached, claims)
        await _note_seen(request, resolved.id)
        return resolved

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
    resolved = await _as_demo_visit(request, user, claims)
    await _note_seen(request, resolved.id)
    return resolved


SEEN_EVERY_S = 60  # users.last_seen_at is written at most this often per user (per process)
_last_seen_write: dict[str, float] = {}
_seen_clock = time.monotonic  # replaced in tests


async def _note_seen(request: Request, user_id: str) -> None:
    """Keeps users.last_seen_at current for the admin console's "online now" (best effort:
    never slows or fails a request)."""
    now = _seen_clock()
    if now - _last_seen_write.get(user_id, float("-inf")) < SEEN_EVERY_S:
        return
    _last_seen_write[user_id] = now
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        return
    try:
        await pool.execute("UPDATE users SET last_seen_at = now() WHERE id = $1", user_id)
    except Exception:  # noqa: BLE001
        logger.debug("could not record last_seen for %s", user_id, exc_info=True)


def pause_seen(user_id: str) -> None:
    """After a sign-out: a request still in flight must not mark the user online again, so
    last_seen writes for them wait a full SEEN_EVERY_S (per process, best effort)."""
    _last_seen_write[user_id] = _seen_clock()


_visit_cache = _TtlCache(USER_CACHE_TTL_S)  # Clerk session id -> the visit account


async def _as_demo_visit(request: Request, user: AuthedUser, claims: dict) -> AuthedUser:
    """The shared demo sign-in acts as the visit account of this session (one per visitor,
    so visitors never see each other's data). Everyone else is returned unchanged."""
    if not user.is_demo:
        return user
    session_id = claims.get("sid")
    if not session_id:
        raise HTTPException(status_code=401, detail="Please sign in to the demo again.")
    cached = _visit_cache.get(str(session_id))
    if cached is not None:
        return cached
    from app.repos import users as users_repo
    from app.services import demo_visits

    pool = request.app.state.pool
    ip = request.client.host if request.client else "unknown"
    visit_user_id = await demo_visits.account_for_session(pool, user.id, str(session_id), ip)
    row = await users_repo.get_user(pool, visit_user_id)
    if row is None:
        raise HTTPException(status_code=403, detail="The demo is not available right now.")
    visit = AuthedUser(
        id=str(row["id"]),
        clerk_user_id=user.clerk_user_id,
        email=user.email,
        display_name=row["display_name"],
        role="member",
        is_demo=True,
        usage_limit_usd=_float_or_none(row.get("usage_limit_usd")),
        session_id=str(session_id),
    )
    _visit_cache.put(str(session_id), visit)
    return visit


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
