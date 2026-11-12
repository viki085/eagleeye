import json

import pytest
from eagleeye_events import EventSink, read_events, stream_key


class FakeRedis:
    def __init__(self) -> None:
        self.entries: list[tuple[str, dict]] = []
        self.expirations: list[tuple[str, int]] = []
        self.xread_response: list = []

    async def xadd(self, key: str, payload: dict) -> None:
        self.entries.append((key, payload))

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations.append((key, ttl))

    async def xread(self, streams: dict, block: int, count: int) -> list:
        return self.xread_response


@pytest.mark.asyncio
async def test_sink_stamps_gapless_seq() -> None:
    redis = FakeRedis()
    sink = EventSink(redis, "r1")
    await sink.emit("run.started", {"run_id": "r1"})
    await sink.emit("text.delta", {"text": "hi"})
    await sink.emit("run.done", {})
    seqs = [p["seq"] for _k, p in redis.entries]
    assert seqs == [0, 1, 2]
    assert all(k == stream_key("r1") for k, _p in redis.entries)


@pytest.mark.asyncio
async def test_sink_sets_ttl_once() -> None:
    redis = FakeRedis()
    sink = EventSink(redis, "r1")
    await sink.emit("a", {})
    await sink.emit("b", {})
    assert len(redis.expirations) == 1


@pytest.mark.asyncio
async def test_read_events_decodes_bytes_entries() -> None:
    redis = FakeRedis()
    redis.xread_response = [
        (
            b"run:r1:events",
            [
                (
                    b"1-0",
                    {
                        b"seq": b"0",
                        b"event": b"text.delta",
                        b"data": json.dumps({"text": "hello"}).encode(),
                    },
                )
            ],
        )
    ]
    events, last_id = await read_events(redis, "r1", "0")
    assert last_id == "1-0"
    assert events == [("1-0", 0, "text.delta", {"text": "hello"})]


@pytest.mark.asyncio
async def test_read_events_empty_is_heartbeat_window() -> None:
    events, last_id = await read_events(FakeRedis(), "r1", "5-0")
    assert events == []
    assert last_id == "5-0"
