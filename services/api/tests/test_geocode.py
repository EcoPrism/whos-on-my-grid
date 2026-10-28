"""The Census geocoder, with its county endpoint down, still geocodes: the
plain locations endpoint answers and the county comes from the FCC area API."""

import httpx
import pytest

from app.geocode import CENSUS_LOCATIONS_URL, CENSUS_URL, FCC_AREA_URL, CensusGeocoder

MATCH = {
    "result": {
        "addressMatches": [
            {
                "matchedAddress": "6401 STARTOWN RD, MAIDEN, NC, 28650",
                "coordinates": {"x": -81.26, "y": 35.577},
                "addressComponents": {"state": "NC", "zip": "28650"},
            }
        ]
    }
}


def _with_county(payload: dict) -> dict:
    out = {"result": {"addressMatches": [dict(payload["result"]["addressMatches"][0])]}}
    out["result"]["addressMatches"][0]["geographies"] = {"Counties": [{"BASENAME": "Catawba"}]}
    return out


async def test_geographies_endpoint_gives_the_county_directly() -> None:
    g = CensusGeocoder()
    calls: list[str] = []

    async def fake(url, params, timeout):
        calls.append(url)
        return _with_county(MATCH)

    g._get_json = fake  # type: ignore[method-assign]
    r = await g.geocode("6401 Startown Road, Maiden, NC 28650")
    assert r is not None and r.county == "Catawba" and r.state == "NC"
    assert calls == [CENSUS_URL]


async def test_falls_back_to_locations_and_fcc_when_geographies_is_down() -> None:
    g = CensusGeocoder()
    calls: list[str] = []

    async def fake(url, params, timeout):
        calls.append(url)
        if url == CENSUS_URL:
            raise httpx.ConnectError("502 from the geographies endpoint")
        if url == CENSUS_LOCATIONS_URL:
            assert "vintage" not in params
            return MATCH
        if url == FCC_AREA_URL:
            return {"results": [{"county_name": "Catawba County", "state_code": "NC"}]}
        raise AssertionError(url)

    g._get_json = fake  # type: ignore[method-assign]
    r = await g.geocode("6401 Startown Road, Maiden, NC 28650")
    assert r is not None
    assert r.county == "Catawba" and r.state == "NC" and r.zip == "28650"
    assert r.display == "Startown Rd, Maiden, NC 28650"
    assert calls == [CENSUS_URL, CENSUS_LOCATIONS_URL, FCC_AREA_URL]


async def test_fcc_failure_leaves_the_county_unknown_not_the_brief() -> None:
    g = CensusGeocoder()

    async def fake(url, params, timeout):
        if url == CENSUS_URL:
            raise httpx.ReadTimeout("slow")
        if url == CENSUS_LOCATIONS_URL:
            return MATCH
        raise httpx.ConnectError("fcc down")

    g._get_json = fake  # type: ignore[method-assign]
    r = await g.geocode("6401 Startown Road, Maiden, NC 28650")
    assert r is not None and r.county is None and r.lat == 35.577


async def test_both_census_endpoints_down_is_unavailable() -> None:
    from app.geocode import GeocodeUnavailable

    g = CensusGeocoder()

    async def fake(url, params, timeout):
        raise httpx.ConnectError("down")

    g._get_json = fake  # type: ignore[method-assign]
    with pytest.raises(GeocodeUnavailable):
        await g.geocode("6401 Startown Road, Maiden, NC 28650")
