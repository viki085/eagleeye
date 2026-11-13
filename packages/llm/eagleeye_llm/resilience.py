"""Provider resilience (C3 §5): a circuit breaker and a concurrency cap per model.

Breaker: CLOSED → (5 provider failures within 30 s) → OPEN → (after 30 s) HALF_OPEN, which lets
one probe through: success closes it, failure re-opens it. While a model's breaker is open the
gateway skips it and goes straight to the fallback, instead of spending retries on a dead
provider. Bad requests (e.g. context too long) are the caller's fault and don't count.
"""

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import Literal

State = Literal["closed", "open", "half_open"]

FAILURE_THRESHOLD = 5
FAILURE_WINDOW_S = 30.0
OPEN_COOLDOWN_S = 30.0


class CircuitOpenError(RuntimeError):
    """Every candidate model's breaker is open."""


def counts_as_provider_failure(exc: BaseException) -> bool:
    """Rate limits, timeouts, 5xx and connection errors count; malformed requests don't."""
    import litellm

    bad_request = getattr(litellm, "BadRequestError", None)
    return not (bad_request is not None and isinstance(exc, bad_request))


class CircuitBreaker:
    def __init__(
        self,
        threshold: int = FAILURE_THRESHOLD,
        window_s: float = FAILURE_WINDOW_S,
        cooldown_s: float = OPEN_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._window_s = window_s
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._failures: deque[float] = deque()
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> State:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._cooldown_s:
            return "half_open"
        return "open"

    def available(self) -> bool:
        """Side-effect free: could a call be attempted now?"""
        state = self.state
        return state == "closed" or (state == "half_open" and not self._probe_in_flight)

    def allow(self) -> bool:
        """Claims the right to call now (in half-open, the single probe slot). Call only
        right before actually calling the model."""
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._probe_in_flight:
            self._probe_in_flight = True  # exactly one probe at a time
            return True
        return False

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self) -> None:
        now = self._clock()
        if self._probe_in_flight or self.state != "closed":
            self._opened_at = now  # failed probe: open again for a full cooldown
            self._probe_in_flight = False
            return
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self._window_s:
            self._failures.popleft()
        if len(self._failures) >= self._threshold:
            self._opened_at = now
            self._failures.clear()


class ModelGuards:
    """One breaker and one semaphore per model id, created on first use."""

    def __init__(self, max_concurrency: int = 32, clock: Callable[[], float] = time.monotonic):
        self._max = max_concurrency
        self._clock = clock
        self._breakers: dict[str, CircuitBreaker] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def breaker(self, model: str) -> CircuitBreaker:
        if model not in self._breakers:
            self._breakers[model] = CircuitBreaker(clock=self._clock)
        return self._breakers[model]

    def semaphore(self, model: str) -> asyncio.Semaphore:
        if model not in self._semaphores:
            self._semaphores[model] = asyncio.Semaphore(self._max)
        return self._semaphores[model]

    def states(self) -> dict[str, State]:
        return {model: b.state for model, b in self._breakers.items()}
