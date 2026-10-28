"""Full mode: the engine's facilities, utility and prices are the brief's;
Spark's drafts supply sentences and what no dataset holds."""

from app.ground import (
    FakeFacilityDatabase,
    FakePrices,
    FakeTariffs,
    FakeUtility,
    FakeUtilityPrices,
    Ground,
)
from app.ground.tariffs import TariffEntry
from app.ground.types import GroundFacility, OperatorSource, PriceSeries, Utility
from app.schema import SECTION_IDS, validate_brief
from tests import fakes

FACILITIES = [
    GroundFacility(
        name="Northgate Campus DC1-DC9",
        operator="Halvex Digital",
        operator_known=True,
        status="live",
        lat=39.019,
        lon=-77.455,
        distance_km=0.4,
        source_url="https://www.peeringdb.com/fac/1",
        source_title="PeeringDB facility 1",
        buildings=9,
        providers=("osm", "peeringdb"),
    ),
    GroundFacility(
        name="4 unnamed data-center buildings",
        operator="Operator not recorded in OpenStreetMap",
        operator_known=False,
        status="under_construction",
        lat=39.03,
        lon=-77.44,
        distance_km=2.3,
        source_url="https://www.openstreetmap.org/way/77",
        source_title="OpenStreetMap way 77",
        buildings=4,
        providers=("osm",),
    ),
]
UTILITY = Utility(
    name="Dominion Energy Virginia",
    raw_name="VIRGINIA ELECTRIC & POWER CO",
    kind="INVESTOR OWNED",
    customers=2_662_831,
    holding="DOMINION RESOURCES",
    source_url="https://example.org/hifld",
    eia_id="19876",
)
PRICE = PriceSeries(
    state="VA",
    rate_now=0.16,
    rate_then=0.14,
    trend_pct=14.3,
    typical_kwh_month=1000.0,
    window_months=24,
    latest=(2026, 8),
    source_url="https://example.org/eia861m",
    source_title="EIA-861M",
    data_status="Preliminary",
    scope="state",
    as_of="2026-08",
    label="VA statewide",
    latest_month_rate=0.165,
)


def ground(**over):
    kw = {
        "facilities": FakeFacilityDatabase(FACILITIES),
        "utility": FakeUtility(UTILITY),
        "prices": FakePrices(PRICE),
    }
    kw.update(over)
    return Ground(**kw)


