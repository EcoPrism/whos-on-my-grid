import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.brief.cache import BriefCache
from app.brief.fetch import HttpFetcher
from app.brief.pipeline import BriefService
from app.config import Settings, get_settings
from app.geocode import CensusGeocoder
from app.ground import get_ground
from app.llm import get_draft_provider, get_verify_provider
from app.routers import brief
from app.telemetry import log_event, uptime_ms


def default_service(settings: Settings) -> BriefService:
    return BriefService(
        settings=settings,
        geocoder=CensusGeocoder(),
        draft_provider=get_draft_provider(),
        verify_provider=get_verify_provider(),
        fetcher=HttpFetcher(),
        cache=BriefCache(settings.data_path),
        ground=get_ground(settings) if settings.brief_source == "full" else None,
    )


def create_app(service: BriefService | None = None) -> FastAPI:
    settings = service.settings if service else get_settings()
    if settings.brief_source not in ("fixtures", "agent", "full"):
        raise RuntimeError(
            "GRID_BRIEF_SOURCE must be 'fixtures', 'agent' or 'full', "
            f"got {settings.brief_source!r}"
        )
    if settings.llm_provider not in ("openai", "fake"):
        raise RuntimeError(
            f"GRID_LLM_PROVIDER must be 'openai' or 'fake', got {settings.llm_provider!r}"
        )
    # The verifier is optional: without GRID_BASETEN_API_KEY claims stay unchecked.
    if (
        settings.brief_source in ("agent", "full")
        and settings.llm_provider == "openai"
        and not settings.openai_api_key
    ):
        raise RuntimeError(
            "GRID_OPENAI_API_KEY is required in agent and full mode (gateway virtual key)"
        )

    logging.basicConfig(level=logging.INFO)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log_event(
            "app_ready",
            ms=uptime_ms(),
            mode=settings.brief_source,
            llm=settings.llm_provider,
            verifier=settings.llm_provider != "openai" or bool(settings.baseten_api_key),
        )
        yield

    app = FastAPI(title="Who's On My Grid API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service or default_service(settings)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"]
        )

    @app.middleware("http")
    async def http_timing(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.monotonic()
        response = await call_next(request)
        # Route template, never the path: an address must not reach the log.
        route = request.scope.get("route")
        log_event(
            "http",
            method=request.method,
            route=getattr(route, "path", "?"),
            status=response.status_code,
            ms=int((time.monotonic() - started) * 1000),
        )
        return response

    countries = {c.strip().upper() for c in settings.allowed_countries.split(",") if c.strip()}
    if countries:
        header = settings.country_header.lower()

        @app.middleware("http")
        async def country_gate(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            # Health stays open for probes; brief routes are gated. Fail closed:
            # a missing header is a misconfigured edge, not a US visitor.
            if request.url.path.startswith("/api/brief"):
                country = (request.headers.get(header) or "").upper()
                if country not in countries:
                    log_event("country_blocked", country=country or "none")
                    return JSONResponse({"detail": "not_available_in_region"}, status_code=403)
            return await call_next(request)

    app.include_router(brief.router)
    return app
