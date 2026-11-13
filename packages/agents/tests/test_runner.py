import asyncio
import time
from dataclasses import dataclass, field

import pytest
from eagleeye_agents import persistence, runner
from eagleeye_agents.budgets import BudgetLimits
from eagleeye_agents.context import AgentSettings
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_llm.gateway import ChatMessage
from fakes import FakeLLM, FakeRetriever, FakeSink, FakeStore, Turn, guard_json

RUN = {
    "id": "r1",
    "chat_id": "chat1",
    "user_id": "u1",
    "status": "QUEUED",
    "params": {"doc_ids": []},
}


class FakeRedis:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled
        self.deleted: list[str] = []

    async def exists(self, key: str) -> int:
        return int(self.cancelled)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


@dataclass
class DB:
    claimable: bool = True
    history: list[ChatMessage] = field(default_factory=list)
    message_parts: list[dict] = field(default_factory=list)
    finished: dict = field(default_factory=dict)
    steps: int = 0
    usage_rows: int = 0
    titles: list[str] = field(default_factory=list)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> DB:
    state = DB()

    async def load_run(pool, run_id):  # noqa: ANN001
        return RUN

    async def claim_run(pool, run_id, model_ids, versions):  # noqa: ANN001
        return state.claimable

    async def load_conversation(pool, chat_id, run_id):  # noqa: ANN001
        return "hi there", state.history

    async def insert_assistant_message(pool, chat_id, run_id, parts, ti, to):  # noqa: ANN001
        state.message_parts = parts
        return "m1"

    async def insert_steps(pool, run_id, records):  # noqa: ANN001
        state.steps = len(records)

    async def insert_usage(pool, user_id, run_id, entries):  # noqa: ANN001
        state.usage_rows = len(entries)

    async def finish_run(pool, run_id, **kw):  # noqa: ANN001, ANN003
        state.finished = kw

    async def rename_chat(pool, chat_id, user_id, title):  # noqa: ANN001
        state.titles.append(title)
        return True

    async def heartbeat(pool, run_id):  # noqa: ANN001
        return None

    for fn in (
        load_run,
        claim_run,
        load_conversation,
        insert_assistant_message,
        insert_steps,
        insert_usage,
        finish_run,
        rename_chat,
        heartbeat,
    ):
        monkeypatch.setattr(persistence, fn.__name__, fn)
    monkeypatch.setattr(persistence, "PgRunStore", lambda pool: FakeStore())
    return state


def _deps(llm: FakeLLM, redis: FakeRedis) -> runner.RunnerDeps:
    return runner.RunnerDeps(
        pool=None,
        redis=redis,
        llm=llm,
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        settings=AgentSettings(),
        prompts=load_prompts(),
        model_ids={"capable": "m"},
    )


async def test_successful_run_persists_parts_and_emits_done(db: DB) -> None:
    sink = FakeSink()
    llm = FakeLLM([guard_json(intent="chitchat"), "Greeting chat"], [Turn("Hello!")])
    await runner.execute_run(_deps(llm, FakeRedis()), "r1", lambda rid: sink)
    names = sink.names()
    assert names[0] == "run.started" and names[-1] == "run.done"
    assert "chat.updated" in names and db.titles == ["Greeting chat"]
    types = [p["type"] for p in db.message_parts]
    assert types == ["text", "steps", "run"]
    assert db.message_parts[0]["text"].strip() == "Hello!"
    assert db.finished["status"] == "SUCCEEDED" and db.finished["route"] == "simple"
    assert db.steps >= 3 and db.usage_rows == 3  # guard + answer + title
    done = sink.of("run.done")[0]
    assert done["message_id"] == "m1" and done["cancelled"] is False


async def test_run_records_time_to_first_token_and_warnings(db: DB) -> None:
    llm = FakeLLM([guard_json(intent="chitchat"), "Greeting chat"], [Turn("Hello!")])
    await runner.execute_run(_deps(llm, FakeRedis()), "r1", lambda rid: FakeSink())
    assert db.finished["first_token_at"] is not None
    assert list(db.finished["warnings"]) == []


class SwitchRedis(FakeRedis):
    def __init__(self, killed: set[str]) -> None:
        super().__init__()
        self.killed = killed

    async def exists(self, key: str) -> int:
        return int(key in self.killed)


class UpExecutor:
    async def available(self) -> bool:
        return True


class OneSourceCatalog:
    async def accessible_sources(self, role):  # noqa: ANN001, ANN201
        return ["acme"]


