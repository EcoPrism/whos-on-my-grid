"""Region wiring: services, router, health, gate and pulse per region, and the
engine fingerprint's coverage of each region's curated data. Split out of
test_regions.py in step 6 (owned by stream D); the registry tests stay there."""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# The module, not its functions: pytest would collect a test_* name.
from app.auth import gate
from app.brief import cache as cache_mod
from app.brief import fixtures
from app.brief.cache import _ENGINE_GLOBS, engine_fingerprint
from app.config import REPO_ROOT
from app.geocode import normalise
from app.ground import Ground
from app.ground.facilities import FakeFacilityDatabase
from app.main import create_app
from app.pulse import cited_constants
from app.regions import KNOWN, US_LOCALE, registry
from tests import fakes
from tests.test_health_regions import enable_ie, ie_region
from tests.test_regions import US_FILES


def _fingerprinted(rel: str) -> bool:
    return any(Path(rel).full_match(g) for g in _ENGINE_GLOBS)


def test_engine_fingerprint_covers_region_json_only() -> None:
    """Every curated JSON or GeoJSON file is hashed; recordings and imagery tiles are not,
    since .dockerignore keeps them out of the image and the container's
    fingerprint must equal the machine's that built it."""
    region_files = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "data" / "regions").rglob("*")
        if p.is_file()
    ]
    # Curated data is JSON or GeoJSON (Ireland's utility map); both are hashed.
    json_files = [r for r in region_files if r.endswith((".json", ".geojson"))]
    assert len(json_files) >= len(US_FILES)
    assert all(_fingerprinted(r) for r in json_files)
    assert not any(_fingerprinted(r) for r in region_files if not r.endswith((".json", ".geojson")))
    for rel in (
        "data/regions/us/hearings/audio/x.mp3",
        "data/regions/us/perception/tiles/a.png",
        "data/regions/us/perception/a.tif",
    ):
        assert not _fingerprinted(rel), rel
    assert _fingerprinted("data/regions/ie/utilities/ie.geojson")
    assert _fingerprinted("data/equivalences.json")
    assert not any(
        g.startswith(("data/tariffs", "data/hearings", "data/perception")) for g in _ENGINE_GLOBS
    )
    hashed = {
        p.relative_to(REPO_ROOT).as_posix()
        for g in _ENGINE_GLOBS
        if g.startswith("data/regions/")
        for p in REPO_ROOT.glob(g)
        if p.is_file()
    }
    assert hashed == set(json_files)


# --- wiring: services, router, health, gate, pulse ----------------------------

HDR = {"x-requested-with": "grid"}
ADDR = "21715 Filigree Ct, Ashburn, VA"
ASHBURN_ID = "4fb253585fde1c93"
TEST_SET_ADDR = "Filigree Ct, Ashburn, VA 20147"  # first row of eval/us/addresses.json
RESOLVED_ADDR = "21721 Filigree Court, Ashburn, VA 20147"  # its eval/us/resolved.json form


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("over", [{"regions": "us,zz"}, {"default_region": "eu"}])
def test_create_app_refuses_unknown_regions(tmp_path: Path, over: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="GRID_REGIONS"):
        create_app(fakes.service(tmp_path, **over))


def test_create_app_needs_a_service_per_region(tmp_path: Path) -> None:
    svc = fakes.service(tmp_path)
    with pytest.raises(RuntimeError, match="brief services cover"):
        create_app(services={"us": svc, "zz": fakes.service(tmp_path)})
    app = create_app(services={"us": svc})
    assert app.state.services == {"us": svc} and app.state.service is svc
    assert list(app.state.regions) == ["us"]


def test_create_app_injected_service_is_the_default_region(tmp_path: Path) -> None:
    svc = fakes.service(tmp_path)
    app = create_app(svc)
    assert app.state.services == {"us": svc} and app.state.service is svc


