"""Synthetic load-test sign-in (ADR-34): narrow, and impossible outside APP_ENV=loadtest."""

import time

import jwt
import pytest
from app import auth
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from eagleeye_core.config import Settings
from fastapi import HTTPException


def _keypair() -> tuple[bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public.decode()


PRIVATE, PUBLIC = _keypair()
OTHER_PRIVATE, _ = _keypair()


class FakeClerk:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def verify(self, token: str) -> dict:
        self.tokens.append(token)
        return {"sub": "user_clerk"}


def _token(key: bytes = PRIVATE, sub: str = "loadtest:7", hours: float = 1, **extra: object) -> str:
    now = int(time.time())
    claims = {"iss": auth.LOADTEST_ISSUER, "sub": sub, "iat": now, "exp": now + int(hours * 3600)}
    return jwt.encode({**claims, **extra}, key, algorithm="RS256")


def _verifier(clerk: FakeClerk | None = None) -> auth.LoadTestVerifier:
    return auth.LoadTestVerifier(PUBLIC, clerk or FakeClerk())  # type: ignore[arg-type]


def test_a_signed_synthetic_token_is_accepted() -> None:
    assert _verifier().verify(_token())["sub"] == "loadtest:7"


def test_the_key_may_arrive_on_one_line() -> None:
    one_line = PUBLIC.replace("\n", "\\n")
    verifier = auth.LoadTestVerifier(one_line, FakeClerk())  # type: ignore[arg-type]
    assert verifier.verify(_token())["sub"] == "loadtest:7"


@pytest.mark.parametrize(
    "token",
    [
        _token(OTHER_PRIVATE),  # signed by someone else
        _token(sub="user_2abc"),  # a real-looking Clerk user id
        _token(hours=7),  # longer than the 6 h cap
        _token(hours=-1),  # expired
        jwt.encode({"iss": auth.LOADTEST_ISSUER, "sub": "loadtest:1"}, PRIVATE, algorithm="RS256"),
        "not-a-jwt",
    ],
)
def test_bad_synthetic_tokens_are_refused(token: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _verifier().verify(token)
    assert exc.value.status_code == 401


def test_hs256_with_the_public_key_is_refused() -> None:
    # the classic algorithm-confusion attack: "sign" with the public key as an HMAC secret
    claims = {"iss": auth.LOADTEST_ISSUER, "sub": "loadtest:1", "iat": 1, "exp": 2**31}
    import base64
    import hashlib
    import hmac
    import json

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    sig = hmac.new(PUBLIC.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    with pytest.raises(HTTPException):
        _verifier().verify(f"{head}.{body}.{b64(sig)}")


def test_other_tokens_go_to_clerk_unchanged() -> None:
    clerk = FakeClerk()
    token = jwt.encode(
        {"iss": "https://clerk.example", "sub": "user_1"}, "x" * 32, algorithm="HS256"
    )
    assert _verifier(clerk).verify(token) == {"sub": "user_clerk"}
    assert clerk.tokens == [token]


def _settings(env: str, key: str) -> Settings:
    # model_construct skips the Settings guard, to prove build_verifier checks again
    return Settings.model_construct(
        app_env=env,
        loadtest_token_public_key=key,
        clerk_issuer="https://clerk.example",
        clerk_publishable_key="",
        web_origin="http://localhost:3000",
    )


def test_build_verifier_is_plain_clerk_without_the_key() -> None:
    assert isinstance(auth.build_verifier(_settings("production", "")), auth.ClerkVerifier)


def test_build_verifier_refuses_the_key_outside_loadtest() -> None:
    with pytest.raises(RuntimeError, match="APP_ENV=loadtest"):
        auth.build_verifier(_settings("production", PUBLIC))


def test_build_verifier_enables_synthetic_sign_in_in_loadtest() -> None:
    assert isinstance(auth.build_verifier(_settings("loadtest", PUBLIC)), auth.LoadTestVerifier)


def test_a_token_expiring_beyond_6_hours_from_now_is_refused() -> None:
    now = int(time.time())
    # a 1-hour lifetime that claims to be issued 10 hours from now
    token = jwt.encode(
        {"iss": auth.LOADTEST_ISSUER, "sub": "loadtest:1", "iat": now + 36000, "exp": now + 39600},
        PRIVATE,
        algorithm="RS256",
    )
    with pytest.raises(HTTPException):
        _verifier().verify(token)
