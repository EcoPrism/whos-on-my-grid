"""Share cards for a brief or a what-if: the PNG crawlers and the download
button fetch, and the JSON the share menu reads so its text and the image
agree. Free and ungated: a card is drawn from a brief or scenario that
already exists, no model call."""

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.brief.cache import engine_fingerprint
from app.card import ID, CardCache, base_url, brief_version, find_brief, find_scenario, make_png
from app.card.spec import CardSpec, share_text, spec_from_brief, spec_from_scenario

router = APIRouter(prefix="/api")

# kind -> (lookup, spec builder, page path, card route, id error, not-found error)
_Lookup = Callable[[Any, str], dict[str, Any] | None]
_Build = Callable[..., CardSpec]
_KINDS: dict[str, tuple[_Lookup, _Build, str, str, str, str]] = {
    "brief": (find_brief, spec_from_brief, "b", "card", "bad_brief_id", "brief_not_found"),
    "scenario": (
        find_scenario,
        spec_from_scenario,
        "what-if",
        "scenario-card",
        "bad_scenario_id",
        "scenario_not_found",
    ),
}


def _cards(request: Request) -> CardCache:
    return request.app.state.cards


def _base(request: Request) -> str:
    return base_url(request.app.state.settings, str(request.base_url))


def _doc(request: Request, kind: str, id: str) -> dict[str, Any]:
    find, _, _, _, bad, missing = _KINDS[kind]
    # Checked before any lookup: the id names a file on disk.
    if not ID.match(id):
        raise HTTPException(422, bad)
    doc = find(request.app.state, id)
    if doc is None:
        raise HTTPException(404, missing)
    return doc


def _spec(request: Request, kind: str, doc: dict[str, Any]) -> CardSpec:
    return _KINDS[kind][1](doc, public_base_url=_base(request))


async def _png(request: Request, kind: str, id: str) -> Response:
    doc = _doc(request, kind, id)
    base = _base(request)
    page = _KINDS[kind][2]
    # The link is in the pixels and the XMP. With no public_base_url it comes
    # from the request, so the cached file is keyed by it: one Host never
    # fixes the link every later viewer gets.
    version = brief_version(doc) + hashlib.sha256(base.encode()).hexdigest()[:8]
    cards = _cards(request)
    png = cards.get(kind, id, version)
    if png is None:
        spec = _spec(request, kind, doc)
        link = f"{base}/{page}/{id}"
        png = await asyncio.to_thread(
            make_png, spec, link=link, settings=request.app.state.settings
        )
        await asyncio.to_thread(cards.put, kind, id, png, version)
    return Response(
        png,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "ETag": f'"{engine_fingerprint()}-{id}-{version}"',
        },
    )


def _info(request: Request, kind: str, id: str) -> dict[str, Any]:
    """CardInfo: {kind, id, spec, share_text, url, image_url}."""
    doc = _doc(request, kind, id)
    spec = _spec(request, kind, doc)
    base = _base(request)
    _, _, page, route, _, _ = _KINDS[kind]
    url = f"{base}/{page}/{id}"
    return {
        "kind": spec.kind,
        "id": id,
        "spec": spec.as_json(),
        "share_text": share_text(spec, url),
        "url": url,
        "image_url": f"{base}/api/{route}/{id}.png",
    }


@router.get("/card/{brief_id}.png")
async def card_png(brief_id: str, request: Request) -> Response:
    return await _png(request, "brief", brief_id)


@router.get("/card/{brief_id}.json")
async def card_json(brief_id: str, request: Request) -> dict[str, Any]:
    return _info(request, "brief", brief_id)


@router.get("/scenario-card/{scenario_id}.png")
async def scenario_card_png(scenario_id: str, request: Request) -> Response:
    return await _png(request, "scenario", scenario_id)


@router.get("/scenario-card/{scenario_id}.json")
async def scenario_card_json(scenario_id: str, request: Request) -> dict[str, Any]:
    return _info(request, "scenario", scenario_id)
