"""address -> geocode -> ground truth -> five drafts -> at-your-house draft ->
assemble -> verify -> validate -> cache.

In `full` mode the ground truth (facilities, utility, prices) is gathered first
and handed to every draft; in `agent` mode there is none and Spark drafts from
its own knowledge."""

import asyncio
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from app.brief.assemble import assemble_brief
from app.brief.cache import BriefCache, Inflight
from app.brief.draft import DraftResult, SectionFailure, draft_house_lines, draft_section
from app.brief.fetch import Fetcher
from app.brief.verify import verify_claims
from app.config import Settings
from app.geocode import Geocoder, GeocodeResult, brief_id_for
from app.ground import Ground, gather_ground
from app.llm.base import LLMProvider
from app.schema import SECTION_IDS, brief_errors
from app.telemetry import log_event

Progress = Callable[[dict], None]

# Reason on a section that has not been drafted yet in a partial brief.
DRAFTING = "Drafting…"


class AddressNotFound(Exception):
    pass


class DraftingUnavailable(Exception):
    pass


class BriefInvalid(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:5]))
        self.errors = errors


class BriefService:
    def __init__(
        self,
        *,
        settings: Settings,
        geocoder: Geocoder,
        draft_provider: LLMProvider,
        verify_provider: LLMProvider,
        fetcher: Fetcher,
        cache: BriefCache,
        ground: Ground | None = None,
    ) -> None:
        self.settings = settings
        self.ground = ground
        self.geocoder = geocoder
        self.draft_provider = draft_provider
        self.verify_provider = verify_provider
        self.fetcher = fetcher
        self.cache = cache
        self.inflight = Inflight()

    async def brief_for_address(self, address: str, progress: Progress | None = None) -> dict:
        """The finished brief. With `progress`, the caller also sees the brief
        take shape: a partial brief after the ground truth lands, again as each
        section is drafted, and a count as claims are checked. Only the first
        caller for an address gets the stages; a second concurrent request
        joins the same run and sees the result."""
        geo = await self.geocoder.geocode(address)
        if geo is None:
            raise AddressNotFound()
        brief_id = brief_id_for(geo.matched)
        cached = self.cache.get(brief_id)
        if cached is not None:
            log_event("brief_cache_hit", brief_id=brief_id)
            return cached
        return await self.inflight.run(brief_id, lambda: self._generate(geo, brief_id, progress))

    async def _generate(
        self, geo: GeocodeResult, brief_id: str, progress: Progress | None = None
    ) -> dict:
        started = time.monotonic()
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        verified = self.verify_provider is not None

        truth = await gather_ground(geo, self.ground) if self.ground is not None else None

        drafts: dict[str, DraftResult | SectionFailure] = {}

        def partial(stage: str) -> None:
            """Assemble what is known so far and hand it to the caller. Undrafted
            sections appear as unavailable with a 'drafting' reason; the page
            shows them as pending."""
            if progress is None:
                return
            filled: dict[str, DraftResult | SectionFailure] = {
                sid: drafts.get(sid, SectionFailure(sid, DRAFTING)) for sid in SECTION_IDS
            }
            brief = assemble_brief(
                geo,
                filled,
                None,
                brief_id=brief_id,
                now_iso=now_iso,
                verified=verified,
                truth=truth,
            )
            brief["partial"] = {
                "stage": stage,
                "pending": [sid for sid in SECTION_IDS if sid not in drafts],
                "drafted": len([d for d in drafts.values() if isinstance(d, DraftResult)]),
                "sections": len(SECTION_IDS),
            }
            progress({"stage": stage, "brief": brief})

        partial("ground")

        async def one_section(sid: str) -> None:
            try:
                r = await draft_section(self.draft_provider, sid, geo, now_iso, truth)
            except Exception as exc:  # noqa: BLE001  isolate it like any other failure
                log_event(
                    "draft_crashed", section=sid, kind=exc.__class__.__name__, reason=str(exc)[:200]
                )
                r = SectionFailure(sid, "The section could not be drafted.")
            drafts[sid] = r
            partial("drafting")

        # The strip reads the five summaries, so it normally runs after them. In
        # full mode its lines anchor to the facts block instead, and it runs in
        # parallel: that is a fifth of the wait.
        house: list[dict] | None = None
        if truth is not None:
            _, house = await asyncio.gather(
                asyncio.gather(*(one_section(sid) for sid in SECTION_IDS)),
                draft_house_lines(self.draft_provider, geo, now_iso, {}, truth),
            )
        else:
            await asyncio.gather(*(one_section(sid) for sid in SECTION_IDS))
        if all(isinstance(d, SectionFailure) for d in drafts.values()):
            raise DraftingUnavailable()
        if house is None:
            summaries = {sid: d.summary for sid, d in drafts.items() if isinstance(d, DraftResult)}
            house = await draft_house_lines(self.draft_provider, geo, now_iso, summaries, truth)

        brief = assemble_brief(
            geo,
            drafts,
            house,
            brief_id=brief_id,
            now_iso=now_iso,
            verified=verified,
            truth=truth,
        )
        total = len(brief["claims"])
        done = 0

        def on_verdict() -> None:
            nonlocal done
            done += 1
            if progress is not None:
                progress({"stage": "verifying", "verified": done, "claims": total})

        if progress is not None:
            progress({"stage": "verifying", "verified": 0, "claims": total})
        await verify_claims(
            self.verify_provider,
            self.fetcher,
            brief["claims"],
            concurrency=self.settings.verify_concurrency,
            verified_by=self.settings.verify_model,
            now_iso=now_iso,
            on_verdict=on_verdict,
        )

        errors = brief_errors(brief)
        if errors:
            log_event("brief_invalid", brief_id=brief_id, errors=errors[:10])
            raise BriefInvalid(errors)

        self.cache.put(brief)
        log_event(
            "brief",
            brief_id=brief_id,
            ms=int((time.monotonic() - started) * 1000),
            sections={sid: brief["sections"][sid]["status"] for sid in SECTION_IDS},
            claims=len(brief["claims"]),
            verdicts=dict(Counter(c["verdict"] for c in brief["claims"])),
        )
        return brief
