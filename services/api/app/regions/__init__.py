"""Regions: one per place the engine can brief. A region names its locale, its
geocoder, its curated data under data/regions/<id>/ and its test set. The US is
the only one; GRID_REGIONS lists the ids a process serves.

A region holds no live ground object. The brief service builds one from
`make_ground` when it is created, and that service's `ground` is the one a brief
reads; building it here as well would leave a second, unused copy that drifts
from the service's (a test that injects a fake ground, say)."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT, Settings
from app.geocode import CensusGeocoder, Geocoder
from app.ground import US_DATA_DIR, Ground, get_ground
from app.regions.locale import US_LOCALE, Locale, Units
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


def _us(settings: Settings) -> Region:
    # The test set stays at eval/addresses.json until a second region needs eval/<id>/.
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
        test_set=REPO_ROOT / "eval" / "addresses.json",
        resolved=REPO_ROOT / "eval" / "resolved.json",
    )


KNOWN: dict[str, Callable[[Settings], Region]] = {"us": _us}


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
    "KNOWN",
    "US_LOCALE",
    "Locale",
    "Region",
    "UnknownRegion",
    "Units",
    "region_for",
    "registry",
]
