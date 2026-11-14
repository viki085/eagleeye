"""Demo reset scheduling (idle-only, once per period across processes) and seed files."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.demo import account, reset_loop
from eagleeye_core.config import Settings
from fake_redis import FakeRedis


def _state(monkeypatch: pytest.MonkeyPatch, *, exists: bool = True, idle: bool = True):
    calls: list[str] = []

    async def demo_user_id(pool):  # noqa: ANN001
        return "demo-id" if exists else None

    async def demo_is_idle(pool):  # noqa: ANN001
        return idle

    async def reset(pool, store, queue, clerk, settings):  # noqa: ANN001
        calls.append("reset")

    monkeypatch.setattr(account, "demo_user_id", demo_user_id)
    monkeypatch.setattr(reset_loop, "demo_is_idle", demo_is_idle)
    monkeypatch.setattr(account, "reset", reset)
    state = SimpleNamespace(
        pool=None, redis=FakeRedis(), store=None, task_queue=None, clerk_admin=None
    )
    return state, calls


def test_resets_once_per_period(monkeypatch: pytest.MonkeyPatch) -> None:
    state, calls = _state(monkeypatch)
    s = Settings(demo_reset_hours=24)

    async def run() -> list[bool]:
        return [await reset_loop.maybe_reset(state, s) for _ in range(3)]

    assert asyncio.run(run()) == [True, False, False] and calls == ["reset"]


@pytest.mark.parametrize(
    ("kw", "hours"),
    [({"exists": False}, 24), ({"idle": False}, 24), ({}, 0)],
    ids=["no demo account", "visitor active", "resets disabled"],
)
def test_no_reset_when_not_due(monkeypatch: pytest.MonkeyPatch, kw: dict, hours: float) -> None:
    state, calls = _state(monkeypatch, **kw)
    assert asyncio.run(reset_loop.maybe_reset(state, Settings(demo_reset_hours=hours))) is False
    assert calls == []


def test_seed_files_are_the_csvs_in_name_order(tmp_path: Path) -> None:
    (tmp_path / "b_file.csv").write_text("a\n1\n")
    (tmp_path / "a-file.csv").write_text("a\n2\n")
    (tmp_path / "notes.txt").write_text("ignored")
    files = account.seed_files(tmp_path)
    assert [f.path.name for f in files] == ["a-file.csv", "b_file.csv"]
    assert len({f.sha256 for f in files}) == 2


def test_missing_seed_folder_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Demo files folder"):
        account.seed_files(tmp_path / "nope")


def test_titles_read_like_the_upload_titles() -> None:
    assert account._title("customer_survey_2026.csv") == "customer survey 2026"


def test_setup_requires_a_password() -> None:
    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        asyncio.run(account.setup(None, None, None, None, Settings(demo_password="")))