async def test_engine_facts_own_the_brief(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground()
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    assert brief["source_mode"] == "full"
    assert brief["address"]["utility"] == "Dominion Energy Virginia"

    grid = brief["sections"]["on_your_grid"]
    assert grid["status"] == "measured" and grid["confidence"] == 0.9
    names = [f["name"] for f in grid["facilities"]]
    assert names == ["Northgate Campus DC1-DC9", "4 unnamed data-center buildings"]
    # Spark's draft listed the same campus with a load figure: merged by name.
    assert (
        grid["facilities"][0]["estimated_mw"] == 180
        and grid["facilities"][0]["mw_basis"] == "reported"
    )
    assert grid["facilities"][0]["lat"] == 39.019
    # Spark's own extra facility (Broad Run, under construction) is not in the database: dropped.
    assert "Broad Run Technology Park" not in names
    # Spark's summary is kept; the engine's claims are checkable records.
    assert grid["summary"].startswith("Two data-center campuses")
    engine_claims = [c for c in brief["claims"] if c["drafted_by"] == "engine"]
    assert {c["source"]["url"] for c in engine_claims} >= {
        "https://www.peeringdb.com/fac/1",
        "https://www.openstreetmap.org/way/77",
        "https://atlas.eia.gov/datasets/eia::electric-retail-service-territories/about",
        "https://example.org/eia861m",
    }

    # Coming keeps Spark's announced campus, which no database can hold.
    coming = [f["name"] for f in brief["sections"]["coming"]["facilities"]]
    assert coming == ["Waxpool North"]

    bill = brief["sections"]["your_bill"]
    assert bill["status"] == "modelled" and bill["price"]["rate_now"] == 0.16
    assert bill["price"]["typical_household_kwh_month"] == 1000.0
    assert brief["headline"]["ai_rent_usd_per_month"] == 20.0
    assert brief["headline"]["ai_rent_range_usd_per_month"] == [16.0, 24.0]
    assert brief["headline"]["one_liner"].startswith(
        "2 data centers within five miles are on your local grid, served by Dominion Energy Virginia (1 under construction)."
    )

    topics = [line["topic"] for line in brief["at_your_house"]]
    assert topics == ["bill", "water", "noise"]  # the order people feel them
    noise = brief["at_your_house"][2]
    assert noise["status"] == "modelled" and "0.2 miles" in noise["text"]
    assert noise["sources"][0]["url"] == "https://www.peeringdb.com/fac/1"
    assert topics.count("noise") == 1  # Spark's noise line is replaced by the engine's
    assert "Facilities, utility and prices from public data" in brief["card"]["footer"]


BEYOND = GroundFacility(
    name="Meta (5 buildings)",
    operator="Meta",
    operator_known=True,
    status="live",
    lat=39.1,
    lon=-77.4,
    distance_km=10.8,
    source_url="https://www.openstreetmap.org/way/900",
    source_title="OpenStreetMap way 900",
    buildings=5,
    providers=("osm",),
)


async def test_sparse_ring_names_the_campus_beyond_it(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(facilities=FakeFacilityDatabase([], beyond=BEYOND))
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    grid = brief["sections"]["on_your_grid"]
    assert grid["facilities"] == []
    assert grid["beyond_ring"]["operator"] == "Meta" and grid["beyond_ring"]["distance_km"] == 10.8
    assert "beyond the five-mile ring is Meta (5 buildings), 6.7 miles to the" in grid["summary"]
    urls = [c["source"]["url"] for c in brief["claims"] if c["drafted_by"] == "engine"]
    assert "https://www.openstreetmap.org/way/900" in urls
    # The map's facility count and the headline stay at zero: it is not in the ring.
    assert brief["card"]["lines"][0].startswith("No data centers listed within 5 miles")


async def test_curated_operator_gets_its_own_claim(tmp_path) -> None:
    apple = GroundFacility(
        name="Apple Maiden data center",
        operator="Apple",
        operator_known=True,
        status="live",
        lat=39.02,
        lon=-77.45,
        distance_km=1.2,
        source_url="https://www.openstreetmap.org/way/116005354",
        source_title="OpenStreetMap way 116005354",
        buildings=2,
        providers=("osm",),
        operator_source=OperatorSource(
            url="https://example.org/apple",
            title="Apple Newsroom",
            quote="Apple is expanding the capacity of its data center in Maiden.",
            claim="Apple operates a data center in Maiden, North Carolina.",
        ),
    )
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(facilities=FakeFacilityDatabase([apple]))
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    assert brief["sections"]["on_your_grid"]["facilities"][0]["operator"] == "Apple"
    engine = [c for c in brief["claims"] if c["drafted_by"] == "engine"]
    by_url = {c["source"]["url"]: c for c in engine}
    # The map record's claim says what the map shows: buildings, no operator.
    assert "operator" not in by_url["https://www.openstreetmap.org/way/116005354"]["text"]
    # The operator has its own claim against the page that names it.
    assert by_url["https://example.org/apple"]["text"].startswith("Apple operates")
    assert by_url["https://example.org/apple"]["source"]["quote"].startswith("Apple is expanding")


async def test_no_facilities_calms_the_brief(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(facilities=FakeFacilityDatabase([]))
    brief = await svc.brief_for_address("1 Main St, Bozeman, MT")
    validate_brief(brief)
    grid = brief["sections"]["on_your_grid"]
    assert grid["facilities"] == [] and grid["status"] == "measured"
    assert brief["headline"]["one_liner"].startswith("No data-center facility within five miles")
    # $20/mo would be "critical" on price alone; with nothing nearby it is capped.
    assert brief["headline"]["band"] == "medium"
    topics = [line["topic"] for line in brief["at_your_house"]]
    # Spark's water line asserts a permitted withdrawal: nothing to be about, dropped.
    assert "water" not in topics
    assert brief["at_your_house"][1]["text"].startswith("No data-center building within five miles")


async def test_engine_writes_the_sections_spark_dropped(tmp_path) -> None:
    drafts = fakes.drafts()
    del drafts["draft_on_your_grid"]
    del drafts["draft_your_bill"]
    svc = fakes.service(tmp_path, brief_source="full", draft_responses=drafts)
    svc.ground = ground()
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    grid = brief["sections"]["on_your_grid"]
    assert grid["status"] == "measured"
    assert grid["summary"].startswith("2 data-center facilities are within five miles")
    assert "Northgate Campus DC1-DC9, 0.2 miles away, operated by Halvex Digital" in grid["summary"]
    bill = brief["sections"]["your_bill"]
    assert bill["status"] == "modelled" and bill["price"]["attribution"] is None
    assert "16.0 cents per kWh in the twelve months to August 2026" in bill["summary"]
    assert brief["headline"]["ai_rent_usd_per_month"] == 20.0
    assert any(line.startswith("2 data centers within 5 miles") for line in brief["card"]["lines"])
    assert any("+$20/mo" in line for line in brief["card"]["lines"])


async def test_provider_failures_fall_back_to_spark_with_a_note(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(
        facilities=FakeFacilityDatabase(fail=True),
        utility=FakeUtility(fail=True),
        prices=FakePrices(fail=True),
    )
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    grid = brief["sections"]["on_your_grid"]
    assert grid["status"] == "reported"  # Spark's list, honestly labelled
    assert "No facility database could be reached" in grid["gap"]
    assert brief["address"]["utility"] is None
    assert brief["sections"]["your_bill"]["price"]["rate_now"] == 0.151  # Spark's figure
    assert "EIA's monthly price series could not be read" in brief["sections"]["your_bill"]["gap"]
    assert brief["source_mode"] == "full"


async def test_rejected_status_is_legal_and_not_counted(tmp_path) -> None:
    drafts = fakes.drafts()
    drafts["draft_coming"]["facilities"].append(
        {
            "name": "Project Blue",
            "codename": "Project Blue",
            "operator": "Beale Infrastructure",
            "operator_confidence": 0.8,
            "distance_km": 9.5,
            "status": "rejected",
            "estimated_mw": 290,
            "mw_basis": "filed",
            "shares_substation": None,
            "lat": None,
            "lon": None,
        }
    )
    svc = fakes.service(tmp_path, brief_source="full", draft_responses=drafts)
    svc.ground = ground()
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    statuses = {f["name"]: f["status"] for f in brief["sections"]["coming"]["facilities"]}
    assert statuses["Project Blue"] == "rejected"
    assert brief["headline"]["one_liner"].startswith("2 data centers within five miles")


UTILITY_PRICE = PriceSeries(
    state="VA",
    rate_now=0.13,
    rate_then=0.125,
    trend_pct=4.0,
    typical_kwh_month=1100.0,
    window_months=24,
    latest=(2024, 12),
    source_url="https://example.org/eia861",
    source_title="EIA-861",
    data_status="Final",
    scope="utility",
    as_of="2024-12",
    label="Virginia Electric & Power Co",
    eia_id="19876",
)
TARIFF = TariffEntry(
    state="VA",
    utility_match="VIRGINIA ELECTRIC",
    name="Rate Schedule GS-5",
    status="in_force",
    protects_households=True,
    docket="PUR-2025-00058",
    summary="Customers above 25 MW pay minimum demand charges under 14-year contracts.",
    url="https://example.org/scc/gs5",
    title="SCC order",
)


async def test_utility_price_and_tariff_table_win(tmp_path) -> None:
    up = FakeUtilityPrices(UTILITY_PRICE)
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(utility_prices=up, tariffs=FakeTariffs(TARIFF))
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    assert up.calls == [("19876", "VA")]  # joined on the EIA utility number from HIFLD
    bill = brief["sections"]["your_bill"]
    assert bill["price"]["rate_now"] == 0.13 and bill["price"]["as_of"] == "2024-12"
    assert bill["price"]["typical_household_kwh_month"] == 1100.0
    assert brief["headline"]["ai_rent_usd_per_month"] == 5.5
    urls = {c["source"]["url"] for c in brief["claims"] if c["section"] == "your_bill"}
    assert {"https://example.org/eia861", "https://example.org/eia861m"} <= urls
    prot = brief["sections"]["protection"]
    assert prot["tariff"] == {
        "large_load_tariff": "in_force",
        "name": "Rate Schedule GS-5",
        "protects_households": True,
        "docket": "PUR-2025-00058",
    }
    assert prot["summary"].startswith("Yes, in part. Customers above 25 MW")
    assert any(c["source"]["url"] == "https://example.org/scc/gs5" for c in brief["claims"])
    assert any(
        line.startswith("Bill shield: Rate Schedule GS-5 in force")
        for line in brief["card"]["lines"]
    )


async def test_delivery_only_or_unknown_utility_falls_back_to_state(tmp_path) -> None:
    up = FakeUtilityPrices(None)
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(utility_prices=up)
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    assert brief["sections"]["your_bill"]["price"]["rate_now"] == 0.16
    assert brief["sections"]["your_bill"]["price"]["as_of"] == "2026-08"


async def test_no_retail_polygon_falls_back_to_eia_county_list(tmp_path) -> None:
    """Prineville: HIFLD has only the Bonneville Power Administration polygon at
    the point. EIA-861's county list names the retail utilities instead."""
    directory = FakeUtilityPrices(
        None,
        customers={"14354": 552756, "3265": 38000},
        counties={"14354": {"CROOK", "DESCHUTES"}, "3265": {"CROOK"}},
        names={"14354": "PacifiCorp", "3265": "Central Electric Coop Inc"},
    )
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(
        utility=FakeUtility(
            features=[
                {
                    "name": "BONNEVILLE POWER ADMINISTRATION",
                    "type": "FEDERAL",
                    "customers": 11,
                    "id": "1738",
                }
            ]
        ),
        utility_prices=directory,
    )
    geo = fakes.GEO.__class__(
        **{
            **fakes.GEO.__dict__,
            "county": "Crook",
            "state": "OR",
            "display": "N Main St, Prineville, OR 97754",
        }
    )
    svc.geocoder = fakes.FakeGeocoder(geo)
    brief = await svc.brief_for_address("1207 N Main St, Prineville, OR")
    assert brief["address"]["utility"] == "Pacific Power (PacifiCorp)"
    assert directory.calls == [("14354", "OR")]


async def test_progress_streams_ground_then_sections_then_verdicts(tmp_path) -> None:
    """The page can show the facts within seconds: the first event is a partial
    brief with the engine's facilities, utility and bill number and every
    section pending; one event per drafted section; a count per verdict."""
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground()
    events: list[dict] = []
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA", events.append)

    stages = [e["stage"] for e in events]
    assert stages[0] == "ground"
    first = events[0]["brief"]
    assert first["partial"]["pending"] == list(SECTION_IDS)
    assert first["address"]["utility"] == "Dominion Energy Virginia"
    assert first["sections"]["on_your_grid"]["facilities"][0]["name"] == "Northgate Campus DC1-DC9"
    assert first["headline"]["ai_rent_usd_per_month"] is not None

    assert stages.count("drafting") == len(SECTION_IDS)
    last_draft = [e for e in events if e["stage"] == "drafting"][-1]["brief"]
    assert last_draft["partial"]["pending"] == []

    verifying = [e for e in events if e["stage"] == "verifying"]
    assert verifying[0]["verified"] == 0
    assert verifying[-1]["verified"] == verifying[-1]["claims"] == len(brief["claims"])
    assert "partial" not in brief
    validate_brief(brief)
