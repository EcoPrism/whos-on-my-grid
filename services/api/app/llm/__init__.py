"""LLM provider seam. Two providers: the drafter (Muse Spark via the gateway)
and the verifier (Muse Spark Open on Baseten). Both speak the OpenAI protocol,
so one class serves both, parametrised. The verifier is optional: with no
Baseten key there is no verify provider and claims stay `unchecked`."""

from app.config import get_settings
from app.llm.base import LLMError, LLMProvider
from app.llm.fake_provider import FakeProvider, KeyedFakeProvider


def get_draft_provider() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
            model=s.draft_model,
            label="draft",
            max_tokens=s.llm_max_tokens,
            timeout=s.llm_timeout_seconds,
            headers={
                "x-betahub-team": "grid",
                "x-betahub-app": "grid",
                "x-betahub-feature": "draft",
            },
        )
    return FakeProvider()


def get_verify_provider() -> LLMProvider | None:
    s = get_settings()
    if s.llm_provider == "openai":
        if not s.baseten_api_key:
            return None
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=s.baseten_api_key,
            base_url=s.baseten_base_url,
            model=s.verify_model,
            label="verify",
            max_tokens=s.verify_max_tokens,
            timeout=s.verify_timeout_seconds,
            strict_json_schema=s.verify_strict_json,
        )
    return FakeProvider()


__all__ = [
    "FakeProvider",
    "KeyedFakeProvider",
    "LLMError",
    "LLMProvider",
    "get_draft_provider",
    "get_verify_provider",
]