async def test_region_service_keeps_the_us_brief_id_and_locale(tmp_path: Path) -> None:
    svc = fakes.service(tmp_path)
    us = registry(svc.settings)["us"]
    svc.region = us
    assert svc.locale == US_LOCALE
    async with _client(create_app(svc)) as c:
        r = await c.post("/api/brief", json={"address": ADDR, "region": "us"})
    assert r.status_code == 200
    brief = r.json()
    assert brief["brief_id"] == ASHBURN_ID
    assert brief["locale"] == dataclasses.asdict(US_LOCALE)


async def test_explicit_us_is_the_same_brief(tmp_path: Path) -> None:
    svc = fakes.service(tmp_path)
    async with _client(create_app(svc)) as c:
        plain = await c.post("/api/brief", json={"address": ADDR})
        assert plain.status_code == 200 and plain.json()["brief_id"] == ASHBURN_ID
        calls = len(svc.draft_provider.calls)  # type: ignore[attr-defined]
        for region in ("us", "US", "", "  "):
            r = await c.post("/api/brief", json={"address": ADDR, "region": region})
            assert r.status_code == 200 and r.json() == plain.json()
        # Each repeat was a cache hit: nothing more was drafted.
        assert len(svc.draft_provider.calls) == calls  # type: ignore[attr-defined]


@pytest.mark.parametrize("route", ["/api/brief", "/api/brief/stream"])
@pytest.mark.parametrize("region", ["zz", "eu", "ie"])
async def test_unknown_region_is_refused_before_anything_is_spent(
    tmp_path: Path, route: str, region: str
) -> None:
    svc = fakes.service(
        tmp_path, auth_provider="fake", session_secret="s" * 40, cookie_secure=False
    )
    app = create_app(svc)
    async with _client(app) as c:
        r = await c.post(route, json={"address": TEST_SET_ADDR, "region": region}, headers=HDR)
    assert r.status_code == 422 and r.json()["detail"] == "unknown_region"
    assert svc.geocoder.calls == 0  # type: ignore[attr-defined]
    assert svc.draft_provider.calls == []  # type: ignore[attr-defined]
    assert await app.state.gate.usage.count_global_today() == 0


@pytest.mark.parametrize("route", ["/api/brief", "/api/brief/stream"])
async def test_unknown_region_is_refused_in_fixtures_mode(tmp_path: Path, route: str) -> None:
    async with _client(create_app(fakes.service(tmp_path, brief_source="fixtures"))) as c:
        r = await c.post(route, json={"address": "Filigree Ct, Ashburn", "region": "zz"})
        assert r.status_code == 422 and r.json()["detail"] == "unknown_region"
        r = await c.post(route, json={"address": "Filigree Ct, Ashburn", "region": "us"})
        assert r.status_code == 200


async def test_region_field_is_bounded(tmp_path: Path) -> None:
    async with _client(create_app(fakes.service(tmp_path))) as c:
        r = await c.post("/api/brief", json={"address": ADDR, "region": "x" * 17})
    assert r.status_code == 422


@pytest.mark.parametrize("mode", ["fixtures", "agent"])
async def test_health_names_the_region(tmp_path: Path, mode: str) -> None:
    async with _client(create_app(fakes.service(tmp_path, brief_source=mode))) as c:
        body = (await c.get("/api/health")).json()
        assert body["region"] == "us"
        # Each row also carries the C7 fields (test_health_regions.py checks them).
        assert [{"id": r["id"], "label": r["label"]} for r in body["regions"]] == [
            {"id": "us", "label": "US"}
        ]
        expected = [] if mode == "fixtures" else [r["address"] for r in gate.test_set_rows()]
        assert body["test_addresses"] == expected
        assert (await c.get("/api/health?region=US")).json() == body
        r = await c.get("/api/health?region=zz")
        assert r.status_code == 422 and r.json()["detail"] == "unknown_region"


