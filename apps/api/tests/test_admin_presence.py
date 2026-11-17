"""Admin presence: masked visitor networks and throttled last-seen writes."""

import asyncio
from types import SimpleNamespace

from app import auth
from app.repos.admin_presence import mask_ip


def test_visitor_ips_are_masked_to_their_network() -> None:
    assert mask_ip("203.0.113.7") == "203.0.113.x"
    assert mask_ip("2001:0db8:85a3:0042::/64") == "2001:db8:…"
    assert mask_ip("not-an-ip") == "hidden"


class RecordingPool:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, sql: str, *args: object) -> None:
        self.calls.append((sql, args))


def test_last_seen_is_written_at_most_once_a_minute(monkeypatch) -> None:  # noqa: ANN001
    pool = RecordingPool()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    clock = iter([1000.0, 1030.0, 1061.0])
    monkeypatch.setattr(auth, "_seen_clock", lambda: next(clock))
    monkeypatch.setattr(auth, "_last_seen_write", {})

    async def run() -> None:
        for _ in range(3):
            await auth._note_seen(request, "u-1")  # noqa: SLF001

    asyncio.run(run())
    assert len(pool.calls) == 2  # t=1000 written, t=1030 throttled, t=1061 written again
    assert "last_seen_at" in pool.calls[0][0] and pool.calls[0][1] == ("u-1",)


def test_a_failed_last_seen_write_never_fails_the_request(monkeypatch) -> None:  # noqa: ANN001
    class Broken:
        async def execute(self, *a: object) -> None:
            raise OSError("db down")

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=Broken())))
    monkeypatch.setattr(auth, "_last_seen_write", {})
    asyncio.run(auth._note_seen(request, "u-2"))  # noqa: SLF001 — no exception


def test_after_a_sign_out_last_seen_writes_wait_a_minute(monkeypatch) -> None:  # noqa: ANN001
    pool = RecordingPool()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)))
    clock = iter([1000.0, 1010.0, 1061.0])
    monkeypatch.setattr(auth, "_seen_clock", lambda: next(clock))
    monkeypatch.setattr(auth, "_last_seen_write", {})
    auth.pause_seen("u-3")  # t=1000: signed out

    async def run() -> None:
        await auth._note_seen(request, "u-3")  # noqa: SLF001 - t=1010: a late request
        await auth._note_seen(request, "u-3")  # noqa: SLF001 - t=1061: the next sign-in

    asyncio.run(run())
    assert len(pool.calls) == 1  # the late request did not mark them online again
