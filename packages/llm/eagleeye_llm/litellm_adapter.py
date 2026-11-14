import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import litellm

from eagleeye_llm.gateway import ChatMessage, StreamChunk, Tier, ToolCall, ToolSpec, Usage
from eagleeye_llm.resilience import CircuitOpenError, ModelGuards, counts_as_provider_failure

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True

NUM_RETRIES = 2
REQUEST_TIMEOUT_S = 60.0  # per request; a hung provider call must not stall a run forever
_unpriced_models: set[str] = set()


def to_wire(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """Provider-neutral OpenAI-style message dicts (LiteLLM translates per provider)."""
    wire: list[dict[str, Any]] = []
    for m in messages:
        msg: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments_json},
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id is not None:
            msg["tool_call_id"] = m.tool_call_id
        wire.append(msg)
    return wire


def tool_schemas(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


class ToolCallAssembler:
    """Streamed tool calls arrive as fragments keyed by index; join them."""

    def __init__(self) -> None:
        self._parts: dict[int, dict[str, str]] = {}

    def add(self, deltas: Any) -> None:
        for d in deltas or []:
            idx = getattr(d, "index", 0) or 0
            part = self._parts.setdefault(idx, {"id": "", "name": "", "args": ""})
            if getattr(d, "id", None):
                part["id"] = d.id
            fn = getattr(d, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    part["name"] += fn.name
                if getattr(fn, "arguments", None):
                    part["args"] += fn.arguments

    def calls(self) -> tuple[ToolCall, ...]:
        return tuple(
            ToolCall(id=p["id"] or f"call_{i}", name=p["name"], arguments_json=p["args"] or "{}")
            for i, p in sorted(self._parts.items())
            if p["name"]
        )


class LiteLLMGateway:
    """LiteLLM adapter: provider selected purely by model id config (ADR-02/03).

    Each tier may have a fallback model; a call that fails on the primary after
    retries is retried once on the fallback and its usage is marked `degraded`.
    """

    def __init__(
        self,
        model_fast: str,
        model_capable: str,
        fallback_fast: str = "",
        fallback_capable: str = "",
        price_reference_model: str | None = None,
        reasoning_fast: str = "",
        reasoning_capable: str = "",
        guards: ModelGuards | None = None,
    ) -> None:
        self._models: dict[Tier, str] = {"fast": model_fast, "capable": model_capable}
        self._fallbacks: dict[Tier, str] = {"fast": fallback_fast, "capable": fallback_capable}
        self._price_ref = price_reference_model or model_capable
        self._efforts: dict[Tier, str] = {"fast": reasoning_fast, "capable": reasoning_capable}
        self._guards = guards or ModelGuards()

    def _candidates(self, tier: Tier) -> list[tuple[str, bool]]:
        """Models to try in order, skipping any whose circuit breaker is open."""
        primary = [(self._models[tier], False)]
        fallback = self._fallbacks[tier]
        allowed = [
            (model, degraded)
            for model, degraded in primary + ([(fallback, True)] if fallback else [])
            if self._guards.breaker(model).available()
        ]
        if not allowed:
            raise CircuitOpenError(f"all models for tier '{tier}' are temporarily unavailable")
        if allowed[0][0] != self._models[tier]:
            logger.warning("circuit open for %s; using fallback %s", self._models[tier], fallback)
        return allowed

    def _claim(self, model: str, last: bool) -> bool:
        """Claims a call slot (the probe in half-open). If another request just took the
        probe, try the next candidate; with none left, fail fast."""
        if self._guards.breaker(model).allow():
            return True
        if last:
            raise CircuitOpenError(f"model {model} is temporarily unavailable")
        return False

    def _failed(self, model: str, exc: BaseException) -> None:
        if counts_as_provider_failure(exc):
            self._guards.breaker(model).record_failure()
        else:  # the request itself was bad; the provider answered, so it is healthy
            self._guards.breaker(model).record_success()

    def breaker_states(self) -> dict[str, str]:
        return dict(self._guards.states())

    def _model_params(self, tier: Tier, model: str, temperature: float | None) -> dict[str, Any]:
        """Per-model knobs. Reasoning models (GPT-5/6, o-series) take `reasoning_effort` and
        reject a non-default temperature unless reasoning is off; classic models ignore effort."""
        params: dict[str, Any] = {}
        effort = self._efforts[tier]
        reasoning = is_reasoning_model(model)
        if reasoning and effort:
            params["reasoning_effort"] = effort
        if temperature is not None and (not reasoning or effort == "none"):
            params["temperature"] = temperature
        return params

    async def stream(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        max_tokens: int = 2048,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        candidates = self._candidates(tier)
        for i, (model, degraded) in enumerate(candidates):
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": to_wire(messages),
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
                "num_retries": NUM_RETRIES,
                "timeout": REQUEST_TIMEOUT_S,
                **self._model_params(tier, model, None),
            }
            if tools:
                kwargs["tools"] = tool_schemas(tools)
            if not self._claim(model, i == len(candidates) - 1):
                continue
            async with self._guards.semaphore(model):
                try:
                    response = await litellm.acompletion(**kwargs)
                except Exception as exc:
                    self._failed(model, exc)
                    if i == len(candidates) - 1:
                        raise
                    logger.warning("model %s failed; falling back", model, exc_info=True)
                    continue
                try:
                    async for chunk in self._consume(response, model, degraded):
                        yield chunk
                except Exception as exc:  # mid-stream: text already sent, no fallback possible
                    self._failed(model, exc)
                    raise
                self._guards.breaker(model).record_success()
            return

    async def _consume(
        self, response: Any, model: str, degraded: bool
    ) -> AsyncIterator[StreamChunk]:
        usage = Usage(model_id=model, degraded=degraded)
        assembler = ToolCallAssembler()
        async for chunk in response:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = self._to_usage(chunk_usage, model, degraded)
            choices = getattr(chunk, "choices", None) or []
            if not choices or choices[0].delta is None:
                continue
            delta = choices[0].delta
            assembler.add(getattr(delta, "tool_calls", None))
            if delta.content:
                yield StreamChunk(text=delta.content, model_id=model)
        yield StreamChunk(done=True, usage=usage, model_id=model, tool_calls=assembler.calls())

    async def complete(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        max_tokens: int = 1024,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> tuple[str, Usage]:
        candidates = self._candidates(tier)
        for i, (model, degraded) in enumerate(candidates):
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": to_wire(messages),
                "max_tokens": max_tokens,
                "num_retries": NUM_RETRIES,
                "timeout": REQUEST_TIMEOUT_S,
                **self._model_params(tier, model, temperature),
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if not self._claim(model, i == len(candidates) - 1):
                continue
            async with self._guards.semaphore(model):
                try:
                    response = await litellm.acompletion(**kwargs)
                except Exception as exc:
                    self._failed(model, exc)
                    if i == len(candidates) - 1:
                        raise
                    logger.warning("model %s failed; falling back", model, exc_info=True)
                    continue
            self._guards.breaker(model).record_success()
            text = response.choices[0].message.content or ""
            return text, self._to_usage(response.usage, model, degraded)
        raise RuntimeError("no model candidates configured")  # unreachable

    def _to_usage(self, raw: object, model: str, degraded: bool) -> Usage:
        tokens_in = getattr(raw, "prompt_tokens", 0) or 0
        tokens_out = getattr(raw, "completion_tokens", 0) or 0
        cost = price(model, tokens_in, tokens_out, self._price_ref)
        return Usage(tokens_in, tokens_out, round(cost, 6), model, degraded, cached_tokens(raw))


def cached_tokens(raw: object) -> int:
    """Prompt-cache hits: OpenAI reports prompt_tokens_details.cached_tokens, Anthropic
    cache_read_input_tokens; missing or malformed fields count as 0."""
    details = getattr(raw, "prompt_tokens_details", None)
    value = getattr(details, "cached_tokens", None) if details is not None else None
    if value is None:
        value = getattr(raw, "cache_read_input_tokens", None)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def is_reasoning_model(model: str) -> bool:
    try:
        return bool(litellm.supports_reasoning(model=model))
    except Exception:  # unknown model: treat as classic (no effort, temperature allowed)
        return False


def price(model: str, tokens_in: int, tokens_out: int, reference_model: str) -> float:
    """Unknown pricing is charged at the reference (capable) model's rate: budgets stay safe."""
    for candidate in (model, reference_model):
        try:
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=candidate, prompt_tokens=tokens_in, completion_tokens=tokens_out
            )
            return float(prompt_cost) + float(completion_cost)
        except Exception:  # noqa: S112 - try the next pricing source
            if candidate not in _unpriced_models:
                _unpriced_models.add(candidate)
                logger.warning("no pricing for model %s", candidate)
            continue
    logger.error("no pricing for %s or reference %s; cost budget is blind", model, reference_model)
    return 0.0
