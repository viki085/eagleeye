"""The one place that picks the model and embedder implementations from settings.

LLM_PROVIDER=stub gives the load-test stand-ins (eagleeye_llm.stub). Settings refuses that value
unless APP_ENV=loadtest, so a real deployment can never answer users with canned text.
"""

from eagleeye_core.config import LOADTEST_ENV, Settings

from eagleeye_llm.embeddings import Embedder, LiteLLMEmbedder
from eagleeye_llm.gateway import LLMGateway
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from eagleeye_llm.stub import StubEmbedder, StubLLM

STUB_PROVIDER = "stub"


def _stub_allowed(s: Settings) -> bool:
    if s.llm_provider != STUB_PROVIDER:
        return False
    if s.app_env != LOADTEST_ENV:  # Settings already refuses this; checked again on purpose
        raise RuntimeError("LLM_PROVIDER=stub is only allowed when APP_ENV=loadtest")
    return True


def build_llm(s: Settings, fallbacks: bool = True) -> LLMGateway:
    if _stub_allowed(s):
        return StubLLM()
    return LiteLLMGateway(
        s.model_fast,
        s.model_capable,
        s.model_fast_fallback if fallbacks else "",
        s.model_capable_fallback if fallbacks else "",
        reasoning_fast=s.reasoning_effort_fast,
        reasoning_capable=s.reasoning_effort_capable,
    )


def build_embedder(s: Settings) -> Embedder:
    if _stub_allowed(s):
        return StubEmbedder(s.embed_dim)
    return LiteLLMEmbedder(s.embed_model, s.embed_dim)
