"""address -> geocode -> ground truth -> five drafts -> at-your-house draft ->
assemble -> verify -> validate -> cache.

In `full` mode the ground truth (facilities, utility, prices) is gathered first
and handed to every draft; in `agent` mode there is none and Spark drafts from
its own knowledge."""

import asyncio
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.brief.assemble import assemble_brief
from app.brief.cache import BriefCache, Inflight
from app.brief.draft import DraftResult, SectionFailure, draft_house_lines, draft_section
from app.brief.fetch import Fetcher
from app.brief.verify import verify_claims
from app.config import Settings
from app.geocode import Geocoder, GeocodeResult, brief_id_for
from app.ground import Ground, gather_ground
from app.llm.base import LLMProvider
from app.regions.locale import US_LOCALE, Locale
from app.schema import SECTION_IDS, brief_errors
from app.telemetry import log_event

if TYPE_CHECKING:
    from app.regions import Region

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


@dataclass(frozen=True)
class Resolved:
    geo: GeocodeResult
    brief_id: str
    cached: dict | None  # a brief by the current engine, if there is one
    inflight: bool  # another request is making it right now


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
        region: "Region | None" = None,
    ) -> None:
        self.settings = settings
        self.ground = ground
        # The region pins the country of the brief id and the locale; None is the US.
        self.region = region
        self.geocoder = geocoder
        self.draft_provider = draft_provider
        self.verify_provider = verify_provider
        self.fetcher = fetcher
        self.cache = cache
        self.inflight = Inflight()

    @property
    def locale(self) -> Locale:
        return self.region.locale if self.region is not None else US_LOCALE

    @property
    def coverage(self) -> frozenset[str] | None:
        """The sections this region can make `measured`; None (no region) is all."""
        return self.region.coverage if self.region is not None else None

    async def resolve(self, address: str) -> Resolved:
        """Everything that costs no model tokens: geocode, derive the id, look
        in the cache. The router decides from this who may pay for the rest."""
        geo = await self.geocoder.geocode(address)
        if geo is None:
            raise AddressNotFound()
        # The country comes from the region, never the geocoder: a US id is unchanged.
        brief_id = brief_id_for(geo.matched, self.locale.country)
        cached = self.cache.get(brief_id, current_only=True)
        if cached is not None:
            log_event("brief_cache_hit", brief_id=brief_id)
        return Resolved(geo, brief_id, cached, self.inflight.running(brief_id))

    async def generate(self, resolved: Resolved, progress: Progress | None = None) -> dict:
        """The finished brief. With `progress`, the caller also sees the brief
        take shape: a partial brief after the ground truth lands, again as each
        section is drafted, and a count as claims are checked. Only the first
        caller for an address gets the stages; a second concurrent request
        joins the same run and sees the result."""
        if resolved.cached is not None:
            return resolved.cached
        geo, brief_id = resolved.geo, resolved.brief_id
        return await self.inflight.run(brief_id, lambda: self._generate(geo, brief_id, progress))

    async def brief_for_address(self, address: str, progress: Progress | None = None) -> dict:
        return await self.generate(await self.resolve(address), progress)

    async def _generate(
        self, geo: GeocodeResult, brief_id: str, progress: Progress | None = None
    ) -> dict:
        started = time.monotonic()
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        verified = self.verify_provider is not None

        on_step = None
        if progress is not None:
            emit = progress

            def on_step(name: str, state: str) -> None:
                emit({"stage": "gathering", "step": name, "state": state})

        truth = await gather_ground(geo, self.ground, on_step) if self.ground is not None else None

        drafts: dict[str, DraftResult | SectionFailure] = {}
        # With an indexed transcript the Hearing section is the engine's: no draft.
        engine_sections = {"hearing"} if truth is not None and truth.hearing else set()
        for sid in engine_sections:
            drafts[sid] = SectionFailure(sid, "Written by the engine from the transcript.")

        # The strip's model lines, once drafted; a partial brief carries them as
        # soon as they land, so the page fills its tiles while sections draft.
        house: list[dict] | None = None

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
                house,
                brief_id=brief_id,
                now_iso=now_iso,
                verified=verified,
                truth=truth,
                public_base_url=self.settings.public_base_url,
                locale=self.locale,
                coverage=self.coverage,
            )
            brief["partial"] = {
                "stage": stage,
                "pending": [sid for sid in SECTION_IDS if sid not in drafts],
                "drafted": len([d for d in drafts.values() if isinstance(d, DraftResult)]),
                "sections": len(SECTION_IDS),
                "house": house is not None,
            }
            progress({"stage": stage, "brief": brief})

        partial("ground")

        async def one_section(sid: str) -> None:
            try:
                r = await draft_section(
                    self.draft_provider, sid, geo, now_iso, truth, locale=self.locale
                )
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
        to_draft = [sid for sid in SECTION_IDS if sid not in engine_sections]

        async def house_lines() -> None:
            nonlocal house
            house = await draft_house_lines(
                self.draft_provider, geo, now_iso, {}, truth, locale=self.locale
            )
            partial("drafting")

        if truth is not None:
            await asyncio.gather(
                asyncio.gather(*(one_section(sid) for sid in to_draft)), house_lines()
            )
        else:
            await asyncio.gather(*(one_section(sid) for sid in to_draft))
        if all(isinstance(drafts.get(sid), SectionFailure) for sid in to_draft):
            raise DraftingUnavailable()
        if house is None:
            summaries = {sid: d.summary for sid, d in drafts.items() if isinstance(d, DraftResult)}
            house = await draft_house_lines(
                self.draft_provider, geo, now_iso, summaries, truth, locale=self.locale
            )

        brief = assemble_brief(
            geo,
            drafts,
            house,
            brief_id=brief_id,
            now_iso=now_iso,
            verified=verified,
            truth=truth,
            public_base_url=self.settings.public_base_url,
            locale=self.locale,
            coverage=self.coverage,
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
