"""Share cards: the brief (or a what-if) as a 1200x630 PNG that says it is
AI-assisted in its pixels, in its metadata and in the text shared with it.
Cached on disk per id, brief version and engine, like the briefs themselves."""

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any

from app.brief import fixtures
from app.brief.cache import engine_fingerprint
from app.card.provenance import IPTC_COMPOSITE_AI, with_c2pa, with_xmp
from app.card.render import render_png
from app.card.spec import CardSpec
from app.config import Settings

ID = re.compile(r"^[0-9a-f]{16}$")
KINDS = ("brief", "scenario")


def brief_version(brief: dict[str, Any]) -> str:
    """Which make of the brief a card shows. A brief regenerated under the same
    id (new engine, new date) gets a new card, not the old one from disk."""
    raw = f"{brief.get('engine', '')}|{brief.get('generated_at', '')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


class CardCache:
    """{dir}/{kind}/{id}.{fingerprint}.png, where the fingerprint is the engine's
    for the doc's region (engine_fingerprint(region_of(doc)); "us" for what-ifs)
    plus the brief version: a code change, an edit to that region's curated data
    or a regenerated brief renders anew.
    A signed card's timestamp makes its bytes differ per render, so a card is made
    once and served from here. `signing` (provenance.signing_stamp) joins the key, so
    loading or rotating a certificate re-renders instead of serving unsigned files."""

    def __init__(self, directory: Path, signing: str = "") -> None:
        self.dir = directory
        self.signing = signing if re.fullmatch(r"[0-9a-f]*", signing) else ""

    def path(self, kind: str, id: str, version: str = "", region_id: str = "us") -> Path | None:
        if kind not in KINDS or not ID.match(id) or not re.fullmatch(r"[0-9a-f]*", version):
            return None
        if not re.fullmatch(r"[a-z]{2,8}", region_id):
            return None
        engine = engine_fingerprint(region_id)
        stamp = f"{engine}-{version}" if version else engine
        if self.signing:
            stamp += f"-c{self.signing}"
        return self.dir / kind / f"{id}.{stamp}.png"

    def get(self, kind: str, id: str, version: str = "", region_id: str = "us") -> bytes | None:
        p = self.path(kind, id, version, region_id)
        if p is None or not p.is_file():
            return None
        return p.read_bytes()

    def put(self, kind: str, id: str, png: bytes, version: str = "", region_id: str = "us") -> None:
        p = self.path(kind, id, version, region_id)
        if p is None:
            raise ValueError("bad card id")
        p.parent.mkdir(parents=True, exist_ok=True)
        # A unique temp name: two writers of the same card never share a file.
        tmp = p.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_bytes(png)
        os.replace(tmp, p)


def find_brief(state: Any, brief_id: str) -> dict[str, Any] | None:
    """A brief by id for the card and the Open Graph tags: the fixture set in
    fixtures mode, else the cache, any engine, so an old link still previews.
    The id is checked before the filesystem is touched."""
    if not ID.match(brief_id):
        return None
    if state.settings.brief_source == "fixtures":
        return fixtures.by_id(brief_id)
    return state.service.cache.get(brief_id)


def find_scenario(state: Any, scenario_id: str) -> dict[str, Any] | None:
    """A scenario by id for its card and Open Graph tags, any engine."""
    if not ID.match(scenario_id):
        return None
    service = getattr(state, "scenarios", None)
    return service.cache.get(scenario_id) if service is not None else None


def base_url(settings: Settings, request_base: str) -> str:
    """settings.public_base_url, or the request's own origin for local runs."""
    return (settings.public_base_url or request_base).rstrip("/")


def make_png(spec: CardSpec, *, link: str, settings: Settings) -> bytes:
    """Pixels, then XMP, then (when configured) a signed C2PA manifest."""
    png = with_xmp(
        render_png(spec),
        source_type=IPTC_COMPOSITE_AI,
        description=spec.disclosure,
        link=link,
    )
    return with_c2pa(png, settings=settings)
