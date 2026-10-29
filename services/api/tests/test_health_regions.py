"""/api/health per region (plan C7): every enabled region's fields for the
web, the asked-for region's settings at the top level, its own test set and
examples. The US body is the step-5 one plus the new keys only.

`enable_ie` registers, for one test, the real `_ie` with a fake geocoder and
the two Irish constants a step-6 code path reads, so the pulse lines do not
depend on the committed data file."""

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app import regions as regions_mod
from app.auth import gate
from app.geocode import FakeGeocoder
from app.main import create_app
from app.regions import KNOWN, Region
from app.scenario.constants import Constant
from tests import fakes

# The two constants a step-6 code path reads (plan 2.1), as the region's table
# holds them once data/regions/ie/constants.json is committed.
IE_HOME = Constant(
    id="ie_home_kwh_per_year",
    value=4200.0,
    unit="kWh of electricity per household per year",
    as_of="2017",
    source_title="CRU, Review of Typical Consumption Figures - Decision Paper",
    source_url="https://www.cru.ie/publications/25651/",
    quote=(
        "This decision paper updates the recommended typical annual consumption figure for "
        "electricity to 4,200 kWh and the typical annual consumption for gas to 11,000 kWh."
    ),
    checked="2026-10-29",
    claim=(
        "The CRU's decision paper sets the recommended typical annual electricity "
        "consumption figure at 4,200 kWh."
    ),
)
IE_SHARE = Constant(
    id="ie_dc_share_metered_electricity",
    value=0.23,
    unit="fraction of Ireland's total metered electricity consumption used by data centres",
    as_of="2025",
    source_title="CSO, Data Centres Metered Electricity Consumption 2025, Key Findings",
    source_url=(
        "https://www.cso.ie/en/releasesandpublications/ep/p-dcmec/"
        "datacentresmeteredelectricityconsumption2025/keyfindings/"
    ),
    quote=(
        "The percentage share of total metered electricity consumption used by data centres "
        "rose to 23% in 2025 from 5% in 2015 (See Table 1)."
    ),
    checked="2026-10-29",
    claim=(
        "The CSO reports that data centres used 23% of Ireland's total metered electricity "
        "consumption in 2025, up from 5% in 2015."
    ),
)

US_REGION_INFO = {
    "id": "us",
    "label": "US",
    "countries": ["US"],
    "places_country": ["us"],
    "locale": {"country": "US", "currency": "USD", "units": "us", "language": "en-US"},
    "scenarios": True,
    "placeholder": "21715 Filigree Ct, Ashburn, VA",
    "address_label": "Street address, city, state",
    "geocoder_attribution": None,
    "sources_line": "PeeringDB, OpenStreetMap, EIA",
    "brief_ttl_days": 0,
}
# The keys /api/health had before step 6 (the golden checks their values).
STEP5_KEYS = {
    "ok",
    "mode",
    "region",
    "regions",
    "examples",
    "test_addresses",
    "auth",
    "google_client_id",
    "user",
    "quota_per_user_day",
}
C7_KEYS = {"locale", "scenarios", "places_country", "brief_ttl_days"}


def ie_region(settings: Any) -> Region:
    r = regions_mod._ie(settings)
    table = {**r.constants, IE_HOME.id: IE_HOME, IE_SHARE.id: IE_SHARE}
    return dataclasses.replace(r, geocoder=FakeGeocoder(fakes.GEO_IE), constants=table)


def enable_ie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(KNOWN, "ie", ie_region)


def client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("mode", ["fixtures", "agent"])
async def test_regions_list_every_enabled_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    enable_ie(monkeypatch)
    app = create_app(services=fakes.services(tmp_path, brief_source=mode, brief_ttl_days=30))
    async with client(app) as c:
        body = (await c.get("/api/health")).json()
    assert body["region"] == "us"
    us, ie = body["regions"]
    assert us == US_REGION_INFO
    assert ie == {
        "id": "ie",
        "label": "Ireland",
        "countries": ["IE"],
        "places_country": ["ie"],
        "locale": {"country": "IE", "currency": "EUR", "units": "metric", "language": "en-IE"},
        "scenarios": False,
        "placeholder": "Blanchardstown Centre, Dublin 15",
        "address_label": "Street address, town, county or Eircode",
        "geocoder_attribution": "© OpenStreetMap contributors",
        "sources_line": (
            "PeeringDB, OpenStreetMap, ESB Networks, Eurostat, CRU, An Coimisiún Pleanála"
        ),
        "brief_ttl_days": 30,
    }


async def test_ie_health_has_its_own_settings_and_test_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_ie(monkeypatch)
    app = create_app(services=fakes.services(tmp_path, brief_ttl_days=7))
    ie = app.state.regions["ie"]
    async with client(app) as c:
        body = (await c.get("/api/health?region=ie")).json()
        assert (await c.get("/api/health?region=IE")).json() == body
    assert body["region"] == "ie"
    assert body["scenarios"] is False and body["places_country"] == ["ie"]
    assert body["locale"]["currency"] == "EUR" and body["locale"]["units"] == "metric"
    assert body["brief_ttl_days"] == ie.brief_ttl_days == 7
    expected = [r["address"] for r in gate.test_set_rows(ie.test_set, None)]
    assert expected and body["test_addresses"] == expected
    assert "Blanchardstown Centre, Blanchardstown, Dublin 15" in body["test_addresses"]
    us_addresses = {r["address"] for r in gate.test_set_rows()}
    assert not us_addresses & set(body["test_addresses"])


async def test_examples_are_the_regions_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_ie(monkeypatch)
    app = create_app(services=fakes.services(tmp_path, brief_source="fixtures"))
    async with client(app) as c:
        us = (await c.get("/api/health")).json()["examples"]
        ie = (await c.get("/api/health?region=ie")).json()["examples"]
    assert {e["key"] for e in us} == {"ashburn", "boise", "kenosha", "rural_sd", "tucson"}
    assert all(e["currency"] == "USD" and e["language"] == "en-US" for e in us)
    # fixtures/briefs/blanchardstown.json, the one Irish fixture.
    assert [e["key"] for e in ie] == ["blanchardstown"]
    assert ie[0]["currency"] == "EUR" and ie[0]["language"] == "en-IE"
    assert ie[0]["brief_id"] == fakes.IE_BRIEF_ID


async def test_us_body_is_step5_plus_the_new_keys(tmp_path: Path) -> None:
    async with client(create_app(fakes.service(tmp_path))) as c:
        body = (await c.get("/api/health")).json()
    assert set(body) == STEP5_KEYS | C7_KEYS
    assert body["regions"] == [US_REGION_INFO]
    assert body["locale"] == US_REGION_INFO["locale"]
    assert body["scenarios"] is True and body["places_country"] == ["us"]
    assert body["brief_ttl_days"] == 0
    # The step-5 projection of a regions[] row.
    assert [{"id": r["id"], "label": r["label"]} for r in body["regions"]] == [
        {"id": "us", "label": "US"}
    ]
