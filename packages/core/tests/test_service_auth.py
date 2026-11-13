import pytest
from eagleeye_core.service_auth import LOCAL_DEV_SECRET, TokenError, resolve_secret, sign, verify

SECRET = "test-secret"  # noqa: S105


def test_round_trip() -> None:
    tok = verify(SECRET, sign(SECRET, "u1", "s1", "r1", now=1000), now=1010)
    assert (tok.user_id, tok.source_id, tok.run_id) == ("u1", "s1", "r1")


def test_tampered_payload_rejected() -> None:
    body, mac = sign(SECRET, "u1", "s1", now=1000).split(".")
    forged = sign(SECRET, "admin", "s1", now=1000).split(".")[0]
    with pytest.raises(TokenError):
        verify(SECRET, f"{forged}.{mac}", now=1001)
    with pytest.raises(TokenError):
        verify("other-secret", f"{body}.{mac}", now=1001)


def test_expired_and_malformed() -> None:
    with pytest.raises(TokenError, match="expired"):
        verify(SECRET, sign(SECRET, "u1", "s1", now=1000), now=1031)
    for bad in ("", "abc", "a.b.c", "!!!.???"):
        with pytest.raises(TokenError):
            verify(SECRET, bad, now=1000)


def test_secret_resolution_fails_closed_outside_local() -> None:
    assert resolve_secret("", "local") == LOCAL_DEV_SECRET
    assert resolve_secret("configured", "prod") == "configured"
    with pytest.raises(RuntimeError):
        resolve_secret("", "prod")
