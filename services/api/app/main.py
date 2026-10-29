import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import get_sessions, get_usage_store, get_verifier
from app.auth.gate import Gate, test_set_addresses
from app.brief.cache import BriefCache
from app.brief.fetch import Fetcher, HttpFetcher, TranscriptFetcher
from app.brief.pipeline import BriefService
from app.card import CardCache
from app.card.provenance import signing_stamp
from app.config import Settings, get_settings
from app.geocode import ZctaCentroids
from app.ground.census import AcsHouseholds
from app.llm import get_draft_provider, get_verify_provider
from app.regions import Region, UnknownRegion, registry
from app.routers import auth, brief, card, scenario
from app.scenario.cache import ScenarioCache
from app.scenario.pipeline import ScenarioService
from app.static import mount_web
from app.telemetry import log_event, uptime_ms


def default_service(settings: Settings, region: Region, cache: BriefCache) -> BriefService:
    """One region's brief service. Every region shares the one brief cache, so a
    brief link resolves whichever region made it; this service's `ground` is the
    one its briefs read."""
    ground = region.make_ground(settings) if settings.brief_source == "full" else None
    fetcher: Fetcher = HttpFetcher()
    if ground is not None and ground.hearings is not None:
        # Hearing claims cite the archive page; the verifier reads the transcript.
        fetcher = TranscriptFetcher(fetcher, ground.hearings)
    return BriefService(
        settings=settings,
        geocoder=region.geocoder,
        draft_provider=get_draft_provider(),
        verify_provider=get_verify_provider(),
        fetcher=fetcher,
        cache=cache,
        ground=ground,
        region=region,
    )


def default_scenarios(
    settings: Settings, brief_service: BriefService, region: Region | None = None
) -> ScenarioService:
    """Beside the brief service and sharing its ground, fetcher and models, on
    the region's constants (the US's). In fixtures mode nothing is verified:
    the page checks would be live fetches."""
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
        constants=region.constants if region is not None else None,
    )


async def sweep_loop(cache: BriefCache, cards_dir: Path, every_s: float) -> None:
    """Remove expired non-US briefs and their cards now and every `every_s`
    seconds, off the event loop. A failed sweep is logged (kind only) and the
    loop goes on: retention must not stop because one file was locked."""
    while True:
        try:
            await asyncio.to_thread(cache.sweep, cards_dir)
        except Exception as exc:  # noqa: BLE001
            log_event("brief_sweep_failed", kind=type(exc).__name__)
        await asyncio.sleep(every_s)


def create_app(
    service: BriefService | None = None,
    scenarios: ScenarioService | None = None,
    *,
    services: dict[str, BriefService] | None = None,
) -> FastAPI:
    """`service` stands in for the default region's; `services` gives one per
    enabled region and must cover exactly GRID_REGIONS."""
    given = service or (next(iter(services.values())) if services else None)
    settings = given.settings if given else get_settings()
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

    try:
        regions = registry(settings)
    except UnknownRegion as exc:
        raise RuntimeError(
            f"GRID_REGIONS and GRID_DEFAULT_REGION must name known regions, got {exc.id!r}"
        ) from exc
    default_region = settings.default_region_id
    if services is None:
        if service is not None:
            services = {default_region: service}
        else:
            cache = BriefCache(settings.data_path, ttl_days=max(0, settings.brief_ttl_days))
            services = {rid: default_service(settings, r, cache) for rid, r in regions.items()}
    if set(services) != set(regions):
        # A request for an enabled region must find its service, never a KeyError.
        raise RuntimeError(
            f"brief services cover {sorted(services)}, GRID_REGIONS enables {sorted(regions)}"
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
            regions=",".join(regions),
        )
        # Retention (plan 0.11): whenever the shared brief cache ages briefs out
        # (GRID_BRIEF_TTL_DAYS > 0), sweep it at startup and every
        # GRID_BRIEF_SWEEP_HOURS. Keyed on the cache, not the enabled regions:
        # Irish briefs left on disk after Ireland is switched off still age out.
        sweeper: asyncio.Task[None] | None = None
        if getattr(app.state.service.cache, "ttl_days", 0) > 0:
            hours = settings.brief_sweep_hours if settings.brief_sweep_hours > 0 else 6.0
            sweeper = asyncio.create_task(
                sweep_loop(app.state.service.cache, settings.cards_path, hours * 3600)
            )
        app.state.sweeper = sweeper
        try:
            yield
        finally:
            if sweeper is not None:
                sweeper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sweeper

    app = FastAPI(title="Who's On My Grid API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.regions = regions
    app.state.services = services
    # The default region's service: brief links, cards and Open Graph read its cache,
    # which every region shares.
    app.state.service = services[default_region]
    # What-ifs run on US ZIPs and US constants, so they sit beside the US service.
    app.state.scenarios = scenarios or (
        default_scenarios(settings, services["us"], regions["us"]) if "us" in services else None
    )
    app.state.pulses = {}
    app.state.verifier = verifier
    app.state.sessions = sessions
    app.state.gate = Gate(
        settings,
        sessions,
        usage,
        allowed=test_set_addresses(*[(r.test_set, r.resolved) for r in regions.values()]),
    )
    app.state.cards = CardCache(settings.cards_path, signing_stamp(settings))

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
