"""Regions: each region's curated data lives under data/regions/<id>/. The US is
the only region; moving its files there, and routing every request through a
region, must not change what a brief reads or what the API answers."""

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings
from app.geocode import CensusGeocoder, FakeGeocoder, NominatimGeocoder
from app.ground import IE_DATA_DIR, US_DATA_DIR, Ground, get_ground
from app.ground.facilities import load_overrides
from app.ground.hearings import HearingIndex
from app.ground.prices import FakeUtilityPrices
from app.ground.tariffs import TariffTable
from app.ground.utility import HifldUtility, disambiguate
from app.regions import (
    IE_LOCALE,
    KNOWN,
    US_LOCALE,
    Region,
    UnknownRegion,
    region_for,
    registry,
)
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


# --- registry -----------------------------------------------------------------


def test_registry_is_the_us_by_default(tmp_path: Path) -> None:
    regions = registry(fakes.settings(tmp_path))
    assert list(regions) == ["us"]
    us = regions["us"]
    assert us.id == "us" and us.label == "US"
    assert us.locale == US_LOCALE == Locale("US", "USD", "us", "en-US")
    assert us.countries == {"US"}
    assert us.data_dir == US_DATA_DIR
    assert us.test_set == REPO_ROOT / "eval" / "us" / "addresses.json"
    assert us.resolved == REPO_ROOT / "eval" / "us" / "resolved.json"
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


# --- Ireland ------------------------------------------------------------------


def test_ireland_is_known_but_off_by_default(tmp_path: Path) -> None:
    assert set(KNOWN) == {"us", "ie"}
    assert list(registry(fakes.settings(tmp_path))) == ["us"]
    assert Settings(_env_file=None).ie_geocoder == "nominatim"  # type: ignore[call-arg]


def test_us_and_ireland_build_together(tmp_path: Path) -> None:
    regions = registry(fakes.settings(tmp_path, regions="us,ie", ie_geocoder="fake"))
    assert list(regions) == ["us", "ie"]
    assert regions["us"].locale == US_LOCALE and regions["ie"].locale == IE_LOCALE


def test_ireland_fields(tmp_path: Path) -> None:
    """Plan 0.3, field by field."""
    s = fakes.settings(tmp_path, regions="us,ie", brief_ttl_days=30)
    ie = registry(s)["ie"]
    assert (ie.id, ie.label) == ("ie", "Ireland")
    assert ie.locale == IE_LOCALE == Locale("IE", "EUR", "metric", "en-IE")
    assert ie.countries == {"IE"}
    assert ie.coverage == {"on_your_grid", "your_bill", "protection"}
    assert ie.data_dir == IE_DATA_DIR == REPO_ROOT / "data" / "regions" / "ie"
    assert ie.test_set == REPO_ROOT / "eval" / "ie" / "addresses.json"
    assert ie.resolved is None
    assert ie.scenarios is False
    assert ie.places_country == ("ie",) and ie.pulse_countries == ("IE",)
    assert ie.brief_ttl_days == 30
    assert ie.placeholder == "Blanchardstown Centre, Dublin 15"
    assert ie.address_label == "Street address, town, county or Eircode"
    assert ie.geocoder_attribution == "© OpenStreetMap contributors"
    assert ie.sources_line == (
        "PeeringDB, OpenStreetMap, ESB Networks, Eurostat, CRU, An Coimisiún Pleanála"
    )
    shared = constants.load((constants.EQUIVALENCES_PATH,))
    assert shared.keys() <= ie.constants.keys()
    assert not hasattr(ie, "ground")


def test_ireland_postal_pattern_is_the_eircode(tmp_path: Path) -> None:
    pattern = registry(fakes.settings(tmp_path, regions="us,ie"))["ie"].postal_pattern
    assert pattern.match("D15 T1FD") and pattern.match("d15t1fd")
    assert not pattern.match("20147") and not pattern.match("D15")


def test_us_new_fields_are_todays_strings(tmp_path: Path) -> None:
    us = registry(fakes.settings(tmp_path, regions="us,ie", brief_ttl_days=30))["us"]
    assert us.scenarios is True
    assert us.places_country == ("us",) and us.pulse_countries == ("US",)
    assert us.brief_ttl_days == 0  # the US keeps briefs whatever the setting
    assert us.placeholder == "21715 Filigree Ct, Ashburn, VA"
    assert us.address_label == "Street address, city, state"
    assert us.geocoder_attribution is None
    assert us.sources_line == "PeeringDB, OpenStreetMap, EIA"
    assert isinstance(us.geocoder, CensusGeocoder)


def test_ireland_geocoder_is_nominatim_from_settings(tmp_path: Path) -> None:
    s = fakes.settings(
        tmp_path,
        regions="us,ie",
        nominatim_url="https://nominatim.example.org/",
        nominatim_email="ops@example.org",
        nominatim_min_interval_seconds=2.5,
        geocode_timeout_seconds=7.0,
    )
    g = registry(s)["ie"].geocoder
    assert isinstance(g, NominatimGeocoder)
    assert g.base_url == "https://nominatim.example.org"
    assert (g.email, g.min_interval, g.timeout) == ("ops@example.org", 2.5, 7.0)


async def test_grid_ie_geocoder_fake_answers_the_test_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRID_REGIONS", "us,ie")
    monkeypatch.setenv("GRID_IE_GEOCODER", "fake")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    g = registry(s)["ie"].geocoder
    assert isinstance(g, FakeGeocoder)
    r = await g.geocode("Galway City Hall, College Road, Galway")
    assert r is not None and r.county == "Galway City" and r.country == "IE"


def test_unknown_ie_geocoder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="GRID_IE_GEOCODER"):
        registry(fakes.settings(tmp_path, regions="us,ie", ie_geocoder="google"))


def test_ireland_ground_is_built_lazily(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry never builds ground; make_ground reaches get_ground_ie only
    when called, and imports it then."""
    import app.ground

    seen: list[Path] = []

    def fake_get_ground_ie(settings: Settings, data_dir: Path = IE_DATA_DIR) -> Ground:
        seen.append(data_dir)
        return Ground()

    monkeypatch.setattr(app.ground, "get_ground_ie", fake_get_ground_ie)
    s = fakes.settings(tmp_path, regions="us,ie")
    ie = registry(s)["ie"]
    assert seen == []
    assert isinstance(ie.make_ground(s), Ground)
    assert seen == [IE_DATA_DIR]


def test_importing_regions_does_not_import_irish_providers() -> None:
    code = (
        "import sys, app.regions, app.regions.locale;"
        "bad = [m for m in ('app.ground.eurostat', 'app.ground.geojson_utility')"
        " if m in sys.modules];"
        "print(','.join(bad))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == ""


def test_fake_region_ie_matches_the_real_one(tmp_path: Path) -> None:
    s = fakes.settings(tmp_path, regions="us,ie", brief_ttl_days=14)
    real, fake = registry(s)["ie"], fakes.region_ie(s)
    skip = {"geocoder", "make_ground", "constants"}
    for f in dataclasses.fields(real):
        if f.name not in skip:
            assert getattr(fake, f.name) == getattr(real, f.name), f.name


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
