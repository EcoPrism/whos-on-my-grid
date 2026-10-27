from typing import Any, Protocol


class LLMError(Exception):
    """Provider-level failure: API error, refusal, truncated or non-JSON output.

    A failed draft makes its section `unavailable`; a failed verification makes
    its claim `unverifiable`. Never a 500.
    """


class LLMProvider(Protocol):
    model: str

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Return a dict conforming to the JSON schema, or raise LLMError."""
        ...
