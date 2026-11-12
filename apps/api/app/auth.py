import base64
import logging
import time
from dataclasses import dataclass
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request
from jwt import PyJWKClient

from eagleeye_core.config import Settings, get_settings

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


class ClerkUserDirectory:
    """Fetches user profile from Clerk's backend API (lazy provisioning source)."""

    def __init__(self, secret_key: str) -> None:
        self._secret_key = secret_key

    async def fetch(self, clerk_user_id: str) -> tuple[str, str | None]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {self._secret_key}"},
            )
        if resp.status_code != 200:
            logger.warning("clerk user fetch failed: %s %s", resp.status_code, clerk_user_id)
            raise HTTPException(status_code=401, detail="Unknown user")
        data = resp.json()
        emails = {e["id"]: e["email_address"] for e in data.get("email_addresses", [])}
        email = emails.get(data.get("primary_email_address_id")) or next(
            iter(emails.values()), ""
        )
        first = data.get("first_name") or ""
        last = data.get("last_name") or ""
        display_name = f"{first} {last}".strip() or None
        return email, display_name


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


_user_cache = _TtlCache(USER_CACHE_TTL_S)
_verifier: ClerkVerifier | None = None


def get_verifier() -> ClerkVerifier:
    global _verifier
    if _verifier is None:
        _verifier = ClerkVerifier(get_settings())
    return _verifier


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    claims = get_verifier().verify(token)
    clerk_user_id: str = claims["sub"]

    cached = _user_cache.get(clerk_user_id)
    if cached is not None:
        return cached

    from app.repos.users import get_or_create_user  # local import avoids cycle

    pool = request.app.state.pool
    row = await get_or_create_user(
        pool,
        clerk_user_id,
        fetch_profile=ClerkUserDirectory(get_settings().clerk_secret_key).fetch,
    )
    user = AuthedUser(
        id=str(row["id"]),
        clerk_user_id=clerk_user_id,
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
    )
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="Account disabled")
    _user_cache.put(clerk_user_id, user)
    return user


CurrentUser = Annotated[AuthedUser, Depends(get_current_user)]