@pytest.mark.parametrize(
    ("killed", "sql", "analysis"),
    [(set(), True, True), ({"kill:sql"}, False, True), ({"kill:analysis"}, True, False)],
)
async def test_kill_switches_hide_sql_and_analysis(
    monkeypatch: pytest.MonkeyPatch, killed: set[str], sql: bool, analysis: bool
) -> None:
    async def role(pool, user_id):  # noqa: ANN001, ANN202
        return "member"

    monkeypatch.setattr(persistence, "load_user_role", role)
    deps = runner.RunnerDeps(
        pool=None,
        redis=SwitchRedis(killed),
        llm=FakeLLM(),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        settings=AgentSettings(),
        prompts=load_prompts(),
        model_ids={},
        gateway=object(),
        catalog=OneSourceCatalog(),
        workspace=object(),
        executor=UpExecutor(),
    )
    ctx = runner._build_context(deps, RUN, FakeSink())
    await runner._enable_sql(deps, ctx)
    await runner._enable_analysis(deps, ctx)
    assert ctx.sql_available is sql and ctx.analysis_available is analysis


async def test_cancelled_run_is_persisted_as_cancelled(db: DB) -> None:
    sink = FakeSink()
    redis = FakeRedis(cancelled=True)
    await runner.execute_run(_deps(FakeLLM(), redis), "r1", lambda rid: sink)
    assert db.finished["status"] == "CANCELLED"
    assert sink.of("run.done")[0]["cancelled"] is True
    assert redis.deleted  # cancel flag cleaned up


async def test_unexpected_error_marks_failed_and_emits_error(
    db: DB, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*a):  # noqa: ANN002
        raise RuntimeError("db gone")

    monkeypatch.setattr(persistence, "load_conversation", boom)
    sink = FakeSink()
    await runner.execute_run(_deps(FakeLLM(), FakeRedis()), "r1", lambda rid: sink)
    assert db.finished["status"] == "FAILED"
    assert sink.names()[-1] == "run.error"


async def test_already_claimed_run_is_skipped(db: DB) -> None:
    db.claimable = False
    sink = FakeSink()
    await runner.execute_run(_deps(FakeLLM(), FakeRedis()), "r1", lambda rid: sink)
    assert sink.events == [] and db.finished == {}


class HangingLLM(FakeLLM):
    """Guard answers, then the answer stream hangs forever (a stuck provider call)."""

    async def stream(self, tier, messages, max_tokens=2048, tools=None):  # noqa: ANN001
        await asyncio.sleep(3600)
        yield  # pragma: no cover


async def test_stop_interrupts_a_hung_llm_call(db: DB) -> None:
    redis = FakeRedis()
    sink = FakeSink()
    llm = HangingLLM([guard_json(intent="chitchat")])

    async def press_stop() -> None:
        await asyncio.sleep(0.3)
        redis.cancelled = True

    started = time.monotonic()
    await asyncio.gather(
        runner.execute_run(_deps(llm, redis), "r1", lambda rid: sink), press_stop()
    )
    assert time.monotonic() - started < 3
    assert db.finished["status"] == "CANCELLED"
    llm_step = [d for d in sink.of("step.finished") if d["status"] == "skipped"]
    assert llm_step and llm_step[0]["output_summary"] == "stopped"


async def test_hard_deadline_fails_run_with_timeout(
    db: DB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "DEADLINE_GRACE_S", 0.3)
    sink = FakeSink()
    deps = _deps(HangingLLM([guard_json(intent="chitchat")]), FakeRedis())
    deps = runner.RunnerDeps(
        **{**deps.__dict__, "settings": AgentSettings(limits=BudgetLimits(max_seconds=0.0))}
    )
    await runner.execute_run(deps, "r1", lambda rid: sink)
    assert db.finished["status"] == "FAILED" and db.finished["error_code"] == "TIMEOUT"
    assert sink.of("run.error")[0]["code"] == "TIMEOUT"


async def test_no_title_after_first_turn(db: DB) -> None:
    db.history = [ChatMessage("user", "earlier"), ChatMessage("assistant", "reply")]
    sink = FakeSink()
    llm = FakeLLM([guard_json(intent="chitchat")], [Turn("ok")])
    await runner.execute_run(_deps(llm, FakeRedis()), "r1", lambda rid: sink)
    assert db.titles == [] and "chat.updated" not in sink.names()