async def test_pulse_per_region(tmp_path: Path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = Ground(facilities=FakeFacilityDatabase([]))
    app = create_app(svc)
    async with _client(app) as c:
        plain = (await c.get("/api/pulse")).json()
        assert plain["peeringdb"]["total"] == 2
        assert (await c.get("/api/pulse?region=us")).json() == plain
        r = await c.get("/api/pulse?region=zz")
        assert r.status_code == 422 and r.json()["detail"] == "unknown_region"
    assert list(app.state.pulses) == ["us"]
    # The region's constants give the same slider rows as the committed table.
    assert plain["constants"] == cited_constants()


async def test_pulse_region_is_checked_in_fixtures_mode(tmp_path: Path) -> None:
    async with _client(create_app(fakes.service(tmp_path, brief_source="fixtures"))) as c:
        assert (await c.get("/api/pulse?region=us")).json() == {
            "peeringdb": None,
            "equivalences": [],
        }
        assert (await c.get("/api/pulse?region=zz")).status_code == 422


def test_gate_allow_list_is_the_us_test_set(tmp_path: Path) -> None:
    app = create_app(fakes.service(tmp_path))
    allowed = app.state.gate.allowed
    assert allowed and allowed == gate.test_set_addresses()
    us = app.state.regions["us"]
    assert allowed == gate.test_set_addresses((us.test_set, us.resolved))


@pytest.mark.parametrize("address", [TEST_SET_ADDR, RESOLVED_ADDR])
@pytest.mark.parametrize("region", [None, "us"])
async def test_test_set_needs_no_sign_in_with_or_without_region(
    tmp_path: Path, address: str, region: str | None
) -> None:
    svc = fakes.service(
        tmp_path, auth_provider="fake", session_secret="s" * 40, cookie_secure=False
    )
    body: dict[str, str] = {"address": address}
    if region is not None:
        body["region"] = region
    async with _client(create_app(svc)) as c:
        r = await c.post("/api/brief", json=body, headers=HDR)
    assert r.status_code == 200, r.json().get("detail")


async def test_country_gate_runs_before_the_region(tmp_path: Path) -> None:
    """The edge's country gate answers first; an allowed visitor naming an
    unknown region then gets the region's 422."""
    app = create_app(fakes.service(tmp_path, allowed_countries="US", country_header="cf-ipcountry"))
    async with _client(app) as c:
        body = {"address": ADDR, "region": "zz"}
        r = await c.post("/api/brief", json=body, headers={"cf-ipcountry": "DE"})
        assert r.status_code == 403 and r.json()["detail"] == "not_available_in_region"
        r = await c.post("/api/brief", json=body, headers={"cf-ipcountry": "US"})
        assert r.status_code == 422 and r.json()["detail"] == "unknown_region"
        r = await c.post("/api/brief", json={"address": ADDR}, headers={"cf-ipcountry": "US"})
        assert r.status_code == 200 and r.json()["brief_id"] == ASHBURN_ID
        assert (await c.get("/api/health", headers={"cf-ipcountry": "US"})).json()["region"] == "us"


# --- step 6: Ireland beside the US -------------------------------------------------


def test_gate_allow_list_adds_the_irish_test_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_ie(monkeypatch)
    app = create_app(services=fakes.services(tmp_path))
    allowed = app.state.gate.allowed
    ie = app.state.regions["ie"]
    irish = gate.test_set_addresses((ie.test_set, None))
    assert irish and irish <= allowed
    assert gate.test_set_addresses() <= allowed
    assert normalise("Blanchardstown Centre, Blanchardstown, Dublin 15") in allowed


async def test_irish_test_address_needs_no_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_ie(monkeypatch)
    svcs = fakes.services(
        tmp_path, auth_provider="fake", session_secret="s" * 40, cookie_secure=False
    )
    app = create_app(services=svcs)
    body = {"address": "Blanchardstown Centre, Blanchardstown, Dublin 15", "region": "ie"}
    async with _client(app) as c:
        # First an address outside the test set: the fake geocoder places it at
        # the same point, so once a brief exists it would be free to anyone.
        r = await c.post(
            "/api/brief", json={"address": "1 Main St, Somewhere", "region": "ie"}, headers=HDR
        )
        assert r.status_code == 401 and r.json()["detail"] == "sign_in_required"
        r = await c.post("/api/brief", json=body, headers=HDR)
        assert r.status_code == 200, r.text
        assert r.json()["brief_id"] == fakes.IE_BRIEF_ID


async def test_lifespan_sweeps_when_a_region_ages_briefs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(KNOWN, "ie", lambda s: dataclasses.replace(ie_region(s), brief_ttl_days=30))
    svcs = fakes.services(tmp_path)
    cache = svcs["us"].cache
    assert cache is svcs["ie"].cache
    cache.ttl_days = 30
    old = (datetime.now(UTC) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache.put({"brief_id": fakes.IE_BRIEF_ID, "generated_at": old, "locale": {"country": "IE"}})
    cache.put({"brief_id": ASHBURN_ID, "generated_at": old})
    card = tmp_path / "cards" / "brief" / f"{fakes.IE_BRIEF_ID}.abc.png"
    card.parent.mkdir(parents=True)
    card.write_bytes(b"png")
    app = create_app(services=svcs)
    async with app.router.lifespan_context(app):
        for _ in range(200):
            if not cache.path(fakes.IE_BRIEF_ID).exists():
                break
            await asyncio.sleep(0.01)
        assert app.state.sweeper is not None and not app.state.sweeper.done()
    assert app.state.sweeper.cancelled()
    assert not cache.path(fakes.IE_BRIEF_ID).exists() and not card.exists()
    assert cache.path(ASHBURN_ID).exists()


async def test_no_sweeper_while_every_region_keeps_briefs(tmp_path: Path) -> None:
    app = create_app(fakes.service(tmp_path))
    async with app.router.lifespan_context(app):
        assert app.state.sweeper is None


async def test_sweeper_runs_on_the_cache_ttl_with_ireland_switched_off(tmp_path: Path) -> None:
    """GRID_REGIONS=us after Ireland was on: Irish briefs on disk still age out."""
    svc = fakes.service(tmp_path)
    svc.cache.ttl_days = 30
    app = create_app(svc)
    assert list(app.state.regions) == ["us"]
    async with app.router.lifespan_context(app):
        assert app.state.sweeper is not None and not app.state.sweeper.done()
    assert app.state.sweeper.cancelled()


async def test_card_etag_follows_the_briefs_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A US curated-data edit changes a US card's ETag and file, not an Irish
    card's; an Irish edit the reverse."""
    root = tmp_path / "repo"
    for rel, text in (
        ("services/api/app/x.py", "x = 1\n"),
        ("data/regions/us/tariffs.json", "{}"),
        ("data/regions/ie/tariffs.json", "{}"),
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    monkeypatch.setattr(cache_mod, "REPO_ROOT", root)
    engine_fingerprint.cache_clear()
    try:
        svc = fakes.service(tmp_path, public_base_url="https://grid.example")
        us = dict(fixtures.by_key("tucson") or {})
        ie = {**us, "brief_id": fakes.IE_BRIEF_ID, "locale": {"country": "IE"}}
        svc.cache.put(us)
        svc.cache.put(ie)
        app = create_app(svc)

        async def etags() -> tuple[str, str]:
            async with _client(app) as c:
                a = await c.get(f"/api/card/{us['brief_id']}.png")
                b = await c.get(f"/api/card/{fakes.IE_BRIEF_ID}.png")
            assert a.status_code == b.status_code == 200
            return a.headers["etag"], b.headers["etag"]

        us_tag, ie_tag = await etags()
        assert us_tag.startswith(f'"{engine_fingerprint("us")}-')
        assert ie_tag.startswith(f'"{engine_fingerprint("ie")}-')
        (root / "data/regions/us/tariffs.json").write_text('{"entries": []}', encoding="utf-8")
        engine_fingerprint.cache_clear()
        us_tag2, ie_tag2 = await etags()
        assert us_tag2 != us_tag and ie_tag2 == ie_tag
        (root / "data/regions/ie/tariffs.json").write_text('{"entries": []}', encoding="utf-8")
        engine_fingerprint.cache_clear()
        us_tag3, ie_tag3 = await etags()
        assert us_tag3 == us_tag2 and ie_tag3 != ie_tag2
        cards = {p.name.split(".")[1] for p in (tmp_path / "cards" / "brief").glob("*.png")}
        assert len(cards) == 4  # one file per (brief, engine) pair rendered
    finally:
        engine_fingerprint.cache_clear()
