import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import User, same_site_post
from app.auth.gate import Gate, GateDenied
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

router = APIRouter(prefix="/api")


class BriefRequest(BaseModel):
    address: str = Field(min_length=3, max_length=300)


def _service(request: Request) -> BriefService:
    return request.app.state.service


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


@router.get("/health")
async def health(request: Request) -> dict:
    mode = _mode(request)
    settings = request.app.state.settings
    return {
        "ok": True,
        "mode": mode,
        "examples": fixtures.examples() if mode == "fixtures" else [],
        "auth": settings.auth_provider,
        "google_client_id": settings.google_client_id
        if settings.auth_provider == "google"
        else None,
        "user": await _who(request),
        "quota_per_user_day": settings.quota_per_user_day,
    }


@router.get("/pulse")
async def pulse(request: Request) -> dict:
    """What PeeringDB lists today and the house-terms lines. Measured, free."""
    if _mode(request) == "fixtures":
        return {"peeringdb": None, "equivalences": []}
    p: Pulse | None = getattr(request.app.state, "pulse", None)
    if p is None:
        p = request.app.state.pulse = Pulse(_service(request).ground)
    return await p.get()


async def _admit(body: BriefRequest, request: Request) -> Resolved:
    """Resolve the address (no tokens spent) and decide who may pay for a new
    brief. A cached or in-flight brief is free to anyone. Raises HTTPException."""
    gate = _gate(request)
    if gate.on and not same_site_post(request):
        raise HTTPException(403, "cross_site")
    try:
        resolved = await _service(request).resolve(body.address)
    except AddressNotFound as exc:
        raise HTTPException(422, "address_not_found") from exc
    except GeocodeUnavailable as exc:
        raise HTTPException(503, "geocoder_unavailable") from exc
    if resolved.cached is not None or resolved.inflight:
        return resolved
    try:
        payer = await gate.admit(body.address, _user(request))
    except GateDenied as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    await gate.charge(payer, resolved.brief_id)
    return resolved


@router.post("/brief")
async def create_brief(body: BriefRequest, request: Request) -> dict:
    if _mode(request) == "fixtures":
        key = fixtures.resolve_address(body.address)
        if key is None:
            raise HTTPException(404, "fixture_not_matched")
        return fixtures.by_key(key) or {}
    resolved = await _admit(body, request)
    try:
        return await _service(request).generate(resolved)
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
    if _mode(request) == "fixtures":
        key = fixtures.resolve_address(body.address)
        if key is None:
            raise HTTPException(404, "fixture_not_matched")
        brief = fixtures.by_key(key) or {}

        async def fixture_events() -> AsyncIterator[bytes]:
            yield _line({"stage": "done", "brief": brief})

        return StreamingResponse(fixture_events(), media_type="application/x-ndjson")

    service = _service(request)
    resolved = await _admit(body, request)
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
