"""Independent verification of every claim: fetch the cited page, then ask
Muse Spark Open whether the page supports the claim. Verdicts are written
back onto the claim objects in place.

No fetch, no verdict from the model: a page that cannot be read is
`unverifiable` with the reason, and the model is not consulted.

No verifier configured (provider is None): nothing is fetched and every claim
stays `unchecked` with a note saying so, so the brief is honest about it.
"""

import asyncio
import re
from typing import Any

from app.brief.fetch import Fetcher, FetchResult
from app.brief.prompts import verifier_prompt, verifier_system_prompt
from app.llm.base import LLMError, LLMProvider
from app.schema import VERDICT_SCHEMA
from app.telemetry import log_event

WINDOW_CHARS = 12_000
VERDICTS = {"supported", "contradicted", "unverifiable"}
UNCHECKED_NOTE = "Not checked: no verifier is configured for this deployment."

_WS = re.compile(r"\s+")


def find_quote(text: str, quote: str) -> int | None:
    """Case- and whitespace-insensitive position of the quote in the text."""
    q = _WS.sub(" ", quote).strip().lower()
    if len(q) < 12:
        return None
    t = _WS.sub(" ", text).lower()
    i = t.find(q)
    return i if i >= 0 else None


def window(text: str, at: int | None) -> str:
    flat = _WS.sub(" ", text)
    if at is None:
        return flat[:WINDOW_CHARS]
    start = max(0, at - WINDOW_CHARS // 2)
    return flat[start : start + WINDOW_CHARS]


async def verify_claims(
    provider: LLMProvider | None,
    fetcher: Fetcher,
    claims: list[dict[str, Any]],
    *,
    concurrency: int,
    verified_by: str,
    now_iso: str,
) -> None:
    if provider is None:
        for claim in claims:
            claim["verdict"] = "unchecked"
            claim["verified_by"] = None
            claim["verifier_note"] = UNCHECKED_NOTE
        log_event("verify_skipped", claims=len(claims))
        return
    sem = asyncio.Semaphore(max(1, concurrency))
    fetches: dict[str, asyncio.Task[FetchResult]] = {}

    def fetch_once(url: str) -> asyncio.Task[FetchResult]:
        if url not in fetches:
            fetches[url] = asyncio.ensure_future(fetcher.fetch(url))
        return fetches[url]

    async def one(claim: dict[str, Any]) -> None:
        async with sem:
            src = claim["source"]
            src["retrieved_at"] = now_iso
            page = await fetch_once(src["url"])
            if not page.ok:
                _unverifiable(claim, f"Could not read the source: {page.note}.")
                return
            quote = src.get("quote") or ""
            at = find_quote(page.text, quote) if quote else None
            messages = [
                {"role": "system", "content": verifier_system_prompt()},
                {
                    "role": "user",
                    "content": verifier_prompt(
                        claim["text"], quote, src["url"], at is not None, window(page.text, at)
                    ),
                },
            ]
            try:
                result = await provider.complete_structured(messages, VERDICT_SCHEMA, "verdict")
            except LLMError as exc:
                log_event("verify_failed", claim=claim["id"], reason=str(exc)[:200])
                _unverifiable(claim, "The verifier was unavailable, so this claim is unchecked.")
                return
            verdict = result.get("verdict")
            claim["verdict"] = verdict if verdict in VERDICTS else "unverifiable"
            claim["verified_by"] = verified_by
            note = str(result.get("note") or "").strip()
            if quote and at is None:
                note = f"{note} The quoted text was not found verbatim on the page.".strip()
            claim["verifier_note"] = note or None

    await asyncio.gather(*(one(c) for c in claims))


def _unverifiable(claim: dict[str, Any], note: str) -> None:
    """A verdict the model did not give: no verifier is credited."""
    claim["verdict"] = "unverifiable"
    claim["verified_by"] = None
    claim["verifier_note"] = note
