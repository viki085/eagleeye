"""Shared demo account: its own spend cap, and one email per new sign-in session
(deduplicated in Redis, capped per hour, never blocking or failing the request)."""

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from app.auth import AuthedUser, usage_limit_for
from app.services import demo_login, notify
from eagleeye_core.config import Settings
from fake_redis import FakeRedis

DEMO = AuthedUser(
    str(uuid.uuid4()),
    "user_demo",
    "demo@example.com",
    None,
    "member",
    is_demo=True,
    usage_limit_usd=1.0,
)


def settings(**kw: object) -> Settings:
    base = {
        "demo_notify_email": "owner@example.com",
        "smtp_username": "me@example.com",
        "smtp_password": "app-pass",
        "demo_notify_max_per_hour": 3,
    }
    return Settings(**{**base, **kw})


# ---- spend cap -----------------------------------------------------------------------


def test_own_limit_overrides_the_organisation_default() -> None:
    assert usage_limit_for(DEMO, 500.0) == 1.0
    assert usage_limit_for(replace(DEMO, usage_limit_usd=None), 500.0) == 500.0
    assert usage_limit_for(replace(DEMO, usage_limit_usd=0.0), 500.0) == 0.0


# ---- sign-in notifications -----------------------------------------------------------


def test_a_session_is_new_only_once() -> None:
    redis, s = FakeRedis(), settings()

    async def run() -> list[bool]:
        return [await demo_login.is_new_session(redis, sid, s) for sid in ("a", "a", "b")]

    assert asyncio.run(run()) == [True, False, True]


def test_notifications_are_capped_per_hour() -> None:
    redis, s = FakeRedis(), settings(demo_notify_max_per_hour=2)

    async def run() -> list[bool]:
        return [await demo_login.is_new_session(redis, f"s{i}", s) for i in range(4)]

    assert asyncio.run(run()) == [True, True, False, False]


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    async def fake_send(s, to, subject, body):  # noqa: ANN001
        sent.append((to, subject))
        return True

    monkeypatch.setattr(demo_login, "send_email", fake_send)
    return sent


def test_one_email_per_session_to_the_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    sent, redis, s = _capture(monkeypatch), FakeRedis(), settings()

    async def run() -> None:
        for _ in range(3):  # many requests in one session
            await demo_login.note_request(redis, s, {"sid": "sess_1"}, "1.2.3.4", "Firefox")
        await demo_login.note_request(redis, s, {"sid": "sess_2"}, "1.2.3.4", "Firefox")
        await asyncio.gather(*demo_login._pending)

    asyncio.run(run())
    assert [to for to, _ in sent] == ["owner@example.com", "owner@example.com"]
    assert sent[0][1].startswith("EagleEye demo sign-in")


@pytest.mark.parametrize(
    ("claims", "kw", "redis"),
    [
        ({}, {}, FakeRedis()),  # no session id in the token
        ({"sid": "s"}, {"demo_notify_email": ""}, FakeRedis()),  # notifications off
        ({"sid": "s"}, {}, None),  # no Redis
        ({"sid": "s"}, {}, FakeRedis(fail=True)),  # Redis down: request still succeeds
    ],
)
def test_no_email_when_it_cannot_or_should_not_be_sent(
    monkeypatch: pytest.MonkeyPatch, claims: dict, kw: dict, redis: FakeRedis | None
) -> None:
    sent = _capture(monkeypatch)
    asyncio.run(demo_login.note_request(redis, settings(**kw), claims, "ip", "ua"))
    assert sent == []


def test_email_body_names_time_ip_and_browser() -> None:
    subject, body = demo_login.compose(
        datetime(2026, 11, 14, 9, 30, tzinfo=UTC), "203.0.113.7", "x" * 500, "demouser1"
    )
    assert subject == "EagleEye demo sign-in · 2026-11-14 09:30 UTC"
    assert "203.0.113.7" in body and "demouser1" in body
    assert "x" * 201 not in body  # user agent truncated


# ---- SMTP ----------------------------------------------------------------------------


def test_send_email_skips_without_credentials() -> None:
    assert asyncio.run(notify.send_email(settings(smtp_password=""), "a@b.c", "s", "b")) is False


def test_send_email_logs_in_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSMTP:
        def __init__(self, host, port, context, timeout):  # noqa: ANN001
            calls.append(f"connect {host}:{port}")

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *exc):  # noqa: ANN002, ANN204
            return False

        def login(self, user, password):  # noqa: ANN001
            calls.append(f"login {user}")

        def send_message(self, msg):  # noqa: ANN001
            calls.append(f"send {msg['To']} {msg['Subject']}")

    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    assert asyncio.run(notify.send_email(settings(), "owner@example.com", "Hi", "body")) is True
    assert calls == [
        "connect smtp.gmail.com:465",
        "login me@example.com",
        "send owner@example.com Hi",
    ]


def test_send_email_failure_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise OSError("network down")

    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", boom)
    assert asyncio.run(notify.send_email(settings(), "a@b.c", "s", "b")) is False
