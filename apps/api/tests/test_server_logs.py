"""Server logs for the admin console: query building, parsing and the route."""

import asyncio
import json
import uuid

import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.services import server_logs as sl
from app.services.permissions import require_admin
from fastapi.testclient import TestClient

ADMIN = AuthedUser(str(uuid.uuid4()), "user_admin", "admin@example.com", None, "admin")


def test_query_filters_are_fixed_or_escaped() -> None:
    q = sl.build_query(sl.LogQuery(service="api", level="error", text='boom" | fields secret \\'))
    assert '| filter @logStream like "eagleeye-demo-api-"' in q
    assert '| filter level in ["ERROR", "CRITICAL"]' in q
    # the text can't close its string literal and start a new command
    assert '| filter @message like "boom\\" | fields secret \\\\"' in q
    assert q.endswith(f"| sort @timestamp desc\n| limit {sl.MAX_EVENTS}")
    plain = sl.build_query(sl.LogQuery())
    assert "filter" not in plain


def test_json_lines_are_unpacked_and_plain_lines_kept() -> None:
    row = {
        "@timestamp": "2026-11-17 17:20:01.123",
        "@logStream": "eagleeye-demo-agent-worker-1",
        "@message": json.dumps(
            {
                "time": "t",
                "level": "ERROR",
                "service": "agent-worker",
                "logger": "x",
                "message": "tool failed",
                "run_id": "r1",
            }
        ),
    }
    e = sl.parse_event(row)
    assert (e["service"], e["level"], e["message"]) == ("agent-worker", "ERROR", "tool failed")
    assert e["details"] == {"run_id": "r1"}
    plain = sl.parse_event(
        {"@logStream": "eagleeye-demo-ingest-worker-1", "@message": "Loading weights 100%"}
    )
    assert (plain["service"], plain["level"], plain["message"]) == (
        "ingest-worker",
        None,
        "Loading weights 100%",
    )


class FakeLogs:
    def __init__(self, status: str = "Complete") -> None:
        self.status = status
        self.started: dict = {}
        self.stopped = False

    def start_query(self, **kw: object) -> dict:
        self.started = kw
        return {"queryId": "q1"}

    def get_query_results(self, queryId: str) -> dict:  # noqa: N803 - boto3's name
        row = [
            {"field": "@timestamp", "value": "2026-11-17 17:20:01.123"},
            {"field": "@logStream", "value": "eagleeye-demo-api-1"},
            {"field": "@message", "value": '{"level": "INFO", "message": "started"}'},
        ]
        return {"status": self.status, "results": [row]}

    def stop_query(self, queryId: str) -> None:  # noqa: N803
        self.stopped = True


def test_recent_runs_one_insights_query_over_the_window() -> None:
    fake = FakeLogs()
    events = asyncio.run(
        sl.recent("/eagleeye/demo", "us-east-1", sl.LogQuery(window="15m"), client=fake)
    )
    assert events[0]["message"] == "started" and events[0]["service"] == "api"
    assert fake.started["logGroupName"] == "/eagleeye/demo"
    assert fake.started["endTime"] - fake.started["startTime"] == 15 * 60


def test_a_failed_query_is_reported_not_raised_raw() -> None:
    with pytest.raises(sl.LogsUnavailableError):
        asyncio.run(sl.recent("/g", "us-east-1", sl.LogQuery(), client=FakeLogs(status="Failed")))


def _client() -> TestClient:
    """An admin (the database role check is covered by test_admin.py's admin-only routes)."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[require_admin] = lambda: ADMIN
    return TestClient(app)


def test_route_says_when_logs_are_not_kept_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eagleeye_core.config import get_settings

    monkeypatch.setattr(get_settings(), "log_group", "")
    data = _client().get("/v1/admin/logs").json()["data"]
    assert data["available"] is False and data["events"] == []
    assert _client().get("/v1/admin/logs?service=nope").status_code == 422


def test_route_returns_events(monkeypatch: pytest.MonkeyPatch) -> None:
    from eagleeye_core.config import get_settings

    monkeypatch.setattr(get_settings(), "log_group", "/eagleeye/demo")

    async def fake_recent(group: str, region: str, q: sl.LogQuery, client: object = None) -> list:
        assert (q.service, q.window, q.level, q.text) == ("api", "6h", "error", "boom")
        return [
            {
                "time": "t",
                "service": "api",
                "level": "ERROR",
                "logger": None,
                "message": "boom",
                "details": None,
            }
        ]

    monkeypatch.setattr(sl, "recent", fake_recent)
    data = _client().get("/v1/admin/logs?service=api&window=6h&level=error&q=boom").json()["data"]
    assert data["available"] is True and data["events"][0]["message"] == "boom"
