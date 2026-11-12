import logging
from collections.abc import AsyncIterator

import litellm

from eagleeye_llm.gateway import ChatMessage, StreamChunk, Tier, Usage

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True


class LiteLLMGateway:
    """LiteLLM adapter: provider selected purely by model id config (ADR-02/03)."""

    def __init__(self, model_fast: str, model_capable: str) -> None:
        self._models: dict[Tier, str] = {"fast": model_fast, "capable": model_capable}

    def _model(self, tier: Tier) -> str:
        return self._models[tier]

    async def stream(
        self, tier: Tier, messages: list[ChatMessage], max_tokens: int = 2048
    ) -> AsyncIterator[StreamChunk]:
        model = self._model(tier)
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        usage = Usage()
        async for chunk in response:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _to_usage(chunk_usage, model)
            choices = chunk.choices
            if choices and choices[0].delta and choices[0].delta.content:
                yield StreamChunk(text=choices[0].delta.content, model_id=model)
        yield StreamChunk(done=True, usage=usage, model_id=model)

    async def complete(
        self, tier: Tier, messages: list[ChatMessage], max_tokens: int = 1024
    ) -> tuple[str, Usage]:
        model = self._model(tier)
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
        )
        text = response.choices[0].message.content or ""
        return text, _to_usage(response.usage, model)


def _to_usage(raw: object, model: str) -> Usage:
    tokens_in = getattr(raw, "prompt_tokens", 0) or 0
    tokens_out = getattr(raw, "completion_tokens", 0) or 0
    try:
        cost = litellm.completion_cost(
            model=model, prompt_tokens=tokens_in, completion_tokens=tokens_out
        )
    except Exception:  # unknown model pricing — cost tracked as 0, logged once upstream
        logger.debug("no pricing for model %s", model)
        cost = 0.0
    return Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=round(cost, 6))
