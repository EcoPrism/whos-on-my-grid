import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.brief import fixtures
from app.brief.pipeline import AddressNotFound, BriefInvalid, BriefService, DraftingUnavailable
from app.geocode import GeocodeUnavailable

router = APIRouter(prefix="/api")


class BriefRequest(BaseModel):
    address: str = Field(min_length=3, max_length=300)


def _service(request: Request) -> BriefService:
    return request.app.state.service


def _mode(request: Request) -> str:
    return request.app.state.settings.brief_source


@router.get("/health")
async def health(request: Request) -> dict:
    mode = _mode(request)
    return {
        "ok": True,
        "mode": mode,
        "examples": fixtures.examples() if mode == "fixtures" else [],
    }


@router.post("/brief")
async def create_brief(body: BriefRequest, request: Request) -> dict:
    if _mode(request) == "fixtures":
        key = fixtures.resolve_address(body.address)
        if key is None:
            raise HTTPException(404, "fixture_not_matched")
        return fixtures.by_key(key) or {}
    try:
        return await _service(request).brief_for_address(body.address)
    except AddressNotFound as exc:
        raise HTTPException(422, "address_not_found") from exc
    except GeocodeUnavailable as exc:
        raise HTTPException(503, "geocoder_unavailable") from exc
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
    address sends only "done". Errors arrive as {"stage":"error","status":...,
    "detail":...} on a 200 transport, since the headers are long gone."""
    if _mode(request) == "fixtures":
        key = fixtures.resolve_address(body.address)
        if key is None:
            raise HTTPException(404, "fixture_not_matched")
        brief = fixtures.by_key(key) or {}

        async def fixture_events() -> AsyncIterator[bytes]:
            yield _line({"stage": "done", "brief": brief})

        return StreamingResponse(fixture_events(), media_type="application/x-ndjson")

    service = _service(request)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def run() -> None:
        try:
            brief = await service.brief_for_address(body.address, queue.put_nowait)
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
