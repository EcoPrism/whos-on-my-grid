"""OpenAI-protocol structured-output provider.

Every OpenAI SDK quirk lives here and nowhere else. Used twice: pointed at the
Betahub LLM Gateway (virtual key + model alias) for drafting, and at Baseten
for the verifier. Copied from lookupsoccer and parametrised.
"""

import json
import re
import time
from typing import Any

from openai import APIError, AsyncOpenAI

from app.llm.base import LLMError
from app.telemetry import log_event

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        label: str,
        max_tokens: int,
        timeout: float,
        headers: dict[str, str] | None = None,
        strict_json_schema: bool = True,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key or "missing",
            base_url=base_url or None,
            default_headers=headers or {},
        )
        self.model = model
        self.label = label
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._strict = strict_json_schema

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        if self._strict:
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
            sent = messages
        else:
            # Prompt-carried schema for endpoints that do not honour json_schema.
            response_format = {"type": "json_object"}
            sent = [
                *messages,
                {
                    "role": "system",
                    "content": "Respond with one JSON object and nothing else. It must match "
                    "this JSON schema exactly:\n" + json.dumps(schema),
                },
            ]
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=sent,  # type: ignore[arg-type]
                max_tokens=max_tokens or self._max_tokens,
                timeout=self._timeout,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except APIError as exc:
            raise LLMError(f"{self.label} API error: {exc}") from exc
        except Exception as exc:  # timeouts, connection errors
            raise LLMError(f"{self.label} call failed: {exc.__class__.__name__}: {exc}") from exc

        # One line per completion, token counts straight from the endpoint.
        if getattr(response, "usage", None) is not None:
            log_event(
                "llm",
                label=self.label,
                schema=schema_name,
                model=self.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                ms=int((time.monotonic() - started) * 1000),
            )

        if not response.choices:
            raise LLMError(f"{self.label}: no choices in completion")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise LLMError(f"{self.label}: output truncated (finish_reason=length)")
        if getattr(choice.message, "refusal", None):
            raise LLMError(f"{self.label}: model refused: {choice.message.refusal}")
        content = choice.message.content
        if not content:
            raise LLMError(f"{self.label}: empty completion")
        m = _FENCE.match(content)
        if m:
            content = m.group(1)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self.label}: non-JSON completion: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMError(f"{self.label}: completion is not a JSON object")
        return parsed
