"""Regions: one per place the engine can brief. A region names its locale, its
geocoder, its curated data under data/regions/<id>/ and its test set. Known
regions are the US and Ireland (`ie`); GRID_REGIONS lists the ids a process
serves, and the default is the US alone.

A region holds no live ground object. The brief service builds one from
`make_ground` when it is created, and that service's `ground` is the one a brief
reads; building it here as well would leave a second, unused copy that drifts
from the service's (a test that injects a fake ground, say)."""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT, Settings
from app.geocode import (
    EIRCODE,
    CensusGeocoder,
    FakeGeocoder,
    Geocoder,
    GeocodeResult,
    NominatimGeocoder,
    snap,
)
from app.ground import US_DATA_DIR, Ground, get_ground
from app.regions.locale import IE_LOCALE, US_LOCALE, Locale, Units
from app.scenario.constants import Constants, load_region
from app.schema import SECTION_IDS


class UnknownRegion(Exception):
    """An id that is not known, or known but not enabled in GRID_REGIONS."""

    def __init__(self, region_id: str) -> None:
        super().__init__(region_id)
        self.id = region_id


@dataclass
class Region:
    id: str
    label: str
    locale: Locale
    countries: frozenset[str]  # ISO codes the country header maps to this region
    geocoder: Geocoder
    make_ground: Callable[[Settings], Ground]
    constants: Constants  # data/regions/<id>/constants.json merged over the shared file
    coverage: frozenset[str]  # section ids this region can make `measured`
    postal_pattern: re.Pattern[str]  # for the what-if input
    data_dir: Path
    test_set: Path
    resolved: Path | None  # the test set's matched spellings, when recorded
    # What the web and /api/health show for the region. Defaults are the US's.
    scenarios: bool = True  # the what-if runs here (US only in step 6)
    places_country: tuple[str, ...] = ("us",)  # Google Places componentRestrictions
    pulse_countries: tuple[str, ...] = ("US",)  # PeeringDB countries the pulse counts
    brief_ttl_days: int = 0  # 0: briefs are kept (until the engine changes)
    placeholder: str = ""  # the address box's example
    address_label: str = ""  # the address box's label
    geocoder_attribution: str | None = None  # shown under a brief when the geocoder needs it
    sources_line: str = ""  # the footer's data line


def _us(settings: Settings) -> Region:
    return Region(
        id="us",
        label="US",
        locale=US_LOCALE,
        countries=frozenset({"US"}),
        geocoder=CensusGeocoder(),
        make_ground=lambda s: get_ground(s, US_DATA_DIR),
        constants=load_region(US_DATA_DIR),
        coverage=frozenset(SECTION_IDS),
        postal_pattern=re.compile(r"^\d{5}$"),
        data_dir=US_DATA_DIR,
        test_set=REPO_ROOT / "eval" / "us" / "addresses.json",
        resolved=REPO_ROOT / "eval" / "us" / "resolved.json",
        scenarios=True,
        places_country=("us",),
        pulse_countries=("US",),
        brief_ttl_days=0,
        placeholder="21715 Filigree Ct, Ashburn, VA",
        address_label="Street address, city, state",
        geocoder_attribution=None,
        sources_line="PeeringDB, OpenStreetMap, EIA",
    )


IE_TEST_SET = REPO_ROOT / "eval" / "ie" / "addresses.json"
# The fixture brief's typed forms (fixtures/briefs/blanchardstown.json): the address
# box's example and the fixture's own display line give its geocode.
IE_FIXTURE_GEOCODE = {
    "display": "Blanchardstown, Fingal, Co. Dublin, D15",
    "lat": 53.393,
    "lon": -6.392,
    "region_code": "IE-D",
    "county": "Fingal",
    "admin_county": "Dublin",
    "postal_code": "D15",
    "matched": "Blanchardstown, Fingal, Co. Dublin, D15",
}
IE_PLACEHOLDER = "Blanchardstown Centre, Dublin 15"


def _ie_geo(block: dict) -> GeocodeResult:
    return GeocodeResult(
        display=str(block["display"]),
        lat=snap(block["lat"]),
        lon=snap(block["lon"]),
        region_code=str(block["region_code"]),
        county=block.get("county"),
        postal_code=str(block.get("postal_code") or ""),
        matched=str(block.get("matched") or block["display"]),
        country="IE",
        admin_county=block.get("admin_county"),
    )


