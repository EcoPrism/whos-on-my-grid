"""ZIP -> centroid -> ground truth and households -> arithmetic -> assemble ->
verify the constants' pages -> validate -> cache. No model drafts anything,
so a scenario costs no tokens beyond the verifier's page checks and needs no
sign-in. The optional interpretation paragraph is a later step behind the gate.

A ZIP is treated like an address: it is never logged; the scenario id is."""

import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.brief.cache import Inflight
from app.brief.fetch import Fetcher
from app.brief.verify import verify_claims
from app.config import Settings
from app.geocode import GeocodeResult
from app.ground import Ground, gather_ground
from app.ground.census import Households, HouseholdsSource
from app.llm.base import LLMProvider
from app.scenario import constants as constants_mod
from app.scenario.assemble import assemble_scenario
from app.scenario.cache import ScenarioCache
from app.scenario.constants import Constants
from app.scenario.inputs import ScenarioInputs
from app.schema import scenario_errors
from app.telemetry import log_event


class ZipNotFound(Exception):
    pass


class ScenarioInvalid(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:5]))
        self.errors = errors


class ZipLocator(Protocol):
    """app.geocode.ZctaCentroids: a ZIP's centroid, state and county."""

    async def locate(self, zip5: str) -> GeocodeResult | None: ...


@dataclass(frozen=True)
class ResolvedScenario:
    inputs: ScenarioInputs
    geo: GeocodeResult
    scenario_id: str
    cached: dict | None  # a scenario by the current engine, if there is one


class ScenarioService:
    def __init__(
        self,
        *,
        settings: Settings,
        zips: ZipLocator,
        ground: Ground | None,
        households: HouseholdsSource,
        cache: ScenarioCache,
        fetcher: Fetcher,
        draft_provider: LLMProvider | None = None,
        verify_provider: LLMProvider | None = None,
        constants: Constants | None = None,
    ) -> None:
        self.settings = settings
        self.zips = zips
        self.ground = ground
        self.households = households
        self.cache = cache
        self.fetcher = fetcher
        # Kept for the interpretation step (build order step 4); unused here.
        self.draft_provider = draft_provider
        self.verify_provider = verify_provider
        self.constants = constants
        self.inflight = Inflight()

    async def resolve(self, inputs: ScenarioInputs) -> ResolvedScenario:
        """The centroid and the id; no ground data yet. Raises ZipNotFound."""
        geo = await self.zips.locate(inputs.zip)
        if geo is None:
            raise ZipNotFound()
        scenario_id = inputs.scenario_id()
        cached = self.cache.get(scenario_id, current_only=True)
        if cached is not None:
            log_event("scenario_cache_hit", scenario_id=scenario_id)
        return ResolvedScenario(inputs, geo, scenario_id, cached)

    async def compute(self, resolved: ResolvedScenario) -> dict:
        """The finished scenario. Engine only, no drafting. Two requests for the
        same inputs while it is made share one run."""
        if resolved.cached is not None:
            return resolved.cached
        return await self.inflight.run(resolved.scenario_id, lambda: self._compute(resolved))

    async def _households(self, zip5: str) -> Households | None:
        try:
            return await self.households.for_zcta(zip5)
        except Exception as exc:  # noqa: BLE001 - a data provider, never fatal
            log_event("ground_failed", provider="acs", reason=str(exc)[:160])
            return None

    async def _compute(self, resolved: ResolvedScenario) -> dict:
        started = time.monotonic()
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        geo, sid = resolved.geo, resolved.scenario_id
        truth = await gather_ground(geo, self.ground) if self.ground is not None else None
        households = await self._households(resolved.inputs.zip)
        table = self.constants if self.constants is not None else constants_mod.default()

        scenario = assemble_scenario(
            resolved.inputs,
            geo,
            truth,
            households,
            table,
            scenario_id=sid,
            now_iso=now_iso,
            public_base_url=self.settings.public_base_url,
            verified=self.verify_provider is not None,
        )
        # The verifier reads each cited page and finds the quote, as for briefs.
        # A constant's retrieved_at is when it was curated; the check restamps it.
        await verify_claims(
            self.verify_provider,
            self.fetcher,
            scenario["claims"],
            concurrency=self.settings.verify_concurrency,
            verified_by=self.settings.verify_model,
            now_iso=now_iso,
        )

        errors = scenario_errors(scenario)
        if errors:
            # Paths only: a message can echo a value, and values include the ZIP.
            log_event(
                "scenario_invalid", scenario_id=sid, errors=[e.split(":")[0] for e in errors[:10]]
            )
            raise ScenarioInvalid(errors)

        self.cache.put(scenario)
        log_event(
            "scenario",
            scenario_id=sid,
            ms=int((time.monotonic() - started) * 1000),
            lines=len(scenario["lines"]),
            claims=len(scenario["claims"]),
            verdicts=dict(Counter(c["verdict"] for c in scenario["claims"])),
            constants=len(table),
        )
        return scenario
