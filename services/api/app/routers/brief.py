from fastapi import APIRouter, HTTPException, Request
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


@router.get("/brief/{brief_id}")
async def get_brief(brief_id: str, request: Request) -> dict:
    if _mode(request) == "fixtures":
        brief = fixtures.by_key(brief_id) or fixtures.by_id(brief_id)
    else:
        brief = _service(request).cache.get(brief_id)
    if brief is None:
        raise HTTPException(404, "not_found")
    return brief
