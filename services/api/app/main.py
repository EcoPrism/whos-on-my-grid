import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import get_sessions, get_usage_store, get_verifier
from app.auth.gate import Gate
from app.brief.cache import BriefCache
from app.brief.fetch import Fetcher, HttpFetcher, TranscriptFetcher
from app.brief.pipeline import BriefService
from app.card import CardCache
from app.config import Settings, get_settings
from app.geocode import CensusGeocoder, ZctaCentroids
from app.ground import get_ground
from app.ground.census import AcsHouseholds
from app.llm import get_draft_provider, get_verify_provider
from app.routers import auth, brief, card, scenario
from app.scenario.cache import ScenarioCache
from app.scenario.pipeline import ScenarioService
from app.static import mount_web
from app.telemetry import log_event, uptime_ms


def default_service(settings: Settings) -> BriefService:
    ground = get_ground(settings) if settings.brief_source == "full" else None
    fetcher: Fetcher = HttpFetcher()
    if ground is not None and ground.hearings is not None:
        # Hearing claims cite the archive page; the verifier reads the transcript.
        fetcher = TranscriptFetcher(fetcher, ground.hearings)
    return BriefService(
        settings=settings,
        geocoder=CensusGeocoder(),
        draft_provider=get_draft_provider(),
        verify_provider=get_verify_provider(),
        fetcher=fetcher,
        cache=BriefCache(settings.data_path),
        ground=ground,
    )


def default_scenarios(settings: Settings, brief_service: BriefService) -> ScenarioService:
    """Beside the brief service and sharing its ground, fetcher and models. In
    fixtures mode nothing is verified: the page checks would be live fetches."""
    return ScenarioService(
        settings=settings,
        zips=ZctaCentroids(settings.ground_path),
        ground=brief_service.ground,
        households=AcsHouseholds(settings.ground_path, api_key=settings.census_api_key),
        cache=ScenarioCache(settings.scenarios_path),
        fetcher=brief_service.fetcher,
        draft_provider=brief_service.draft_provider,
        verify_provider=None
        if settings.brief_source == "fixtures"
        else brief_service.verify_provider,
    )


def create_app(
    service: BriefService | None = None, scenarios: ScenarioService | None = None
) -> FastAPI:
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

    # The sign-in gate and the usage store fail fast on a half-configured deploy:
    # google without a client id or a session secret, table without an account.
    verifier = get_verifier(settings)
    sessions = get_sessions(settings)
    usage = get_usage_store(settings)

    logging.basicConfig(level=logging.INFO)
    # httpx logs every request URL at INFO, and those URLs carry the geocoder's
    # address and the point being looked up (an address's or a ZIP's centroid).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log_event(
            "app_ready",
            ms=uptime_ms(),
            mode=settings.brief_source,
            llm=settings.llm_provider,
            verifier=settings.llm_provider != "openai" or bool(settings.baseten_api_key),
            auth=settings.auth_provider,
            usage=settings.usage_store,
            web=web_mounted,
        )
        yield

    app = FastAPI(title="Who's On My Grid API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service or default_service(settings)
    app.state.scenarios = scenarios or default_scenarios(settings, app.state.service)
    app.state.verifier = verifier
    app.state.sessions = sessions
    app.state.gate = Gate(settings, sessions, usage)
    app.state.cards = CardCache(settings.cards_path)

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
    app.include_router(auth.router)
    app.include_router(card.router)
    app.include_router(scenario.router)
    # Last: the SPA catch-all must sit behind every /api route.
    web_mounted = mount_web(app, settings.web_dist_path)
    return app
