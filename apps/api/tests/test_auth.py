import base64
import time

from app.auth import AuthedUser, _TtlCache, derive_issuer


def _pk(domain: str) -> str:
    encoded = base64.b64encode(f"{domain}$".encode()).decode().rstrip("=")
    return f"pk_test_{encoded}"


def test_derive_issuer_from_publishable_key() -> None:
    assert derive_issuer(_pk("example.clerk.accounts.dev")) == (
        "https://example.clerk.accounts.dev"
    )


def test_derive_issuer_handles_padding_variants() -> None:
    for domain in ("a.clerk.accounts.dev", "ab.clerk.accounts.dev", "abc.clerk.accounts.dev"):
        assert derive_issuer(_pk(domain)) == f"https://{domain}"


def _user(uid: str = "u1") -> AuthedUser:
    return AuthedUser(id=uid, clerk_user_id="ck_1", email="a@b.c", display_name=None, role="member")


def test_ttl_cache_returns_within_ttl() -> None:
    cache = _TtlCache(ttl_s=60)
    cache.put("k", _user())
    assert cache.get("k") is not None


def test_ttl_cache_expires(monkeypatch) -> None:
    cache = _TtlCache(ttl_s=0.01)
    cache.put("k", _user())
    time.sleep(0.02)
    assert cache.get("k") is None


def test_ttl_cache_miss() -> None:
    assert _TtlCache(ttl_s=60).get("absent") is None
