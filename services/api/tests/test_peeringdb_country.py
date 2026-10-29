"""PeeringDB by country (plan C3): the US URL and cache stay byte for byte, Ireland
asks for IE and GB, the pulse counts one country, and a facility whose name is a
person's is shown by its org_name. No network: snapshots are written to tmp."""

import json
import time
from pathlib import Path

from app.ground import IE_DATA_DIR
from app.ground.facilities import (
    PEERINGDB_URL,
    FacilityDatabase,
    PeeringDBSource,
    load_name_fixes,
    peeringdb_url,
)

# The step-5 literal, copied from b02e7d1: the US request must not change.
US_URL = (
    "https://www.peeringdb.com/api/fac?country=US&status=ok&limit=5000"
    "&fields=id,name,org_name,address1,city,state,latitude,longitude,created"
)
IE_GB_URL = (
    "https://www.peeringdb.com/api/fac?country__in=IE,GB&status=ok&limit=5000"
    "&fields=id,name,org_name,address1,city,state,country,latitude,longitude,created"
)
DUNDALK = (54.0090, -6.4049)

RECORDS = [
    {
        "id": 9101,
        "name": "Fictional Dublin West",
        "org_name": "Fictional Colo Ltd",
        "country": "IE",
        "latitude": 53.39,
        "longitude": -6.39,
        "created": "2020-01-01T00:00:00Z",
    },
    {
        "id": 9102,
        "name": "Fictional Border North",
        "org_name": "Fictional Colo Ltd",
        "country": "GB",
        "latitude": 54.10,
        "longitude": -6.37,
        "created": "2020-01-01T00:00:00Z",
    },
    {
        "id": 4256,
        "name": "A Person's Name",
        "org_name": "Fictional Org Ltd",
        "country": "IE",
        "latitude": 54.0,
        "longitude": -6.41,
        "created": "2020-01-01T00:00:00Z",
    },
]


def _snapshot(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": time.time(), "data": data}), encoding="utf-8")


def test_us_url_and_cache_are_unchanged(tmp_path: Path) -> None:
    assert PEERINGDB_URL == US_URL
    assert peeringdb_url(("US",)) == US_URL
    src = PeeringDBSource(tmp_path)
    assert src.url == US_URL
    assert src.path == tmp_path / "peeringdb_fac.json"
    assert src.countries == ("US",)


def test_ie_url_and_cache(tmp_path: Path) -> None:
    assert peeringdb_url(("IE", "GB")) == IE_GB_URL
    assert peeringdb_url(("ie",)) == IE_GB_URL.replace("country__in=IE,GB", "country=IE")
    src = PeeringDBSource(tmp_path, countries=("IE", "GB"))
    assert src.url == IE_GB_URL
    assert src.path == tmp_path / "peeringdb_fac_ie_gb.json"


async def test_summary_counts_one_country(tmp_path: Path) -> None:
    src = PeeringDBSource(tmp_path, countries=("IE", "GB"))
    _snapshot(src.path, RECORDS)
    ie = await src.summary(("IE",))
    assert ie["total"] == 2 and ie["countries"] == ["IE"]
    both = await src.summary()
    assert both["total"] == 3 and both["countries"] == ["IE", "GB"]
    db = FacilityDatabase([src], overrides=[])
    assert (await db.summary(("IE",)))["total"] == 2


async def test_us_snapshot_without_country_field_counts_as_us(tmp_path: Path) -> None:
    src = PeeringDBSource(tmp_path)
    _snapshot(src.path, [{k: v for k, v in r.items() if k != "country"} for r in RECORDS])
    s = await src.summary(("US",))
    assert s["total"] == 3 and s["countries"] == ["US"]
    assert (await src.summary())["total"] == 3


async def test_briefs_keep_northern_ireland_sites_near_the_border(tmp_path: Path) -> None:
    src = PeeringDBSource(tmp_path, countries=("IE", "GB"))
    _snapshot(src.path, RECORDS)
    keys = {s.key for s in await src.near(*DUNDALK, 16.09)}
    assert "fac/9102" in keys  # GB, about 11 km away
    assert "fac/9101" not in keys  # Dublin, about 70 km away


async def test_name_fix_shows_org_name(tmp_path: Path) -> None:
    src = PeeringDBSource(tmp_path, countries=("IE", "GB"), name_fixes=frozenset({4256}))
    _snapshot(src.path, RECORDS)
    sites = {s.key: s for s in await src.near(*DUNDALK, 16.09)}
    assert sites["fac/4256"].name == "Fictional Org Ltd"
    assert sites["fac/4256"].operator == "Fictional Org Ltd"
    assert sites["fac/9102"].name == "Fictional Border North"
    plain = PeeringDBSource(tmp_path, countries=("IE", "GB"))
    unfixed = {s.key: s for s in await plain.near(*DUNDALK, 16.09)}
    assert unfixed["fac/4256"].name == "A Person's Name"


async def test_name_fixed_claim_names_only_the_organization(tmp_path: Path) -> None:
    """The cited page lists the facility under its own (hidden) name, so the engine
    claim may not say it is "named" the org: it names the organization only."""
    from app.brief.assemble import _facility_claim, _facility_quote
    from app.ground.facilities import _facility

    src = PeeringDBSource(tmp_path, countries=("IE", "GB"), name_fixes=frozenset({4256}))
    _snapshot(src.path, RECORDS)
    sites = {s.key: s for s in await src.near(*DUNDALK, 16.09)}
    assert sites["fac/4256"].name_from_org
    assert not sites["fac/9102"].name_from_org
    fixed = _facility([sites["fac/4256"]], *DUNDALK)
    assert fixed.name_from_org
    claim = _facility_claim(fixed)
    assert claim == "PeeringDB lists a facility under the organization Fictional Org Ltd."
    assert "named" not in claim
    assert _facility_quote(fixed) == "Fictional Org Ltd"
    plain = _facility([sites["fac/9102"]], *DUNDALK)
    assert not plain.name_from_org
    assert _facility_claim(plain).startswith("PeeringDB lists a facility named Fictional Border")


def test_load_name_fixes(tmp_path: Path) -> None:
    assert load_name_fixes(tmp_path / "absent.json") == frozenset()
    f = tmp_path / "facilities.json"
    f.write_text(json.dumps({"entries": []}), encoding="utf-8")
    assert load_name_fixes(f) == frozenset()
    f.write_text(json.dumps({"entries": [], "peeringdb_use_org_name": [4256]}), encoding="utf-8")
    assert load_name_fixes(f) == frozenset({4256})


def test_committed_ie_file_fixes_4256() -> None:
    path = IE_DATA_DIR / "facilities.json"
    if not path.exists():
        return  # stream E writes it
    assert 4256 in load_name_fixes(path)
