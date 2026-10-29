"""Households per ZIP from the ACS 5-year table B11001. Saved payloads only;
no network."""

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.ground.census import (
    ALL_ZCTAS,
    CENSUS_API_URL,
    DATA_CENSUS_API_URL,
    AcsHouseholds,
    FakeHouseholds,
    parse_census_api,
    parse_data_census,
)

# data.census.gov's table API, trimmed to the columns that matter.
DATA_CENSUS_2024 = {
    "response": {
        "data": [
            ["B11001_002E", "B11001_001E", "NAME", "GEO_ID", "B11001_001M"],
            ["17783", "25178", "ZCTA5 20147", "860Z200US20147", "753"],
            ["5000", "6200", "ZCTA5 28650", "860Z200US28650", "300"],
            [None, "-666666666", "ZCTA5 00001", "860Z200US00001", None],
            ["0", "0", "ZCTA5 99999", "860Z200US99999", "11"],
        ],
        "objectId": "ACSDT5Y2024.B11001",
    }
}
# api.census.gov, header row then one row per ZCTA.
CENSUS_API_2024 = [
    ["B11001_001E", "zip code tabulation area"],
    ["25178", "20147"],
    ["6200", "28650"],
]


def _not_found(url: str) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "400", request=httpx.Request("GET", url), response=httpx.Response(400)
    )


def _acs(
    tmp_path: Path, *, key: str = "", census_api: Any = None, years=(2025, 2024), **kw: Any
) -> tuple[AcsHouseholds, list[tuple[str, dict]]]:
    h = AcsHouseholds(tmp_path, api_key=key, years=list(years), **kw)
    calls: list[tuple[str, dict]] = []

    async def get_json(url: str, params: dict[str, str]) -> Any:
        calls.append((url, params))
        if url == DATA_CENSUS_API_URL and params["id"] == "ACSDT5Y2024.B11001":
            assert params["g"] == ALL_ZCTAS
            return DATA_CENSUS_2024
        if url == CENSUS_API_URL.format(year=2024) and census_api is not None:
            if isinstance(census_api, Exception):
                raise census_api
            return census_api
        raise _not_found(url)

    h._get_json = get_json  # type: ignore[method-assign]
    return h, calls


def test_parsers_skip_missing_and_sentinel_values() -> None:
    assert parse_data_census(DATA_CENSUS_2024) == {"20147": 25178, "28650": 6200, "99999": 0}
    assert parse_census_api(CENSUS_API_2024) == {"20147": 25178, "28650": 6200}
    assert parse_data_census({}) == {} and parse_census_api([]) == {}


async def test_for_zcta_cites_a_keyless_page_with_the_count(tmp_path: Path) -> None:
    h, _ = _acs(tmp_path)
    r = await h.for_zcta("20147")
    assert r is not None
    assert r.count == 25178 and r.quote == "25178"
    assert r.as_of == "ACS 5-year 2024"
    assert r.source_url == (
        "https://data.census.gov/api/access/data/table?id=ACSDT5Y2024.B11001&g=860Z200US20147"
    )
    assert "B11001" in r.source_title and "20147" in r.source_title


async def test_newest_published_year_wins_and_the_table_is_fetched_once(tmp_path: Path) -> None:
    h, calls = _acs(tmp_path)
    await h.for_zcta("20147")
    await h.for_zcta("28650")
    ids = [p.get("id") for u, p in calls]
    assert ids == ["ACSDT5Y2025.B11001", "ACSDT5Y2024.B11001"]
    saved = json.loads((tmp_path / "acs" / "b11001_zcta.json").read_text(encoding="utf-8"))
    assert saved["year"] == 2024 and saved["households"]["20147"] == 25178
    # Only the national table is on disk, nothing named for a ZIP.
    assert [p.name for p in (tmp_path / "acs").iterdir()] == ["b11001_zcta.json"]

    h2, calls2 = _acs(tmp_path)
    assert (await h2.for_zcta("20147")).count == 25178  # type: ignore[union-attr]
    assert calls2 == []


async def test_stale_cache_kept_when_no_newer_year_answers(tmp_path: Path) -> None:
    h, _ = _acs(tmp_path)
    await h.for_zcta("20147")
    path = tmp_path / "acs" / "b11001_zcta.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["fetched_at"] = time.time() - 60 * 86_400
    path.write_text(json.dumps(saved), encoding="utf-8")

    h2, calls2 = _acs(tmp_path)
    r = await h2.for_zcta("20147")
    assert r is not None and r.as_of == "ACS 5-year 2024"
    # Only years newer than the one held are tried.
    assert [p.get("id") for u, p in calls2] == ["ACSDT5Y2025.B11001"]
    assert json.loads(path.read_text(encoding="utf-8"))["fetched_at"] > saved["fetched_at"]


async def test_key_uses_census_api_and_keeps_the_key_out_of_the_citation(tmp_path: Path) -> None:
    h, calls = _acs(tmp_path, key="k-secret", census_api=CENSUS_API_2024, years=(2024,))
    r = await h.for_zcta("20147")
    assert r is not None and r.count == 25178
    assert calls[0][0] == CENSUS_API_URL.format(year=2024)
    assert calls[0][1]["key"] == "k-secret"
    assert "k-secret" not in r.source_url and "key" not in r.source_url
    assert len(calls) == 1


async def test_key_rejected_falls_back_to_data_census(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    h, calls = _acs(tmp_path, key="k-secret", census_api=_not_found("x"), years=(2024,))
    with caplog.at_level("DEBUG"):
        r = await h.for_zcta("20147")
    assert r is not None and r.count == 25178
    assert [u for u, _ in calls] == [CENSUS_API_URL.format(year=2024), DATA_CENSUS_API_URL]
    assert "k-secret" not in caplog.text


async def test_missing_zero_or_bad_zip_is_none(tmp_path: Path) -> None:
    h, _ = _acs(tmp_path)
    assert await h.for_zcta("00001") is None  # sentinel, not a count
    assert await h.for_zcta("99999") is None  # no households to share among
    assert await h.for_zcta("12345") is None  # not in the table
    assert await h.for_zcta("2014") is None


async def test_unreachable_is_none_not_an_error(tmp_path: Path) -> None:
    h, _ = _acs(tmp_path, years=(2025,))
    assert await h.for_zcta("20147") is None


async def test_zip_is_never_logged_or_named_on_disk(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    h, _ = _acs(tmp_path)
    with caplog.at_level("DEBUG"):
        await h.for_zcta("20147")
    assert "20147" not in caplog.text
    names = [str(p) for p in tmp_path.rglob("*")]
    assert not any("20147" in os.path.basename(n) for n in names)


async def test_fake_households() -> None:
    f = FakeHouseholds(1000)
    r = await f.for_zcta("20147")
    assert r is not None and r.count == 1000 and r.quote == "1000" and f.calls == 1
    assert await FakeHouseholds(None).for_zcta("20147") is None
