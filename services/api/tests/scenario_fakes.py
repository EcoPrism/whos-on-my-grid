"""Scripted inputs for the scenario tests: a cited-constants table with
fictional pages, a ZIP centroid, ground truth around it and a service wired
to fakes. Every page, operator and figure here is fictional."""

from pathlib import Path
from typing import Any

from app.brief.fetch import FakeFetcher
from app.geocode import FakeZctaCentroids, GeocodeResult
from app.ground import Ground
from app.ground.census import FakeHouseholds
from app.ground.facilities import FakeFacilityDatabase
from app.ground.tariffs import FakeTariffs, TariffEntry
from app.ground.types import GroundFacility, GroundTruth, Utility
from app.ground.utility import HIFLD_PAGE, FakeUtility
from app.llm.fake_provider import KeyedFakeProvider
from app.scenario.cache import ScenarioCache
from app.scenario.constants import Constant, Constants
from app.scenario.pipeline import ScenarioService
from tests import fakes

ZIP_GEO = GeocodeResult(
    display="ZIP 20147, Loudoun County, VA",
    lat=39.0438,
    lon=-77.4874,
    region_code="VA",
    county="Loudoun",
    postal_code="20147",
    matched="zip:20147",
)

_ROWS: list[tuple[str, float, str, str]] = [
    # id, value, unit, quote (each quote is on its page below)
    ("us_home_kwh_per_year", 10791, "kWh per home per year", "average of 10,791 kilowatthours"),
    ("football_field_sq_ft", 57600, "square feet", "a field covers 57,600 square feet"),
    ("dc_load_factor", 0.8, "fraction of nameplate", "campuses run at 80 percent of capacity"),
    ("water_evaporative_l_per_kwh", 1.8, "litres per kWh", "evaporative: 1.8 litres per kWh"),
    ("water_closed_loop_l_per_kwh", 0.2, "litres per kWh", "closed loop: 0.2 litres per kWh"),
    ("us_home_water_gal_per_day", 300, "gallons per home per day", "more than 300 gallons a day"),
    ("dc_acres_per_mw", 0.5, "acres per MW", "about half an acre per megawatt"),
    ("dc_construction_months_lo", 18, "months", "construction took 18 months"),
    ("dc_construction_months_hi", 36, "months", "and up to 36 months"),
    ("dc_permanent_jobs_per_100mw", 50, "jobs per 100 MW", "about 50 permanent jobs per 100 MW"),
    ("dc_tax_usd_per_mw_year", 40000, "USD per MW per year", "tax revenue of $40,000 per MW"),
    (
        "pjm_capacity_usd_per_mw_year",
        100000,
        "USD per MW per year",
        "capacity price of $100,000 per MW-year",
    ),
    ("residential_allocation_lo", 0.3, "fraction", "residential share between 30 percent"),
    ("residential_allocation_hi", 0.4, "fraction", "and 40 percent of capacity costs"),
]


def url(cid: str) -> str:
    return f"https://example.org/constants/{cid}"


def constants(*drop: str) -> Constants:
    return {
        cid: Constant(
            id=cid,
            value=float(value),
            unit=unit,
            as_of="2024",
            source_title=f"Fictional source for {cid}",
            source_url=url(cid),
            quote=quote,
            checked="2026-10-28",
        )
        for cid, value, unit, quote in _ROWS
        if cid not in drop
    }


PAGES: dict[str, str] = {
    url(cid): f"A fictional page. It says {quote}, which is the figure. " * 8
    for cid, _, _, quote in _ROWS
}

FACILITIES = [
    GroundFacility(
        name="Northgate Campus",
        operator="Halvex Digital",
        operator_known=True,
        status="live",
        lat=39.05,
        lon=-77.48,
        distance_km=1.2,
        source_url="https://example.org/registry/northgate",
        source_title="Facility registry",
        providers=("peeringdb",),
    ),
    GroundFacility(
        name="Broad Run Park",
        operator="Orrin Cloud",
        operator_known=True,
        status="under_construction",
        lat=39.03,
        lon=-77.50,
        distance_km=2.5,
        source_url="https://example.org/registry/broad-run",
        source_title="Facility registry",
        providers=("peeringdb",),
    ),
]
PAGES["https://example.org/registry/northgate"] = (
    "Registry. Northgate Campus, Halvex Digital. " * 10
)
PAGES["https://example.org/registry/broad-run"] = "Registry. Broad Run Park, Orrin Cloud. " * 10

