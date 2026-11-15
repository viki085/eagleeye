"""Wake function: secret check, start rules, daily running-time cap, safety stops."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("wake", Path(__file__).with_name("wake.py"))
wake = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(wake)  # type: ignore[union-attr]

SECRET = "w" * 48  # noqa: S105 - test value
NOON = datetime(2026, 11, 15, 12, 0, tzinfo=UTC).timestamp()
HOUR = 3600


class FakeEC2:
    def __init__(self, state: str = "stopped") -> None:
        self.state = state
        self.started = self.stopped = 0

    def describe_instances(self, InstanceIds: list[str]) -> dict:  # noqa: N803
        return {"Reservations": [{"Instances": [{"State": {"Name": self.state}}]}]}

    def start_instances(self, InstanceIds: list[str]) -> None:  # noqa: N803
        self.started += 1

    def stop_instances(self, InstanceIds: list[str]) -> None:  # noqa: N803
        self.stopped += 1


class FakeSSM:
    def __init__(self, record: dict | None = None) -> None:
        self.value = json.dumps(record or {"day": "", "seconds": 0, "started_at": 0})

    def get_parameter(self, Name: str) -> dict:  # noqa: N803
        return {"Parameter": {"Value": self.value}}

    def put_parameter(self, Name: str, Value: str, Type: str, Overwrite: bool) -> None:  # noqa: N803
        self.value = Value


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wake, "WAKE_SECRET", SECRET)
    monkeypatch.setattr(wake, "INSTANCE_ID", "i-1")
    monkeypatch.setattr(wake, "DAILY_CAP_S", 6 * HOUR)


def url_event(secret: str = SECRET, method: str = "POST") -> dict:
    return {"requestContext": {"http": {"method": method}}, "headers": {"X-Wake-Secret": secret}}


def call(event: dict, ec2: FakeEC2, ssm: FakeSSM, now: float = NOON) -> dict:
    return wake.wake(event, ec2, ssm, now)


def test_a_stopped_machine_is_started() -> None:
    ec2 = FakeEC2("stopped")
    resp = call(url_event(), ec2, FakeSSM())
    assert resp["statusCode"] == 200 and json.loads(resp["body"]) == {"state": "starting"}
    assert ec2.started == 1


def test_a_running_machine_is_left_alone() -> None:
    ec2 = FakeEC2("running")
    assert json.loads(call(url_event(), ec2, FakeSSM())["body"]) == {"state": "running"}
    assert ec2.started == 0


def test_a_stopping_machine_is_reported_as_starting_without_a_start_call() -> None:
    ec2 = FakeEC2("stopping")
    assert json.loads(call(url_event(), ec2, FakeSSM())["body"]) == {"state": "starting"}
    assert ec2.started == 0


@pytest.mark.parametrize("secret", ["", "wrong", SECRET[:-1]])
def test_a_wrong_secret_is_refused(secret: str) -> None:
    ec2 = FakeEC2()
    assert call(url_event(secret), ec2, FakeSSM())["statusCode"] == 403
    assert ec2.started == 0


def test_only_post_is_accepted() -> None:
    assert call(url_event(method="GET"), FakeEC2(), FakeSSM())["statusCode"] == 405


def test_no_configured_secret_refuses_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wake, "WAKE_SECRET", "")
    assert call(url_event(""), FakeEC2(), FakeSSM())["statusCode"] == 403


def test_the_daily_cap_refuses_a_start() -> None:
    ec2 = FakeEC2("stopped")
    used = FakeSSM({"day": "2026-11-15", "seconds": 6 * HOUR, "started_at": 0})
    assert call(url_event(), ec2, used)["statusCode"] == 429 and ec2.started == 0


def test_yesterdays_running_time_does_not_count() -> None:
    ec2 = FakeEC2("stopped")
    old = FakeSSM({"day": "2026-11-14", "seconds": 6 * HOUR, "started_at": 0})
    assert call(url_event(), ec2, old)["statusCode"] == 200 and ec2.started == 1


def test_running_time_is_kept_across_starts_and_stops() -> None:
    record: dict = {"day": "", "seconds": 0, "started_at": 0}
    record = wake.on_state(record, "running", NOON)
    record = wake.on_state(record, "stopped", NOON + 2 * HOUR)
    assert record == {"day": "2026-11-15", "seconds": 2 * HOUR, "started_at": 0}
    record = wake.on_state(record, "running", NOON + 3 * HOUR)
    assert wake.used_today(record, NOON + 4 * HOUR) == 3 * HOUR


def test_a_run_across_midnight_counts_only_todays_part() -> None:
    late = datetime(2026, 11, 14, 23, 0, tzinfo=UTC).timestamp()
    record = {"day": "2026-11-14", "seconds": 4 * HOUR, "started_at": late}
    one_am = datetime(2026, 11, 15, 1, 0, tzinfo=UTC).timestamp()
    assert wake.used_today(record, one_am) == 1 * HOUR


def test_enforce_stops_a_machine_over_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    ec2 = FakeEC2("running")
    ssm = FakeSSM({"day": wake.today(NOON), "seconds": 0, "started_at": NOON - 7 * HOUR})
    monkeypatch.setattr(wake, "_clients", lambda: (ec2, ssm))
    monkeypatch.setattr(wake.time, "time", lambda: NOON)
    assert wake.handler({"action": "enforce"}) == {"stopped": True} and ec2.stopped == 1


def test_enforce_leaves_a_machine_under_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    ec2 = FakeEC2("running")
    ssm = FakeSSM({"day": wake.today(NOON), "seconds": 0, "started_at": NOON - HOUR})
    monkeypatch.setattr(wake, "_clients", lambda: (ec2, ssm))
    monkeypatch.setattr(wake.time, "time", lambda: NOON)
    assert wake.handler({"action": "enforce"}) == {"stopped": False} and ec2.stopped == 0


def test_nightly_stop_always_stops_a_running_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    ec2 = FakeEC2("running")
    monkeypatch.setattr(wake, "_clients", lambda: (ec2, FakeSSM()))
    assert wake.handler({"action": "nightly_stop"}) == {"stopped": True}


def test_state_change_events_update_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    ssm = FakeSSM()
    monkeypatch.setattr(wake, "_clients", lambda: (FakeEC2(), ssm))
    monkeypatch.setattr(wake.time, "time", lambda: NOON)
    event = {"source": "aws.ec2", "detail": {"instance-id": "i-1", "state": "running"}}
    wake.handler(event)
    assert json.loads(ssm.value)["started_at"] == NOON
    other = {"source": "aws.ec2", "detail": {"instance-id": "i-other", "state": "stopped"}}
    wake.handler(other)
    assert json.loads(ssm.value)["started_at"] == NOON  # another machine changes nothing
