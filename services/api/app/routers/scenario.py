"""What-if scenarios. Making one costs no model tokens, so it needs no sign-in;
a per-process daily soft cap (scenario_global_day) bounds the page fetches
and ground lookups a flood could cause. Reading one is free to anyone, from
any engine, so an old link keeps working. The optional interpretation spends
model tokens, so it sits behind the sign-in gate and is charged once per
scenario, only when a paragraph is stored. Nothing here logs the ZIP."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import User, same_site_post
from app.auth.gate import Gate, GateDenied
from app.geocode import GeocodeUnavailable
from app.scenario.inputs import MW_MAX, MW_MIN, ScenarioInputs
from app.scenario.pipeline import (
    InterpretFailed,
    InterpretUnavailable,
    ScenarioInvalid,
    ScenarioNotFound,
    ScenarioService,
    ZipNotFound,
)
from app.telemetry import log_event

ScenarioId = Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]

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


def _user(request: Request) -> User | None:
    sessions = request.app.state.sessions
    return sessions.user_of(request) if sessions is not None else None


_INTERPRET_ERRORS: list[tuple[type[Exception], int, str]] = [
    (ScenarioNotFound, 404, "not_found"),
    (InterpretUnavailable, 503, "interpretation_unavailable"),
    (InterpretFailed, 502, "drafting_unavailable"),
    (ScenarioInvalid, 500, "scenario_invalid"),
]


@router.post("/scenario/{scenario_id}/interpret")
async def interpret_scenario(scenario_id: ScenarioId, request: Request) -> StreamingResponse:
    """The plain-words paragraph, as newline-delimited JSON: {"stage":"drafting"},
    {"stage":"verifying","verified":k,"claims":n} per checked claim, then
    {"stage":"done","scenario":...}. A scenario already interpreted, or being
    interpreted, sends only "done" and charges nothing. The request that starts
    the run is charged once the paragraph is stored, so a failed run (or its
    retry) costs nothing. The gate and the cache
    answer before the stream opens, as plain HTTP errors; later errors arrive as
    a final {"stage":"error","status":...,"detail":...} (plus "reason" when the
    model's paragraph was not used)."""
    gate: Gate = request.app.state.gate
    if gate.on and not same_site_post(request):
        raise HTTPException(403, "cross_site")
    service = _service(request)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    admitted, payer = False, None
    while True:
        scenario = service.cache.get(scenario_id)
        if scenario is None:
            raise HTTPException(404, "not_found")
        if scenario.get("interpretation") or service.interpreting(scenario_id):
            break  # join it, free
        if admitted:
            break  # no await since the check: this request starts the run
        if service.draft_provider is None:
            raise HTTPException(503, "interpretation_unavailable")
        try:
            payer = await gate.admit_scenario(_user(request))
        except GateDenied as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        admitted = True  # look again: the awaits may have let another run start

    async def charge() -> None:
        # The usage row holds the scenario id, never the ZIP. A stored
        # paragraph stays stored if the usage store fails.
        try:
            await gate.charge(payer, f"scenario:{scenario_id}")
        except Exception as exc:  # noqa: BLE001
            log_event("interpret_charge_failed", kind=type(exc).__name__)

    try:
        task, _ = service.start_interpret(
            scenario_id, queue.put_nowait, after=charge if admitted else None
        )
    except ScenarioNotFound as exc:
        raise HTTPException(404, "not_found") from exc
    except InterpretUnavailable as exc:
        raise HTTPException(503, "interpretation_unavailable") from exc

    async def run() -> None:
        try:
            done = await asyncio.shield(task)
            queue.put_nowait({"stage": "done", "scenario": done})
        except Exception as exc:  # noqa: BLE001  reported on the stream
            for kind, status, detail in _INTERPRET_ERRORS:
                if isinstance(exc, kind):
                    event = {"stage": "error", "status": status, "detail": detail}
                    if isinstance(exc, InterpretFailed):
                        event["reason"] = exc.reason
                    queue.put_nowait(event)
                    break
            else:
                log_event("interpret_error", scenario_id=scenario_id, kind=type(exc).__name__)
                queue.put_nowait({"stage": "error", "status": 500, "detail": "internal_error"})
        finally:
            queue.put_nowait(None)

    async def events() -> AsyncIterator[bytes]:
        task = asyncio.ensure_future(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield _line(event)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(events(), media_type="application/x-ndjson")


def _line(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
