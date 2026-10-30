import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import User, same_site_post
from app.auth.gate import Gate, GateDenied, test_set_rows
from app.brief import fixtures
from app.brief.pipeline import (
    AddressNotFound,
    BriefInvalid,
    BriefService,
    DraftingUnavailable,
    Resolved,
)
from app.geocode import GeocodeUnavailable
from app.pulse import Pulse
from app.regions import Region, UnknownRegion, region_for

router = APIRouter(prefix="/api")


class BriefRequest(BaseModel):
    address: str = Field(min_length=3, max_length=300)
    # A region id; absent or blank picks one from the country header, then the default.
    region: str | None = Field(default=None, max_length=16)


def _region(request: Request, explicit: str | None) -> Region:
    """The region a request is for. The country header counts only when an edge
    sets it (GRID_ALLOWED_COUNTRIES). An unknown or disabled id is a 422, raised
    before anything is geocoded or charged."""
    s = request.app.state.settings
    header = request.headers.get(s.country_header) if s.allowed_countries.strip() else None
    try:
        return region_for(
            request.app.state.regions,
            explicit=explicit,
            country_header=header,
            default=s.default_region_id,
        )
    except UnknownRegion as exc:
        raise HTTPException(422, "unknown_region") from exc


def _service(request: Request, region: Region | None = None) -> BriefService:
    state = request.app.state
    return state.services[region.id] if region is not None else state.service


def _mode(request: Request) -> str:
    return request.app.state.settings.brief_source


def _gate(request: Request) -> Gate:
    return request.app.state.gate


def _user(request: Request) -> User | None:
    sessions = request.app.state.sessions
    return sessions.user_of(request) if sessions is not None else None


async def _who(request: Request) -> dict | None:
    user = _user(request)
    if user is None:
        return None
    return {"email": user.email, "remaining": await _gate(request).remaining(user)}


def _region_info(r: Region) -> dict:
    """What the web needs to show a region: its switch label, locale, address
    box, footer sources and retention (C7)."""
    return {
        "id": r.id,
        "label": r.label,
        "countries": sorted(r.countries),
        "places_country": list(r.places_country),
        "locale": dataclasses.asdict(r.locale),
        "scenarios": r.scenarios,
        "placeholder": r.placeholder,
        "address_label": r.address_label,
        "geocoder_attribution": r.geocoder_attribution,
        "sources_line": r.sources_line,
        "brief_ttl_days": r.brief_ttl_days,
    }


@router.get("/health")
async def health(request: Request, region: str | None = None) -> dict:
    r = _region(request, region)
    mode = _mode(request)
    settings = request.app.state.settings
    regions: dict[str, Region] = request.app.state.regions
    return {
        "ok": True,
        "mode": mode,
        "region": r.id,
        "regions": [_region_info(reg) for reg in regions.values()],
        # The asked-for region's settings, at the top level for the page in view.
        "locale": dataclasses.asdict(r.locale),
        "scenarios": r.scenarios,
        "places_country": list(r.places_country),
        "brief_ttl_days": r.brief_ttl_days,
        "examples": fixtures.examples(country=r.locale.country) if mode == "fixtures" else [],
        # The dropdown of free addresses; the gate admits exactly these strings.
        "test_addresses": []
        if mode == "fixtures"
        else [row["address"] for row in test_set_rows(r.test_set, r.resolved)],
        "auth": settings.auth_provider,
        "google_client_id": settings.google_client_id
        if settings.auth_provider == "google"
        else None,
        "user": await _who(request),
        "quota_per_user_day": settings.quota_per_user_day,
    }


@router.get("/pulse")
async def pulse(request: Request, region: str | None = None) -> dict:
    """What PeeringDB lists today and the house-terms lines. Measured, free.
    One per region, each cached on its own: PeeringDB counted over the region's
    own countries, its house-terms lines, and the what-if slider's constants
    only where the what-if runs."""
    r = _region(request, region)
    if _mode(request) == "fixtures":
        return {"peeringdb": None, "equivalences": []}
    pulses: dict[str, Pulse] = request.app.state.pulses
    p = pulses.get(r.id)
    if p is None:
        p = pulses[r.id] = Pulse(
            _service(request, r).ground,
            constants=r.constants,
            region_id=r.id,
            label=r.label,
            countries=r.pulse_countries,
            scenarios=r.scenarios,
        )
    return await p.get()


