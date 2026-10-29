"""Regions: each region's curated data lives under data/regions/<id>/. The US is
the only region; moving its files there, and routing every request through a
region, must not change what a brief reads or what the API answers."""

import dataclasses
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# The module, not its functions: pytest would collect a test_* name.
from app.auth import gate
from app.brief.cache import _ENGINE_GLOBS
from app.config import REPO_ROOT, Settings
from app.ground import US_DATA_DIR, Ground, get_ground
from app.ground.facilities import FakeFacilityDatabase, load_overrides
from app.ground.hearings import HearingIndex
from app.ground.prices import FakeUtilityPrices
from app.ground.tariffs import TariffTable
from app.ground.utility import HifldUtility, disambiguate
from app.main import create_app
from app.pulse import cited_constants
from app.regions import US_LOCALE, Region, UnknownRegion, region_for, registry
from app.regions.locale import Locale
from app.scenario import constants
from tests import fakes

US_FILES = (
    "tariffs.json",
    "facilities.json",
    "constants.json",
    "hearings/sources.json",
    "perception/areas.json",
)


@pytest.mark.parametrize("name", US_FILES)
def test_us_curated_files_exist(name: str) -> None:
    assert (US_DATA_DIR / name).is_file()


def test_us_curated_data_is_not_empty() -> None:
    """Every loader returns empty for a missing file, so a wrong path would
    silently drop operators, hearings and tariffs instead of failing."""
    assert load_overrides(US_DATA_DIR / "facilities.json")
    assert HearingIndex(US_DATA_DIR / "hearings").sources()["bodies"]
    assert TariffTable().match("VA", "VIRGINIA ELECTRIC & POWER CO") is not None
    assert TariffTable().path == US_DATA_DIR / "tariffs.json"


def test_us_constants_are_the_default_table() -> None:
    region = constants.load_region(US_DATA_DIR)
    default = constants.load()
    assert region and region.keys() == default.keys()
    assert all(region[k] == default[k] for k in default)


def test_ground_reads_the_us_directories(tmp_path: Path) -> None:
    s = fakes.settings(tmp_path)
    g = get_ground(s)
    assert s.hearings_path == US_DATA_DIR / "hearings"
    assert s.perception_path == US_DATA_DIR / "perception"
    assert g.hearings.dir == s.hearings_path  # type: ignore[union-attr]
    assert g.imagery.dir == s.perception_path  # type: ignore[union-attr]
    assert g.tariffs.path == US_DATA_DIR / "tariffs.json"  # type: ignore[union-attr]
    assert g.facilities.overrides == load_overrides(US_DATA_DIR / "facilities.json")  # type: ignore[union-attr]
    # EIA-861 settles overlapping territories: the utility provider must hold
    # the same directory the brief reads prices from.
    assert isinstance(g.utility, HifldUtility)
    assert g.utility.directory is g.utility_prices


# Fictional utilities: a big IOU polygon drawn over a co-op that EIA-861 says
# is the one serving Loudoun.
_OVERLAP = [
    {"NAME": "BIGTOWN POWER CO", "TYPE": "INVESTOR OWNED", "CUSTOMERS": 900000, "ID": "1"},
    {"NAME": "VALLEY ELECTRIC COOP", "TYPE": "COOPERATIVE", "CUSTOMERS": 40000, "ID": "2"},
]


async def test_disambiguate_uses_the_directory() -> None:
    directory = FakeUtilityPrices(counties={"1": {"FAIRFAX"}, "2": {"LOUDOUN"}})
    assert (await disambiguate(fakes.GEO, _OVERLAP, None)).raw_name == "BIGTOWN POWER CO"  # type: ignore[union-attr]
    chosen = await disambiguate(fakes.GEO, _OVERLAP, directory)
    assert chosen is not None and chosen.raw_name == "VALLEY ELECTRIC COOP"


