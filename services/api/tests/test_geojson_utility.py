"""The curated GeoJSON utility map (plan 0.5): point in polygon with holes and
overlaps, the edge tolerance, and how gather_ground reports an unreadable file
(failure_note) against a point outside the map (None, no note)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.ground import IE_DATA_DIR, gather_ground
from app.ground.geojson_utility import ESB_FAILURE_NOTE, GeoJsonUtility
from tests.fakes import GEO_IE
from tests.fakes_ie import UTILITY_IE, ie_ground

TWO = Path(__file__).parent / "fixtures" / "geojson_two_polygons.json"
REAL = IE_DATA_DIR / "utilities" / "ie.geojson"


def test_inside_outside_and_hole() -> None:
    u = GeoJsonUtility(TWO)
    a = u.match(2.0, 2.0)
    assert a is not None and a.name == "Alpha Networks" and a.candidates == 1
    assert u.match(5.0, 5.0) is None  # the hole
    assert u.match(15.0, 15.0) is None
    b = u.match(1.0, 21.0)  # Beta's second part
    assert b is not None and b.name == "Beta Grid"


def test_fields_come_from_the_feature() -> None:
    a = GeoJsonUtility(TWO).match(2.0, 2.0)
    assert a is not None
    assert a.raw_name == "Alpha Networks DAC"
    assert a.kind == "DSO" and a.customers == 1000 and a.holding == "Alpha Group"
    assert a.source_url == "https://example.org/alpha/about"
    assert a.source_title == "Alpha Networks, About"
    assert (
        a.quote
        == a.claim_text
        == "Alpha Networks DAC is the licensed operator for the test square."
    )
    assert a.website == "https://example.org/alpha"
    assert a.eia_id is None and a.ba_code is None


def test_overlap_picks_most_customers_and_counts() -> None:
    u = GeoJsonUtility(TWO).match(9.0, 9.0)
    assert u is not None and u.name == "Beta Grid" and u.candidates == 2


def test_edge_tolerance_only_in_the_map_country() -> None:
    u = GeoJsonUtility(TWO, country="IE", tolerance_deg=0.003)
    assert u.match(2.0, -0.002, "IE") is not None  # 0.002 deg west of Alpha's edge
    assert u.match(2.0, -0.002, "GB") is None
    assert u.match(2.0, -0.002, None) is None
    assert u.match(2.0, -0.004, "IE") is None  # past the tolerance
    # Inside the hole is not "near the edge" of anything that counts: the hole's
    # edge is not the outer edge, and the point is 1 deg from it.
    assert u.match(5.0, 5.0, "IE") is None


async def test_locate_uses_the_geocode() -> None:
    u = GeoJsonUtility(TWO)
    geo = replace(GEO_IE, lat=2.0, lon=2.0)
    found = await u.locate(geo)
    assert found is not None and found.name == "Alpha Networks"


async def test_unreadable_file_raises_and_gather_notes_failure(tmp_path: Path) -> None:
    bad = tmp_path / "ie.geojson"
    bad.write_text("{not json", encoding="utf-8")
    u = GeoJsonUtility(bad)
    with pytest.raises(ValueError):
        await u.locate(GEO_IE)
    missing = GeoJsonUtility(tmp_path / "absent.geojson")
    with pytest.raises(OSError):
        await missing.locate(GEO_IE)
    truth = await gather_ground(GEO_IE, ie_ground(utility=u))
    assert truth.utility is None
    assert ESB_FAILURE_NOTE in truth.notes
    assert GeoJsonUtility.failure_note == ESB_FAILURE_NOTE


async def test_outside_the_map_is_none_without_a_note() -> None:
    u = GeoJsonUtility(TWO)
    truth = await gather_ground(replace(GEO_IE, lat=50.0, lon=50.0), ie_ground(utility=u))
    assert truth.utility is None
    assert truth.notes == []


def test_failure_note_can_be_given() -> None:
    assert GeoJsonUtility(TWO, failure_note="x").failure_note == "x"


# --- the committed map (stream E builds it) -------------------------------------------

IN = {
    "Dublin": (53.3498, -6.2603),
    "Cork": (51.8985, -8.4756),
    "Galway": (53.2707, -9.0568),
    "Dundalk": (54.0090, -6.4049),
    "Clones": (54.1792, -7.2306),
    "Lifford": (54.8331, -7.4800),
}
OUT = {
    "Belfast": (54.5973, -5.9301),
    "Derry": (54.9966, -7.3086),
    "Strabane": (54.8274, -7.4633),
    "Newry": (54.1751, -6.3402),
}


@pytest.mark.skipif(not REAL.exists(), reason="data/regions/ie/utilities/ie.geojson not built")
@pytest.mark.parametrize("place", sorted(IN))
def test_real_map_holds_the_republic(place: str) -> None:
    lat, lon = IN[place]
    u = GeoJsonUtility(REAL).match(lat, lon, "IE")
    assert u is not None
    assert u.name == UTILITY_IE.name and u.raw_name == UTILITY_IE.raw_name
    assert u.claim_text == UTILITY_IE.claim_text and u.quote == UTILITY_IE.quote
    assert u.source_url == UTILITY_IE.source_url and u.customers == UTILITY_IE.customers


@pytest.mark.skipif(not REAL.exists(), reason="data/regions/ie/utilities/ie.geojson not built")
@pytest.mark.parametrize("place", sorted(OUT))
def test_real_map_excludes_northern_ireland(place: str) -> None:
    lat, lon = OUT[place]
    u = GeoJsonUtility(REAL)
    assert u.match(lat, lon, "GB") is None
    assert u.match(lat, lon, "IE") is None  # even with the edge tolerance


@pytest.mark.skipif(not REAL.exists(), reason="data/regions/ie/utilities/ie.geojson not built")
def test_real_map_is_one_feature() -> None:
    raw = json.loads(REAL.read_text(encoding="utf-8"))
    assert len(raw["features"]) == 1
