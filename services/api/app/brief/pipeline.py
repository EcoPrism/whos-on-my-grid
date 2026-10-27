"""address -> geocode -> five drafts -> assemble -> verify -> validate -> cache."""

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime

from app.brief.assemble import assemble_brief
from app.brief.cache import BriefCache, Inflight
from app.brief.draft import DraftResult, SectionFailure, draft_section
from app.brief.fetch import Fetcher
from app.brief.verify import verify_claims
from app.config import Settings
from app.geocode import Geocoder, GeocodeResult, brief_id_for
from app.llm.base import LLMProvider
from app.schema import SECTION_IDS, brief_errors
from app.telemetry import log_event


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
    ) -> None:
        self.settings = settings
        self.geocoder = geocoder
        self.draft_provider = draft_provider
        self.verify_provider = verify_provider
        self.fetcher = fetcher
        self.cache = cache
        self.inflight = Inflight()

    async def brief_for_address(self, address: str) -> dict:
        geo = await self.geocoder.geocode(address)
        if geo is None:
            raise AddressNotFound()
        brief_id = brief_id_for(geo.matched)
        cached = self.cache.get(brief_id)
        if cached is not None:
            log_event("brief_cache_hit", brief_id=brief_id)
            return cached
        return await self.inflight.run(brief_id, lambda: self._generate(geo, brief_id))

    async def _generate(self, geo: GeocodeResult, brief_id: str) -> dict:
        started = time.monotonic()
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        results = await asyncio.gather(
            *(draft_section(self.draft_provider, sid, geo, now_iso) for sid in SECTION_IDS),
            return_exceptions=True,
        )
        drafts: dict[str, DraftResult | SectionFailure] = {}
        for sid, r in zip(SECTION_IDS, results, strict=True):
            if isinstance(r, DraftResult | SectionFailure):
                drafts[sid] = r
            else:  # an unexpected exception; isolate it like any other failure
                log_event(
                    "draft_crashed", section=sid, kind=r.__class__.__name__, reason=str(r)[:200]
                )
                drafts[sid] = SectionFailure(sid, "The section could not be drafted.")
        if all(isinstance(d, SectionFailure) for d in drafts.values()):
            raise DraftingUnavailable()

        brief = assemble_brief(geo, drafts, brief_id=brief_id, now_iso=now_iso)
        await verify_claims(
            self.verify_provider,
            self.fetcher,
            brief["claims"],
            concurrency=self.settings.verify_concurrency,
            verified_by=self.settings.verify_model,
            now_iso=now_iso,
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