UTILITY = Utility(
    name="Northgate Power",
    raw_name="NORTHGATE POWER CO",
    kind="INVESTOR OWNED",
    customers=200_000,
    holding=None,
    source_url="https://example.org/hifld",
    ba_code="PJM",
)
PAGES["https://example.org/hifld"] = "Territories. NORTHGATE POWER CO, investor owned. " * 10
# gather_ground re-chooses the utility and cites the HIFLD page itself.
PAGES[HIFLD_PAGE] = PAGES["https://example.org/hifld"]


def tariff(status: str = "in_force", protects: bool | None = True) -> TariffEntry:
    return TariffEntry(
        jurisdiction="VA",
        utility_match="NORTHGATE",
        name="Schedule LL-1",
        status=status,
        protects_households=protects,
        docket="PUR-0000-00001",
        summary="A fictional large-load schedule.",
        url="https://example.org/tariff",
        title="Fictional commission order",
    )


def truth(**over: Any) -> GroundTruth:
    kw: dict[str, Any] = {
        "facilities": list(FACILITIES),
        "utility": UTILITY,
        "tariff": tariff("none_found", None),
    }
    kw.update(over)
    return GroundTruth(**kw)


SUPPORTED = {"verdict": {"verdict": "supported", "note": "The page says so."}}


def interpretation(**over: Any) -> dict[str, Any]:
    """A scripted interpretation draft for the 300 MW evaporative scenario:
    numbers only from the engine's lines, two claims on the scenario's own
    pages and one on a page the scenario does not cite."""
    draft: dict[str, Any] = {
        "summary": "This is a hypothetical, modelled campus, not a real proposal. At 300 MW it "
        "would use as much electricity as about 194,829 homes and about 2,738,936 gallons of "
        "water a day. Two data centers are already listed within five miles.",
        "confidence": 0.7,
        "claims": [
            {
                "text": "A typical home uses an average of 10,791 kilowatthours a year.",
                "source_title": "Whatever the model calls it",
                "source_url": url("us_home_kwh_per_year"),
                "quote": "average of 10,791 kilowatthours",
                "page": None,
                "confidence": 0.8,
            },
            {
                "text": "Campuses run at 80 percent of capacity.",
                "source_title": "Load factor",
                "source_url": url("dc_load_factor"),
                "quote": "campuses run at 80 percent of capacity",
                "page": None,
                "confidence": 0.8,
            },
            {
                "text": "Data centers use a lot of water.",
                "source_title": "A page the scenario never cited",
                "source_url": "https://example.net/elsewhere",
                "quote": "data centers use a lot of water every day",
                "page": None,
                "confidence": 0.5,
            },
        ],
    }
    draft.update(over)
    return {"draft_scenario": draft}


def service(
    tmp_path: Path,
    *,
    geo: GeocodeResult | None = ZIP_GEO,
    table: Constants | None = None,
    verify: bool = True,
    tariff_entry: TariffEntry | None = None,
    draft: dict[str, Any] | None = None,
    **over: Any,
) -> ScenarioService:
    s = fakes.settings(tmp_path, scenarios_dir=str(tmp_path / "scenarios"), **over)
    ground = Ground(
        facilities=FakeFacilityDatabase(list(FACILITIES)),
        utility=FakeUtility(UTILITY),
        tariffs=FakeTariffs(tariff_entry or tariff("none_found", None)),
    )
    return ScenarioService(
        settings=s,
        zips=FakeZctaCentroids(geo),
        ground=ground,
        households=FakeHouseholds(25_000),
        cache=ScenarioCache(s.scenarios_path),
        fetcher=FakeFetcher(PAGES),
        draft_provider=KeyedFakeProvider(draft) if draft is not None else None,
        verify_provider=KeyedFakeProvider(SUPPORTED) if verify else None,
        constants=constants() if table is None else table,
    )
