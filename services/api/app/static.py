"""Serve the built web app from the same process. Mounted only when the
dist directory exists, so local development (Vite proxying /api) is
unchanged. Hashed assets are immutable; index.html is never cached, and any
path that is not /api and not a file falls back to it for the SPA routes.

Link crawlers (X, Facebook, LinkedIn) run no JavaScript, so the server
writes the Open Graph tags into index.html: a brief's title, first card line
and card image on /b/{id}, a what-if's on /what-if/{id}, the site defaults
everywhere else."""

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from app.card import base_url, find_brief, find_scenario
from app.card.render import H, W
from app.card.spec import SCENARIO_SHARE_TAIL, SHARE_TAIL

# Kinds that have a share card: a brief and a what-if scenario.
_SHARE_ROUTES = re.compile(r"^(b|what-if)/([0-9a-f]{16})$")
OG_MARKER = "<!--og-->"
SITE_NAME = "Who's On My Grid"
SITE_TAGLINE = "What is on my grid, what is coming, and what has it done to my bill."
SITE_DESCRIPTION = f"Type any US address. {SITE_TAGLINE}"
# The built page's own description meta (web/index.html), rewritten only when a
# region other than the US is enabled.
_DESCRIPTION_META = re.compile(
    r'(<meta\s+name="description"\s+content=")[^"]*("\s*/?>)', re.IGNORECASE
)


def site_description(labels: list[str] | tuple[str, ...]) -> str:
    """The site description for the enabled regions' labels. The US alone (or
    nothing) is SITE_DESCRIPTION, byte for byte; else "Type an address in the US
    or Ireland. ..."."""
    if not labels or list(labels) == ["US"]:
        return SITE_DESCRIPTION
    places = ["the US" if label == "US" else label for label in labels]
    where = places[0] if len(places) == 1 else f"{', '.join(places[:-1])} or {places[-1]}"
    return f"Type an address in {where}. {SITE_TAGLINE}"


def describe(index_html: str, description: str) -> str:
    """index.html with its <meta name="description"> content set to
    `description` (escaped). Unchanged for the US-only description, or when
    the page has no such meta."""
    if description == SITE_DESCRIPTION:
        return index_html
    value = html.escape(description)
    return _DESCRIPTION_META.sub(lambda m: f"{m[1]}{value}{m[2]}", index_html, count=1)


@dataclass(frozen=True)
class OgMeta:
    title: str
    description: str
    url: str
    image: str | None = None  # absolute
    image_alt: str | None = None
    type: str = "website"


def og_tags(meta: OgMeta) -> str:
    """The Open Graph and Twitter tags, every value escaped: a title comes from
    a model's card line and must never break out of the attribute."""
    props: list[tuple[str, str, str]] = [
        ("property", "og:site_name", SITE_NAME),
        ("property", "og:type", meta.type),
        ("property", "og:title", meta.title),
        ("property", "og:description", meta.description),
        ("property", "og:url", meta.url),
    ]
    if meta.image:
        props += [
            ("property", "og:image", meta.image),
            ("property", "og:image:type", "image/png"),
            ("property", "og:image:width", str(W)),
            ("property", "og:image:height", str(H)),
            ("property", "og:image:alt", meta.image_alt or meta.title),
            ("name", "twitter:card", "summary_large_image"),
            ("name", "twitter:image", meta.image),
            ("name", "twitter:image:alt", meta.image_alt or meta.title),
        ]
    else:
        props.append(("name", "twitter:card", "summary"))
    props += [
        ("name", "twitter:title", meta.title),
        ("name", "twitter:description", meta.description),
    ]
    return "\n    ".join(
        f'<meta {attr}="{html.escape(key)}" content="{html.escape(value)}" />'
        for attr, key, value in props
    )


def inject(index_html: str, tags: str) -> str:
    """Replaces the <!--og--> marker once. A build without the marker gets the
    tags before </head>, or after the doctype when there is no head at all."""
    if OG_MARKER in index_html:
        return index_html.replace(OG_MARKER, tags, 1)
    lower = index_html.lower()
    at = lower.find("</head>")
    if at < 0 and lower.startswith("<!doctype"):
        at = lower.index(">") + 1
    if at < 0:
        at = 0
    return index_html[:at] + tags + index_html[at:]


def default_meta(base: str, description: str = SITE_DESCRIPTION) -> OgMeta:
    return OgMeta(title=SITE_NAME, description=description, url=f"{base}/")


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else f"{text}."


class OgIndex:
    """Share-page metadata from the brief and scenario caches (fixtures in
    fixtures mode). A miss returns None and the page gets the defaults; the
    SPA shows its own not-found page."""

    def __init__(self, state: Any) -> None:
        self.state = state

    def lookup(self, *, kind: str, id: str, base: str) -> OgMeta | None:
        if kind == "b":
            doc, tail, card_route = find_brief(self.state, id), SHARE_TAIL, "card"
        elif kind == "what-if":
            doc, tail, card_route = (
                find_scenario(self.state, id),
                SCENARIO_SHARE_TAIL,
                "scenario-card",
            )
        else:
            return None
        if doc is None:
            return None
        card = doc.get("card") or {}
        title = str(card.get("title") or SITE_NAME)
        lines = [str(line) for line in card.get("lines") or [] if line]
        description = " ".join(p for p in (_sentence(lines[0]) if lines else "", tail) if p)
        return OgMeta(
            title=title,
            description=description,
            url=f"{base}/{kind}/{id}",
            image=f"{base}/api/{card_route}/{id}.png",
            image_alt=f"Share card for {title}. {tail}",
            type="article",
        )


class ImmutableFiles(StaticFiles):
    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_web(app: FastAPI, dist: Path) -> bool:
    index = dist / "index.html"
    if not index.is_file():
        return False
    # Read once at mount: a deploy is a new process. The enabled regions name
    # the places the description offers (US alone: the page as built).
    regions = getattr(app.state, "regions", None) or {}
    description = site_description([r.label for r in regions.values()])
    index_html = describe(index.read_text(encoding="utf-8"), description)
    dist_root = dist.resolve()
    index_file = index.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", ImmutableFiles(directory=str(assets)), name="assets")
    app.state.og = OgIndex(app.state)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "not_found")
        # A real file at the dist root (favicon, logo). No traversal: the
        # resolved path must stay inside dist. index.html itself falls through,
        # so it gets its tags and no-cache like every other page.
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_file() and candidate != index_file and dist_root in candidate.parents:
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=3600"})
        base = base_url(app.state.settings, str(request.base_url))
        meta: OgMeta | None = None
        m = _SHARE_ROUTES.match(path)
        if m:
            meta = app.state.og.lookup(kind=m[1], id=m[2], base=base)
        page = inject(index_html, og_tags(meta or default_meta(base, description)))
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})

    return True