async def _admit(body: BriefRequest, request: Request, region: Region) -> Resolved:
    """Resolve the address (no tokens spent) and decide who may pay for a new
    brief. A cached or in-flight brief is free; signed out, only a test-set
    address is geocoded at all (a brief link needs no form). Raises HTTPException."""
    gate = _gate(request)
    if gate.on and not same_site_post(request):
        raise HTTPException(403, "cross_site")
    user = _user(request)
    try:
        gate.anonymous_ok(body.address, user)
    except GateDenied as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    try:
        resolved = await _service(request, region).resolve(body.address)
    except AddressNotFound as exc:
        raise HTTPException(422, "address_not_found") from exc
    except GeocodeUnavailable as exc:
        raise HTTPException(503, "geocoder_unavailable") from exc
    if resolved.cached is not None or resolved.inflight:
        return resolved
    try:
        payer = await gate.admit(body.address, user)
    except GateDenied as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    await gate.charge(payer, resolved.brief_id)
    return resolved


@router.post("/brief")
async def create_brief(body: BriefRequest, request: Request) -> dict:
    region = _region(request, body.region)
    if _mode(request) == "fixtures":
        key = fixtures.resolve_address(body.address, country=region.locale.country)
        if key is None:
            raise HTTPException(404, "fixture_not_matched")
        return fixtures.by_key(key) or {}
    resolved = await _admit(body, request, region)
    try:
        return await _service(request, region).generate(resolved)
    except DraftingUnavailable as exc:
        raise HTTPException(502, "drafting_unavailable") from exc
    except BriefInvalid as exc:
        raise HTTPException(500, "brief_invalid") from exc


_ERRORS: list[tuple[type[Exception], int, str]] = [
    (AddressNotFound, 422, "address_not_found"),
    (GeocodeUnavailable, 503, "geocoder_unavailable"),
    (DraftingUnavailable, 502, "drafting_unavailable"),
    (BriefInvalid, 500, "brief_invalid"),
]


@router.post("/brief/stream")
async def stream_brief(body: BriefRequest, request: Request) -> StreamingResponse:
    """The same brief, as newline-delimited JSON events while it is made:
    {"stage":"ground","brief":...} once the facts are in, {"stage":"drafting",
    "brief":...} as each section lands, {"stage":"verifying","verified":k,
    "claims":n} per checked claim, then {"stage":"done","brief":...}. A cached
    address sends only "done". Geocoding and the gate answer before the stream
    opens, as plain HTTP errors; later errors arrive as {"stage":"error",
    "status":...,"detail":...} on a 200 transport, since the headers are long gone."""
    region = _region(request, body.region)
    if _mode(request) == "fixtures":
        key = fixtures.resolve_address(body.address, country=region.locale.country)
        if key is None:
            raise HTTPException(404, "fixture_not_matched")
        brief = fixtures.by_key(key) or {}

        async def fixture_events() -> AsyncIterator[bytes]:
            yield _line({"stage": "done", "brief": brief})

        return StreamingResponse(fixture_events(), media_type="application/x-ndjson")

    service = _service(request, region)
    resolved = await _admit(body, request, region)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def run() -> None:
        try:
            brief = await service.generate(resolved, queue.put_nowait)
            queue.put_nowait({"stage": "done", "brief": brief})
        except Exception as exc:  # noqa: BLE001  reported on the stream
            for kind, status, detail in _ERRORS:
                if isinstance(exc, kind):
                    queue.put_nowait({"stage": "error", "status": status, "detail": detail})
                    break
            else:
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


@router.get("/brief/{brief_id}")
async def get_brief(brief_id: str, request: Request) -> dict:
    if _mode(request) == "fixtures":
        brief = fixtures.by_key(brief_id) or fixtures.by_id(brief_id)
    else:
        brief = _service(request).cache.get(brief_id)
    if brief is None:
        raise HTTPException(404, "not_found")
    return brief
