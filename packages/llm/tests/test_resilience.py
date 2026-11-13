import asyncio
from types import SimpleNamespace

import litellm
import pytest
from eagleeye_llm import litellm_adapter as adapter
from eagleeye_llm.gateway import ChatMessage
from eagleeye_llm.resilience import CircuitBreaker, CircuitOpenError, ModelGuards


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_breaker_opens_after_threshold_within_window() -> None:
    clock = Clock()
    b = CircuitBreaker(threshold=3, window_s=30, cooldown_s=30, clock=clock)
    for _ in range(2):
        b.record_failure()
    assert b.state == "closed"
    b.record_failure()
    assert b.state == "open" and not b.available() and not b.allow()


def test_old_failures_fall_out_of_the_window() -> None:
    clock = Clock()
    b = CircuitBreaker(threshold=3, window_s=30, cooldown_s=30, clock=clock)
    b.record_failure()
    b.record_failure()
    clock.t += 31
    b.record_failure()
    assert b.state == "closed"


def test_half_open_allows_exactly_one_probe() -> None:
    clock = Clock()
    b = CircuitBreaker(threshold=1, window_s=30, cooldown_s=30, clock=clock)
    b.record_failure()
    clock.t += 30
    assert b.state == "half_open" and b.available()
    assert b.allow() is True
    assert b.available() is False and b.allow() is False  # second request must wait


def test_probe_success_closes_and_failure_reopens() -> None:
    clock = Clock()
    b = CircuitBreaker(threshold=1, window_s=30, cooldown_s=30, clock=clock)
    b.record_failure()
    clock.t += 30
    b.allow()
    b.record_failure()
    assert b.state == "open"
    clock.t += 30
    b.allow()
    b.record_success()
    assert b.state == "closed" and b.allow()


def _response(text: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def _gateway(guards: ModelGuards) -> adapter.LiteLLMGateway:
    return adapter.LiteLLMGateway("primary", "cap", fallback_fast="backup", guards=guards)


async def test_open_breaker_skips_straight_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    async def fake(**kw):  # noqa: ANN003, ANN202
        called.append(kw["model"])
        if kw["model"] == "primary":
            raise litellm.RateLimitError("slow down", llm_provider="openai", model="primary")
        return _response("from backup")

    monkeypatch.setattr(adapter.litellm, "acompletion", fake)
    monkeypatch.setattr(adapter, "price", lambda *a: 0.0)
    guards = ModelGuards()
    gw = _gateway(guards)
    for _ in range(5):
        text, usage = await gw.complete("fast", [ChatMessage("user", "x")])
        assert text == "from backup" and usage.degraded
    assert guards.breaker("primary").state == "open"
    called.clear()
    await gw.complete("fast", [ChatMessage("user", "x")])
    assert called == ["backup"]  # no time wasted on the dead primary


async def test_bad_requests_do_not_open_the_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(**kw):  # noqa: ANN003, ANN202
        raise litellm.BadRequestError("context too long", model="primary", llm_provider="openai")

    monkeypatch.setattr(adapter.litellm, "acompletion", fake)
    guards = ModelGuards()
    gw = adapter.LiteLLMGateway("primary", "cap", guards=guards)
    for _ in range(6):
        with pytest.raises(litellm.BadRequestError):
            await gw.complete("fast", [ChatMessage("user", "x")])
    assert guards.breaker("primary").state == "closed"


async def test_all_breakers_open_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    guards = ModelGuards()
    for model in ("primary", "backup"):
        for _ in range(5):
            guards.breaker(model).record_failure()
    with pytest.raises(CircuitOpenError):
        await _gateway(guards).complete("fast", [ChatMessage("user", "x")])


async def test_unused_fallback_keeps_its_probe_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    guards = ModelGuards(clock=clock)
    for _ in range(5):
        guards.breaker("backup").record_failure()
    clock.t += 30  # backup half-open; primary healthy

    async def fake(**kw):  # noqa: ANN003, ANN202
        return _response()

    monkeypatch.setattr(adapter.litellm, "acompletion", fake)
    monkeypatch.setattr(adapter, "price", lambda *a: 0.0)
    await _gateway(guards).complete("fast", [ChatMessage("user", "x")])
    assert guards.breaker("backup").available()  # regression: candidate listing used to claim it


async def test_semaphore_caps_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    active, peak = 0, 0

    async def fake(**kw):  # noqa: ANN003, ANN202
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _response()

    monkeypatch.setattr(adapter.litellm, "acompletion", fake)
    monkeypatch.setattr(adapter, "price", lambda *a: 0.0)
    gw = adapter.LiteLLMGateway("primary", "cap", guards=ModelGuards(max_concurrency=2))
    await asyncio.gather(*(gw.complete("fast", [ChatMessage("user", "x")]) for _ in range(8)))
    assert peak == 2