def load_ie_fixtures(path: Path = IE_TEST_SET) -> dict[str, GeocodeResult]:
    """Typed address -> geocode for GRID_IE_GEOCODER=fake: every row of the Irish
    test set that carries a `geocode` block, read at runtime, plus the fixture
    brief's typed forms. FakeGeocoder normalises the keys."""
    out: dict[str, GeocodeResult] = {}
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("addresses", [])
    except (OSError, ValueError, AttributeError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        block = row.get("geocode") if isinstance(row, dict) else None
        if isinstance(block, dict) and row.get("address"):
            try:
                out[str(row["address"])] = _ie_geo(block)
            except (KeyError, TypeError, ValueError):
                continue
    fixture = _ie_geo(IE_FIXTURE_GEOCODE)
    out.setdefault(IE_FIXTURE_GEOCODE["display"], fixture)
    out.setdefault(IE_PLACEHOLDER, fixture)
    return out


def _ie_geocoder(settings: Settings) -> Geocoder:
    kind = settings.ie_geocoder.strip().lower()
    if kind == "fake":
        return FakeGeocoder(by_address=load_ie_fixtures())
    if kind == "nominatim":
        return NominatimGeocoder(
            settings.nominatim_url,
            email=settings.nominatim_email,
            min_interval=settings.nominatim_min_interval_seconds,
            timeout=settings.geocode_timeout_seconds,
        )
    raise ValueError(f"GRID_IE_GEOCODER must be nominatim or fake, not {kind!r}")


def _make_ground_ie(settings: Settings) -> Ground:
    # Imported here: the Irish providers (Eurostat, the ESB map) load only when an
    # Irish service builds its ground, never on `import app.regions`.
    from app.ground import IE_DATA_DIR, get_ground_ie

    return get_ground_ie(settings, IE_DATA_DIR)


def _ie(settings: Settings) -> Region:
    from app.ground import IE_DATA_DIR

    return Region(
        id="ie",
        label="Ireland",
        locale=IE_LOCALE,
        countries=frozenset({"IE"}),
        geocoder=_ie_geocoder(settings),
        make_ground=_make_ground_ie,
        constants=load_region(IE_DATA_DIR),
        coverage=frozenset({"on_your_grid", "your_bill", "protection"}),
        postal_pattern=EIRCODE,
        data_dir=IE_DATA_DIR,
        test_set=IE_TEST_SET,
        resolved=None,
        scenarios=False,
        places_country=("ie",),
        pulse_countries=("IE",),
        brief_ttl_days=settings.brief_ttl_days,
        placeholder=IE_PLACEHOLDER,
        address_label="Street address, town, county or Eircode",
        geocoder_attribution="© OpenStreetMap contributors",
        sources_line=(
            "PeeringDB, OpenStreetMap, ESB Networks, Eurostat, CRU, An Coimisiún Pleanála"
        ),
    )


KNOWN: dict[str, Callable[[Settings], Region]] = {"us": _us, "ie": _ie}


def registry(settings: Settings) -> dict[str, Region]:
    """The regions GRID_REGIONS enables, in its order. An unknown id, or a
    default that is not enabled, raises UnknownRegion: a typo in the deploy
    should stop the process, not serve every address as the US."""
    ids = settings.region_ids
    for rid in ids:
        if rid not in KNOWN:
            raise UnknownRegion(rid)
    if settings.default_region_id not in ids:
        raise UnknownRegion(settings.default_region_id)
    return {rid: KNOWN[rid](settings) for rid in ids}


def region_for(
    regions: Mapping[str, Region],
    *,
    explicit: str | None,
    country_header: str | None,
    default: str,
) -> Region:
    """An explicit id wins and must be enabled; then the country header, when a
    region covers that country; then the default. Blank counts as absent."""
    if explicit is not None and explicit.strip():
        rid = explicit.strip().lower()
        if rid not in regions:
            raise UnknownRegion(rid)
        return regions[rid]
    if country_header and country_header.strip():
        country = country_header.strip().upper()
        for region in regions.values():
            if country in region.countries:
                return region
    return regions[default.strip().lower()]


__all__ = [
    "IE_LOCALE",
    "KNOWN",
    "load_ie_fixtures",
    "US_LOCALE",
    "Locale",
    "Region",
    "UnknownRegion",
    "Units",
    "region_for",
    "registry",
]
