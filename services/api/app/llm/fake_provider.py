"""Scriptable fake providers for tests and keyless local dev.

With no scripted response they raise LLMError, so a draft becomes an
`unavailable` section and a verification becomes `unverifiable`.
"""

from typing import Any

from app.llm.base import LLMError


class FakeProvider:
    """Responses consumed in order."""

    model = "fake"

    def __init__(self, responses: list[dict[str, Any] | Exception] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append((schema_name, messages))
        if not self._responses:
            raise LLMError("fake provider has no scripted response")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class KeyedFakeProvider:
    """Responses keyed by schema name, so five parallel section drafts each get
    theirs regardless of completion order. A missing key raises LLMError."""

    model = "fake"

    def __init__(self, responses: dict[str, dict[str, Any] | Exception] | None = None) -> None:
        self._responses = dict(responses or {})
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append((schema_name, messages))
        if schema_name not in self._responses:
            raise LLMError(f"fake provider has no response for {schema_name}")
        item = self._responses[schema_name]
        if isinstance(item, Exception):
            raise item
        return item
