"""One Spark call per section. A failed draft is a SectionFailure, which the
assembler turns into an `unavailable` section with the reason in `gap`."""

from dataclasses import dataclass, field
from typing import Any

from app.brief.prompts import house_prompt, house_system_prompt, section_prompt, system_prompt
from app.geocode import GeocodeResult
from app.ground.types import GroundTruth
from app.llm.base import LLMError, LLMProvider
from app.schema import (
    SECTION_EXTRA,
    ValidationError,
    draft_schemas,
    house_schemas,
    validate_draft,
    validate_house_draft,
)
from app.telemetry import log_event


@dataclass
class DraftResult:
    section_id: str
    confidence: float
    summary: str
    gap: str | None
    card_line: str | None
    extra: dict[str, Any] = field(default_factory=dict)  # {"facilities": [...]} etc.
    claims: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SectionFailure:
    section_id: str
    reason: str


ATTEMPTS = 2


async def draft_section(
    provider: LLMProvider,
    section_id: str,
    geo: GeocodeResult,
    now_iso: str,
    truth: GroundTruth | None = None,
) -> DraftResult | SectionFailure:
    _, strict = draft_schemas(section_id)
    messages = [
        {"role": "system", "content": system_prompt(now_iso)},
        {"role": "user", "content": section_prompt(section_id, geo, truth)},
    ]
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            raw = await provider.complete_structured(messages, strict, f"draft_{section_id}")
            draft = validate_draft(section_id, raw)
            break
        except (LLMError, ValidationError) as exc:
            last = exc
            log_event(
                "draft_failed",
                section=section_id,
                attempt=attempt,
                kind=exc.__class__.__name__,
                reason=str(exc)[:200],
            )
    else:
        return SectionFailure(section_id, _reason(last))

    prop = SECTION_EXTRA[section_id][0]
    return DraftResult(
        section_id=section_id,
        confidence=float(draft["confidence"]),
        summary=draft["summary"],
        gap=draft.get("gap"),
        card_line=draft.get("card_line"),
        extra={prop: draft[prop]},
        claims=list(draft.get("claims", [])),
    )


async def draft_house_lines(
    provider: LLMProvider,
    geo: GeocodeResult,
    now_iso: str,
    summaries: dict[str, str],
    truth: GroundTruth | None = None,
) -> list[dict[str, Any]]:
    """The model's part of the at-your-house strip: two or three lines, each
    with its claims. Drafted after the sections, from their summaries. A
    failure leaves the strip to the bill sentence alone; nothing else breaks."""
    _, strict = house_schemas()
    messages = [
        {"role": "system", "content": house_system_prompt(now_iso)},
        {"role": "user", "content": house_prompt(geo, summaries, truth)},
    ]
    for attempt in range(1, ATTEMPTS + 1):
        try:
            raw = await provider.complete_structured(messages, strict, "draft_at_your_house")
            return list(validate_house_draft(raw)["lines"])
        except (LLMError, ValidationError) as exc:
            log_event(
                "draft_failed",
                section="at_your_house",
                attempt=attempt,
                kind=exc.__class__.__name__,
                reason=str(exc)[:200],
            )
    return []


def _reason(exc: Exception | None) -> str:
    if isinstance(exc, ValidationError):
        return "The model's draft did not fit the brief contract, so it was not used."
    if isinstance(exc, LLMError):
        text = str(exc)
        if "truncated" in text:
            return "The model ran out of room before finishing this section."
        if "timed out" in text.lower() or "Timeout" in text:
            return "The model did not answer in time."
        return "The drafting model was unavailable."
    return "The section could not be drafted."
