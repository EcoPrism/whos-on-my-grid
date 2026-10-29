"""What-if scenarios. Making one costs no model tokens, so it needs no sign-in;
a per-process daily soft cap (scenario_global_day) bounds the page fetches
and ground lookups a flood could cause. Reading one is free to anyone, from
any engine, so an old link keeps working. Nothing here logs the ZIP."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import same_site_post
from app.geocode import GeocodeUnavailable
from app.scenario.inputs import MW_MAX, MW_MIN, ScenarioInputs
from app.scenario.pipeline import ScenarioInvalid, ScenarioService, ZipNotFound
from app.telemetry import log_event

router = APIRouter(prefix="/api")


class Pin(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class ScenarioRequest(BaseModel):
    zip: str = Field(pattern=r"^\d{5}$")
    mw: int = Field(ge=MW_MIN, le=MW_MAX, strict=True)
    cooling: Literal["evaporative", "closed_loop"]
    pin: Pin | None = None


class DailyCap:
    """New scenarios computed today (UTC) by this process. A soft cap: a
    restart or a second replica resets it, which is fine for a belt."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.day = ""
        self.used = 0

    def _roll(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self.day:
            self.day, self.used = today, 0

    def full(self) -> bool:
        self._roll()
        return self.used >= self.limit

    def take(self) -> None:
        self._roll()
        self.used += 1


def _service(request: Request) -> ScenarioService:
    service = getattr(request.app.state, "scenarios", None)
    if service is None:
        raise HTTPException(503, "scenarios_unavailable")
    return service


def _cap(request: Request) -> DailyCap:
    cap = getattr(request.app.state, "scenario_cap", None)
    if cap is None:
        limit = _service(request).settings.scenario_global_day
        cap = request.app.state.scenario_cap = DailyCap(limit)
    return cap


@router.post("/scenario")
async def create_scenario(body: ScenarioRequest, request: Request) -> dict:
    gate = request.app.state.gate
    if gate.on and not same_site_post(request):
        raise HTTPException(403, "cross_site")
    service = _service(request)
    inputs = ScenarioInputs.create(
        zip=body.zip,
        mw=body.mw,
        cooling=body.cooling,
        pin=(body.pin.lat, body.pin.lon) if body.pin else None,
    )
    try:
        resolved = await service.resolve(inputs)
    except ZipNotFound as exc:
        raise HTTPException(404, "zip_not_found") from exc
    except GeocodeUnavailable as exc:
        raise HTTPException(503, "geocoder_unavailable") from exc
    if resolved.cached is None and not service.inflight.running(resolved.scenario_id):
        cap = _cap(request)
        if cap.full():
            log_event("scenario_denied", reason="global_cap")
            raise HTTPException(429, "quota_exceeded_today")
        cap.take()
    try:
        return await service.compute(resolved)
    except ScenarioInvalid as exc:
        raise HTTPException(500, "scenario_invalid") from exc


@router.get("/scenario/{scenario_id}")
async def get_scenario(scenario_id: str, request: Request) -> dict:
    scenario = _service(request).cache.get(scenario_id)
    if scenario is None:
        raise HTTPException(404, "not_found")
    return scenario
