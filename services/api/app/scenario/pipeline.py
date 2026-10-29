"""ZIP -> centroid -> ground truth and households -> arithmetic -> assemble ->
verify the constants' pages -> validate -> cache. No model drafts anything,
so a scenario costs no tokens beyond the verifier's page checks and needs no
sign-in. The optional interpretation paragraph (`interpret`) is one Spark call
behind the sign-in gate; its claims cite only the scenario's own pages.

A ZIP is treated like an address: it is never logged; the scenario id is."""

import asyncio
import json
import os
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.brief.cache import Inflight, engine_fingerprint
from app.brief.draft import SectionFailure
from app.brief.fetch import Fetcher
from app.brief.verify import verify_claims
from app.config import DRAFT_MODEL_ID, Settings
from app.geocode import GeocodeResult
from app.ground import Ground, gather_ground
from app.ground.census import Households, HouseholdsSource
from app.llm.base import LLMProvider
from app.scenario import constants as constants_mod
from app.scenario.assemble import assemble_scenario
from app.scenario.cache import ScenarioCache
from app.scenario.constants import Constants
from app.scenario.inputs import ScenarioInputs
from app.scenario.interpret import draft_interpretation
from app.schema import scenario_errors
from app.telemetry import log_event


class ZipNotFound(Exception):
    pass


class ScenarioInvalid(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:5]))
        self.errors = errors


class ScenarioNotFound(Exception):
    pass


class InterpretUnavailable(Exception):
    """No drafting model is configured for this deployment."""


class InterpretFailed(Exception):
    """The model's paragraph could not be drafted or did not hold to the facts."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


Progress = Callable[[dict], None]


def interpret_key(scenario_id: str) -> str:
    return f"interpret:{scenario_id}"


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
        # Only `interpret` drafts; making a scenario never does.
        self.draft_provider = draft_provider
        self.verify_provider = verify_provider
        self.constants = constants
        self.inflight = Inflight()
        self._background: set[asyncio.Task] = set()

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
        """Optional, so bounded: a cold ACS download that outlasts the ground
        timeout keeps running for later requests, and this one goes without."""
        task = asyncio.ensure_future(self.households.for_zcta(zip5))
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), timeout=self.settings.ground_timeout_seconds
            )
        except TimeoutError:
            log_event("ground_failed", provider="acs", reason="timeout")
            return None
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

    # --- the optional interpretation ------------------------------------------

    def interpreting(self, scenario_id: str) -> bool:
        return self.inflight.running(interpret_key(scenario_id))

    async def interpret(self, scenario_id: str, progress: Progress | None = None) -> dict:
        """The cached scenario with its `interpretation`: three sentences from
        the drafting model, its claims verified like any other. Idempotent: a
        scenario already interpreted comes back as it is. Two calls for the same
        id while it is drafted share one run. Raises ScenarioNotFound,
        InterpretUnavailable, InterpretFailed or ScenarioInvalid."""
        scenario = self.cache.get(scenario_id)
        if scenario is None:
            raise ScenarioNotFound()
        if scenario.get("interpretation"):
            return scenario
        if self.draft_provider is None:
            raise InterpretUnavailable()
        return await self.inflight.run(
            interpret_key(scenario_id), lambda: self._interpret(scenario_id, progress)
        )

    def start_interpret(
        self,
        scenario_id: str,
        progress: Progress | None = None,
        after: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[asyncio.Future[dict], bool]:
        """Like `interpret`, but synchronous up to the start of the run, so a
        caller's check (and its charge) cannot race a second request: (the
        future scenario, True when this call started the run). `after` runs
        only on the run this call started, once the interpretation is stored."""
        scenario = self.cache.get(scenario_id)
        if scenario is None:
            raise ScenarioNotFound()
        if scenario.get("interpretation"):
            done: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
            done.set_result(scenario)
            return done, False
        if self.draft_provider is None:
            raise InterpretUnavailable()

        async def make() -> dict:
            made = await self._interpret(scenario_id, progress)
            if after is not None:
                await after()
            return made

        return self.inflight.start(interpret_key(scenario_id), make)

    async def _interpret(self, scenario_id: str, progress: Progress | None) -> dict:
        started = time.monotonic()
        scenario = self.cache.get(scenario_id)
        if scenario is None:
            raise ScenarioNotFound()
        if scenario.get("interpretation"):
            return scenario
        assert self.draft_provider is not None
        if progress is not None:
            progress({"stage": "drafting"})
        result = await draft_interpretation(self.draft_provider, scenario)
        if isinstance(result, SectionFailure):
            log_event("interpret_failed", scenario_id=scenario_id)
            raise InterpretFailed(result.reason)

        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        start = max(
            (int(c["id"][1:]) for c in scenario["claims"] if str(c.get("id", ""))[1:].isdigit()),
            default=0,
        )
        claims = [_drafted_claim(c, start + n, now_iso) for n, c in enumerate(result.claims, 1)]
        total, done = len(claims), 0

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
            claims,
            concurrency=self.settings.verify_concurrency,
            verified_by=self.settings.verify_model,
            now_iso=now_iso,
            on_verdict=on_verdict,
        )

        scenario["claims"].extend(claims)
        scenario["interpretation"] = {
            # A model's sentences: reported, never measured.
            "status": "reported",
            "text": result.summary,
            "model": DRAFT_MODEL_ID,
            "confidence": result.confidence,
            # Still a draft until the verifier has backed every claim it makes.
            "draft": not claims or any(c["verdict"] != "supported" for c in claims),
        }
        errors = scenario_errors(scenario)
        if errors:
            log_event(
                "scenario_invalid",
                scenario_id=scenario_id,
                errors=[e.split(":")[0] for e in errors[:10]],
            )
            raise ScenarioInvalid(errors)
        self._store(scenario)
        log_event(
            "scenario_interpreted",
            scenario_id=scenario_id,
            ms=int((time.monotonic() - started) * 1000),
            claims=total,
            dropped=result.extra.get("dropped", 0),
            verdicts=dict(Counter(c["verdict"] for c in claims)),
        )
        return scenario

    def _store(self, scenario: dict) -> None:
        """Write the interpreted scenario back. One made by an older engine
        keeps its stamp, so the next POST for those inputs still recomputes it."""
        engine = scenario.get("engine")
        if not engine or engine == engine_fingerprint("us"):
            self.cache.put(scenario)
            return
        p = self.cache.path(scenario["scenario_id"])
        if p is None:
            raise ValueError("bad scenario id")
        tmp = p.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(scenario, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)


def _drafted_claim(c: dict[str, Any], n: int, now_iso: str) -> dict[str, Any]:
    return {
        "id": f"c{n}",
        "section": "scenario",
        "text": c["text"],
        "source": {
            "title": c["source_title"],
            "url": c["source_url"],
            "retrieved_at": now_iso,
            "page": c.get("page"),
            "quote": c["quote"],
        },
        "drafted_by": DRAFT_MODEL_ID,
        "verdict": "unchecked",
        "verified_by": None,
        "verifier_note": None,
    }