async def test_disambiguate_falls_back_to_the_county_list() -> None:
    marketer = [{"NAME": "FEDERAL POWER ADMIN", "TYPE": "FEDERAL", "ID": "9"}]
    directory = FakeUtilityPrices(counties={"2": {"LOUDOUN"}}, names={"2": "Valley Electric Coop"})
    assert (await disambiguate(fakes.GEO, marketer, None)).raw_name == "FEDERAL POWER ADMIN"  # type: ignore[union-attr]
    chosen = await disambiguate(fakes.GEO, marketer, directory)
    assert chosen is not None and chosen.raw_name == "VALLEY ELECTRIC COOP"


@pytest.mark.parametrize(
    "value", ["data/hearings", "data/hearings/", "data\\hearings", "data\\hearings\\"]
)
def test_legacy_hearings_dir_reads_the_region(tmp_path: Path, value: str) -> None:
    """A .env copied from an older .env.example still names the old place."""
    s = fakes.settings(tmp_path, hearings_dir=value)
    assert s.hearings_path == US_DATA_DIR / "hearings"


@pytest.mark.parametrize("value", ["data/perception", "data\\perception", "data/perception/"])
def test_legacy_perception_dir_reads_the_region(tmp_path: Path, value: str) -> None:
    s = fakes.settings(tmp_path, perception_dir=value)
    assert s.perception_path == US_DATA_DIR / "perception"


def test_other_dirs_are_not_remapped(tmp_path: Path) -> None:
    s = fakes.settings(tmp_path, hearings_dir=str(tmp_path / "h"), perception_dir="elsewhere")
    assert s.hearings_path == tmp_path / "h"
    assert s.perception_path == REPO_ROOT / "elsewhere"


def _fingerprinted(rel: str) -> bool:
    return any(Path(rel).full_match(g) for g in _ENGINE_GLOBS)


def test_engine_fingerprint_covers_region_json_only() -> None:
    """Every curated JSON file is hashed; recordings and imagery tiles are not,
    since .dockerignore keeps them out of the image and the container's
    fingerprint must equal the machine's that built it."""
    region_files = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "data" / "regions").rglob("*")
        if p.is_file()
    ]
    json_files = [r for r in region_files if r.endswith(".json")]
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


# --- registry -----------------------------------------------------------------


def test_registry_is_the_us_by_default(tmp_path: Path) -> None:
    regions = registry(fakes.settings(tmp_path))
    assert list(regions) == ["us"]
    us = regions["us"]
    assert us.id == "us" and us.label == "US"
    assert us.locale == US_LOCALE == Locale("US", "USD", "us", "en-US")
    assert us.countries == {"US"}
    assert us.data_dir == US_DATA_DIR
    assert us.test_set == REPO_ROOT / "eval" / "addresses.json"
    assert us.resolved == REPO_ROOT / "eval" / "resolved.json"
    assert us.constants.keys() == constants.default().keys()


def test_region_holds_no_live_ground(tmp_path: Path) -> None:
    """The service builds the ground; the region only knows how."""
    s = fakes.settings(tmp_path, brief_source="full")
    us = registry(s)["us"]
    assert not hasattr(us, "ground")
    g = us.make_ground(s)
    assert isinstance(g, Ground)
    assert g.tariffs.path == US_DATA_DIR / "tariffs.json"  # type: ignore[union-attr]
    assert g.hearings.dir == s.hearings_path  # type: ignore[union-attr]
    assert isinstance(g.utility, HifldUtility)
    assert g.utility.directory is g.utility_prices


def test_us_postal_pattern(tmp_path: Path) -> None:
    pattern = registry(fakes.settings(tmp_path))["us"].postal_pattern
    assert pattern.match("20147")
    assert not pattern.match("2014")
    assert not pattern.match("201470")
    assert not pattern.match("D15 X2Y3")


@pytest.mark.parametrize("value", ["us", " us , ", "US", "us,us", ",us,"])
def test_region_ids_are_normalised(tmp_path: Path, value: str) -> None:
    s = fakes.settings(tmp_path, regions=value)
    assert s.region_ids == ("us",)
    assert list(registry(s)) == ["us"]


def test_default_region_is_normalised(tmp_path: Path) -> None:
    s = fakes.settings(tmp_path, default_region=" US ")
    assert s.default_region_id == "us"
    assert list(registry(s)) == ["us"]


