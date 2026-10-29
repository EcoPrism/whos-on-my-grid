"""ZIP to a point from the Census ZCTA gazetteer, state and county from the
FCC area API. Saved payloads only; no network."""

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.geocode import (
    FCC_AREA_URL,
    GAZETTEER_ZCTA_URL,
    GeocodeUnavailable,
    ZctaCentroids,
    parse_gazetteer,
)

# The 2025 file is pipe-delimited; earlier years are tab-delimited.
GAZ_2025 = (
    "GEOID|GEOIDFQ|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG\n"
    "00601|860Z200US00601|166836450|798613|64.416|0.308|18.180555|-66.749961\n"
    "20147|860Z200US20147|62046374|1009553|23.956|0.39|39.041947|-77.47813\n"
)
GAZ_2023 = (
    "GEOID\tALAND\tAWATER\tALAND_SQMI\tAWATER_SQMI\tINTPTLAT\t"
    "INTPTLONG                                                                                                               \n"
    "20147\t62046374\t1009553\t23.956\t0.39\t39.041947\t-77.47813\n"
)
FCC = {
    "results": [
        {"county_fips": "51107", "county_name": "Loudoun County", "state_code": "VA"},
    ]
}


def _zip(text: str, name: str = "2025_Gaz_zcta_national.txt") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def _centroids(tmp_path: Path, *, fcc=FCC, years=(2025, 2024)) -> tuple[ZctaCentroids, list[str]]:
    z = ZctaCentroids(tmp_path, years=list(years), fcc_timeout=5)
    calls: list[str] = []

    async def get_bytes(url: str) -> bytes:
        calls.append(url)
        if url == GAZETTEER_ZCTA_URL.format(year=2025):
            return _zip(GAZ_2025)
        raise httpx.HTTPStatusError(
            "404", request=httpx.Request("GET", url), response=httpx.Response(404)
        )

    async def get_json(url, params, timeout):
        calls.append(url)
        assert url == FCC_AREA_URL
        if isinstance(fcc, Exception):
            raise fcc
        return fcc

    z._get_bytes = get_bytes  # type: ignore[method-assign]
    z._get_json = get_json  # type: ignore[method-assign]
    return z, calls


def test_parse_gazetteer_reads_pipe_and_tab_files() -> None:
    assert parse_gazetteer(GAZ_2025)["20147"] == (39.041947, -77.47813)
    assert parse_gazetteer(GAZ_2023) == {"20147": (39.041947, -77.47813)}
    assert parse_gazetteer("") == {}
    assert parse_gazetteer("no|columns\n1|2\n") == {}


async def test_locate_gives_point_state_and_county(tmp_path: Path) -> None:
    z, calls = _centroids(tmp_path)
    r = await z.locate("20147")
    assert r is not None
    assert r.display == "ZIP 20147, Loudoun County, VA"
    assert (r.lat, r.lon) == (39.041947, -77.47813)
    assert r.state == "VA" and r.county == "Loudoun"
    assert r.zip == "20147" and r.matched == "zip:20147"
    assert calls == [GAZETTEER_ZCTA_URL.format(year=2025), FCC_AREA_URL]


async def test_gazetteer_is_downloaded_once_and_holds_nothing_per_zip(tmp_path: Path) -> None:
    z, calls = _centroids(tmp_path)
    await z.locate("20147")
    await z.locate("00601")
    assert calls.count(GAZETTEER_ZCTA_URL.format(year=2025)) == 1
    saved = json.loads((tmp_path / "gazetteer_zcta.json").read_text(encoding="utf-8"))
    assert saved["year"] == 2025 and set(saved["zctas"]) == {"00601", "20147"}
    assert [p.name for p in tmp_path.iterdir()] == ["gazetteer_zcta.json"]

    # A second instance reads the cache and downloads nothing.
    z2, calls2 = _centroids(tmp_path)
    assert (await z2.locate("20147")) is not None
    assert calls2 == [FCC_AREA_URL]


async def test_falls_back_to_an_older_year(tmp_path: Path) -> None:
    z, calls = _centroids(tmp_path, years=(2026, 2025))
    assert (await z.locate("20147")) is not None
    assert calls[:2] == [GAZETTEER_ZCTA_URL.format(year=2026), GAZETTEER_ZCTA_URL.format(year=2025)]


async def test_not_a_zcta_or_not_five_digits_is_none(tmp_path: Path) -> None:
    z, calls = _centroids(tmp_path)
    assert await z.locate("99999") is None
    assert await z.locate("2014") is None
    assert await z.locate("abcde") is None
    assert FCC_AREA_URL not in calls


async def test_fcc_without_a_county_still_locates(tmp_path: Path) -> None:
    z, _ = _centroids(tmp_path, fcc={"results": [{"county_name": None, "state_code": "PR"}]})
    r = await z.locate("00601")
    assert r is not None and r.display == "ZIP 00601, PR" and r.county is None


async def test_fcc_without_a_state_is_none(tmp_path: Path) -> None:
    z, _ = _centroids(tmp_path, fcc={"results": []})
    assert await z.locate("20147") is None


async def test_fcc_down_is_unavailable(tmp_path: Path) -> None:
    z, _ = _centroids(tmp_path, fcc=httpx.ConnectError("fcc down"))
    with pytest.raises(GeocodeUnavailable):
        await z.locate("20147")


async def test_gazetteer_unreachable_is_unavailable(tmp_path: Path) -> None:
    z, _ = _centroids(tmp_path, years=(2024,))
    with pytest.raises(GeocodeUnavailable):
        await z.locate("20147")


async def test_zip_is_never_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    z, _ = _centroids(tmp_path)
    with caplog.at_level("DEBUG"):
        await z.locate("20147")
    assert "20147" not in caplog.text


async def test_gazetteer_failure_is_remembered_for_a_cool_down(tmp_path: Path) -> None:
    z, calls = _centroids(tmp_path, years=(2023,))
    with pytest.raises(GeocodeUnavailable):
        await z.locate("20147")
    first = len(calls)
    with pytest.raises(GeocodeUnavailable):
        await z.locate("20147")
    assert len(calls) == first  # no second download inside the cool-down
    z._failed_at -= z.retry_after_s + 1
    with pytest.raises(GeocodeUnavailable):
        await z.locate("20147")
    assert len(calls) > first
