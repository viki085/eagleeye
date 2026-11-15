"""Scale mode: queued + running answers published to CloudWatch for agent-worker autoscaling."""

import asyncio

from app.services import queue_metric as qm


class FakePool:
    def __init__(self, n: int, fail: bool = False) -> None:
        self.n, self.fail = n, fail
        self.sql = ""

    async def fetchval(self, sql: str) -> int:
        if self.fail:
            raise OSError("db down")
        self.sql = sql
        return self.n


class FakeCloudWatch:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_metric_data(self, **kw: object) -> None:
        self.calls.append(kw)


def test_counts_queued_and_running_answers() -> None:
    pool = FakePool(7)
    assert asyncio.run(qm.active_answers(pool)) == 7
    assert "QUEUED" in pool.sql and "RUNNING" in pool.sql


def test_publishes_one_datapoint_in_the_namespace() -> None:
    cw = FakeCloudWatch()
    asyncio.run(qm.publish_once(FakePool(3), cw, "EagleEye/loadtest"))
    (call,) = cw.calls
    assert call["Namespace"] == "EagleEye/loadtest"
    (datum,) = call["MetricData"]
    assert datum["MetricName"] == qm.METRIC and datum["Value"] == 3.0 and datum["Unit"] == "Count"


def test_a_failed_count_publishes_nothing() -> None:
    cw = FakeCloudWatch()
    assert asyncio.run(qm.publish_once(FakePool(0, fail=True), cw, "EagleEye")) is False
    assert cw.calls == []