@pytest.mark.parametrize(
    ("over", "bad"),
    [
        ({"regions": "us,zz"}, "zz"),
        ({"regions": "zz"}, "zz"),
        ({"regions": ""}, "us"),
        ({"default_region": "eu"}, "eu"),
    ],
)
def test_registry_rejects_unknown_ids(tmp_path: Path, over: dict[str, str], bad: str) -> None:
    with pytest.raises(UnknownRegion) as err:
        registry(fakes.settings(tmp_path, **over))
    assert err.value.id == bad


def test_registry_honours_grid_regions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRID_REGIONS", "us,zz")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.region_ids == ("us", "zz")
    with pytest.raises(UnknownRegion) as err:
        registry(s)
    assert err.value.id == "zz"


def test_registry_honours_grid_default_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRID_DEFAULT_REGION", "eu")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.default_region_id == "eu"
    with pytest.raises(UnknownRegion) as err:
        registry(s)
    assert err.value.id == "eu"


def test_registry_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRID_REGIONS", raising=False)
    monkeypatch.delenv("GRID_DEFAULT_REGION", raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.region_ids == ("us",) and s.default_region_id == "us"


# --- region_for ---------------------------------------------------------------


def _two(tmp_path: Path) -> dict[str, Region]:
    us = registry(fakes.settings(tmp_path))["us"]
    ie = dataclasses.replace(
        us,
        id="ie",
        label="Ireland",
        locale=Locale("IE", "EUR", "metric", "en-IE"),
        countries=frozenset({"IE"}),
    )
    return {"us": us, "ie": ie}


def _pick(regions: dict[str, Region], explicit: str | None, header: str | None) -> str:
    return region_for(regions, explicit=explicit, country_header=header, default="us").id


def test_region_for_explicit_beats_header_beats_default(tmp_path: Path) -> None:
    regions = _two(tmp_path)
    assert _pick(regions, "us", "IE") == "us"
    assert _pick(regions, "ie", "US") == "ie"
    assert _pick(regions, " IE ", None) == "ie"
    assert _pick(regions, None, "IE") == "ie"
    assert _pick(regions, None, "ie") == "ie"
    assert _pick(regions, None, None) == "us"


@pytest.mark.parametrize("header", ["DE", "", "  ", "XX", None])
def test_region_for_uncovered_header_is_the_default(tmp_path: Path, header: str | None) -> None:
    assert _pick(_two(tmp_path), None, header) == "us"


@pytest.mark.parametrize("explicit", ["", "   "])
def test_region_for_blank_explicit_is_absent(tmp_path: Path, explicit: str) -> None:
    """A client may send an empty stored choice; that is no choice, not a bad one."""
    regions = _two(tmp_path)
    assert _pick(regions, explicit, "IE") == "ie"
    assert _pick(regions, explicit, None) == "us"


@pytest.mark.parametrize("explicit", ["zz", "eu", "united states"])
def test_region_for_unknown_explicit_raises(tmp_path: Path, explicit: str) -> None:
    with pytest.raises(UnknownRegion) as err:
        _pick(_two(tmp_path), explicit, "US")
    assert err.value.id == explicit


def test_region_for_disabled_region_raises(tmp_path: Path) -> None:
    """A known id that GRID_REGIONS leaves out is as unknown as a typo."""
    regions = {"us": _two(tmp_path)["us"]}
    with pytest.raises(UnknownRegion):
        _pick(regions, "ie", None)
    assert _pick(regions, None, "IE") == "us"


# --- wiring: services, router, health, gate, pulse ----------------------------

HDR = {"x-requested-with": "grid"}
ADDR = "21715 Filigree Ct, Ashburn, VA"
ASHBURN_ID = "4fb253585fde1c93"
TEST_SET_ADDR = "Filigree Ct, Ashburn, VA 20147"  # first row of eval/addresses.json
RESOLVED_ADDR = "21721 Filigree Court, Ashburn, VA 20147"  # its eval/resolved.json form


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
        assert body["regions"] == [{"id": "us", "label": "US"}]
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
