"""Ireland's scripted ground truth for the tests: the Eurostat price series, the
ESB Networks utility, the CRU connection-policy row and the Google Grange
Castle decision, exactly as plan section 0.4-0.7 and 2.3 give them, plus a
FakeGround built from them. The two facilities are fictional (example.org).

Owned by stream B after phase 0; streams C and D import from here, never copy."""

from typing import Any

from app.geocode import GeocodeResult
from app.ground import (
    Decision,
    FakeFacilityDatabase,
    FakeHearingIndex,
    FakePrices,
    FakeTariffs,
    Ground,
    GroundFacility,
    PriceSeries,
    TariffEntry,
    Utility,
)

EUROSTAT_COMPACT_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_204"
    "?geo=IE&nrg_cons=KWH2500-4999&tax=I_TAX&currency=EUR&unit=KWH&time=2024-S1&time=2026-S1"
)
EUROSTAT_TITLE = (
    "Eurostat, Electricity prices for household consumers - bi-annual data (nrg_pc_204)"
)
EUROSTAT_CLAIM = (
    "Eurostat nrg_pc_204, Ireland, Consumption from 2 500 kWh to 4 999 kWh - band DC, All taxes "
    "and levies included: EUR 0.3871 per kWh in 2026-S1 and EUR 0.2590 per kWh in 2024-S1."
)
EUROSTAT_QUOTE = '"value":{"0":0.2590,"1":0.3871}'  # raw text of the compact response

CRU_KWH_URL = "https://www.cru.ie/publications/25651/"
CRU_KWH_TITLE = "CRU, Review of Typical Consumption Figures - Decision Paper"
CRU_KWH_QUOTE = (
    "This decision paper updates the recommended typical annual consumption figure for "
    "electricity to 4,200 kWh and the typical annual consumption for gas to 11,000 kWh."
)
CRU_KWH_CLAIM = (
    "The CRU's decision paper sets the recommended typical annual electricity consumption figure "
    "at 4,200 kWh."
)

# Plan 0.4: 2026-S1 against 2024-S1, all taxes, band DC; 4,200 kWh a year / 12 = 350.
PRICE_IE = PriceSeries(
    jurisdiction="IE",
    rate_now=0.3871,
    rate_then=0.2590,
    trend_pct=49.5,
    typical_kwh_month=350.0,
    window_months=24,
    latest=(2026, 6),
    source_url=EUROSTAT_COMPACT_URL,
    source_title=EUROSTAT_TITLE,
    data_status="Final",
    scope="country",
    as_of="2026-06",
    label="Ireland",
    latest_month_rate=None,
    currency="EUR",
    granularity="semiannual",
    claim_text=EUROSTAT_CLAIM,
    quote=EUROSTAT_QUOTE,
    period_now="2026-S1",
    period_then="2024-S1",
    kwh_claim_text=CRU_KWH_CLAIM,
    kwh_source_url=CRU_KWH_URL,
    kwh_source_title=CRU_KWH_TITLE,
    kwh_quote=CRU_KWH_QUOTE,
)

ESB_SOURCE_URL = (
    "https://www.esbnetworks.ie/about-us/company/publication-scheme/about-esb-networks-dac"
)
ESB_QUOTE = (
    "ESB Networks DAC, a ringfenced subsidiary within ESB Group, is the licensed Distribution "
    "System Operator (DSO) for Ireland."
)
ESB_CLAIM = "ESB Networks DAC is the licensed Distribution System Operator (DSO) for Ireland."

# Plan 0.5: the feature properties of data/regions/ie/utilities/ie.geojson.
UTILITY_IE = Utility(
    name="ESB Networks",
    raw_name="ESB Networks DAC",
    kind="DSO",
    customers=2_500_000,
    holding="ESB Group",
    source_url=ESB_SOURCE_URL,
    website="https://www.esbnetworks.ie",
    source_title="ESB Networks, About ESB Networks DAC",
    quote=ESB_QUOTE,
    claim_text=ESB_CLAIM,
)
ESB_FAILURE_NOTE = (
    "The ESB Networks map file could not be read; the serving network operator is not known."
)

CRU_POLICY_URL = (
    "https://www.cru.ie/about-us/news/"
    "the-cru-publishes-its-decision-on-new-electricity-connection-policy-for-data-centres/"
)

# Plan 0.6, the row of data/regions/ie/tariffs.json.
TARIFF_IE = TariffEntry(
    jurisdiction="IE",
    utility_match="*",
    name="CRU connection policy for new data centres (December 2025)",
    status="in_force",
    protects_households=False,
    docket=None,
    summary=(
        "The Commission for Regulation of Utilities' December 2025 decision requires new data "
        "centres connecting to the electricity network to provide generation and/or storage "
        "capacity, onsite or local in proximity, to match their requested maximum import demand "
        "capacity, with that generation participating in the wholesale electricity market, and "
        "to meet at least 80% of their annual demand with additional renewable electricity "
        "projects generating in the Republic of Ireland. Its stated objective is a pathway to "
        "connect that takes into account grid constraints, security of supply and generation "
        "adequacy, and national renewable energy targets."
    ),
    url=CRU_POLICY_URL,
    title=(
        "CRU, The CRU Publishes its Decision on New Electricity Connection Policy for Data "
        "Centres (12 December 2025)"
    ),
    min_mw=None,
    min_mw_inclusive=True,
    quote=(
        "New data centres connecting to the electricity network will continue to be required to "
        "provide generation and/or storage capacity, either onsite or local in proximity to "
        "match the requested data centre maximum import demand capacity."
    ),
    kind="connection_policy",
)

# Plan 2.3, the South Dublin body's decision (site: OSM relation 4546404, Profile Park).
DECISION_GOOGLE = Decision(
    project="Google Ireland Grange Castle expansion (SD24A/0164W)",
    codename=None,
    operator="Google Ireland Limited",
    status="approved",
    date="2026-09-23",
    body="South Dublin County Council",
    decided_by="An Coimisiún Pleanála",
    text=(
        "On 2026-09-23 An Coimisiún Pleanála decided appeal PL06S.320852 (South Dublin ref. "
        "SD24A/0164W), Google Ireland Limited's ten-year application to expand its operations "
        "with a data storage facility at Grange Castle Business Park South and Profile Park, "
        "with the decision Grant Permissions with Conditions."
    ),
    source_url="https://www.pleanala.ie/en-ie/case/320852",
    source_title="An Coimisiún Pleanála, case PL06S.320852",
    quote="Grant Permissions with Conditions",
    lat=53.3144,
    lon=-6.4443,
    estimated_mw=None,
)

# Fictional facilities near the Blanchardstown fixture point (53.393, -6.392).
FACILITIES_IE = [
    GroundFacility(
        name="Halvex Dublin 15 Campus",
        operator="Halvex Digital",
        operator_known=True,
        status="live",
        lat=53.398,
        lon=-6.380,
        distance_km=0.9,
        source_url="https://example.org/peeringdb/fac/9001",
        source_title="PeeringDB facility 9001",
        buildings=3,
        providers=("osm", "peeringdb"),
    ),
    GroundFacility(
        name="2 unnamed data-centre buildings",
        operator="Operator not recorded in OpenStreetMap",
        operator_known=False,
        status="under_construction",
        lat=53.410,
        lon=-6.400,
        distance_km=2.0,
        source_url="https://example.org/osm/way/9002",
        source_title="OpenStreetMap way 9002",
        buildings=2,
        providers=("osm",),
    ),
]


class FakeIeUtility:
    """The ESB Networks map as a provider: UTILITY_IE inside, None outside
    (`outside=True`), raises when `fail` (the unreadable-file case)."""

    name = "esb-networks-map"
    failure_note = ESB_FAILURE_NOTE

    def __init__(
        self, utility: Utility | None = UTILITY_IE, *, fail: bool = False, outside: bool = False
    ) -> None:
        self.utility = utility
        self.fail = fail
        self.outside = outside
        self.calls = 0

    async def locate(self, geo: GeocodeResult) -> Utility | None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake")
        return None if self.outside else self.utility


def _country(geo: GeocodeResult) -> str:
    return geo.country


def ie_ground(**over: Any) -> Ground:
    """Ireland's ground as get_ground_ie wires it, with the fakes above: prices
    and tariffs keyed by country, decisions matched by distance, no imagery."""
    kw: dict[str, Any] = {
        "facilities": FakeFacilityDatabase(list(FACILITIES_IE)),
        "utility": FakeIeUtility(),
        "prices": FakePrices(PRICE_IE),
        "utility_prices": None,
        "tariffs": FakeTariffs(TARIFF_IE),
        "imagery": None,
        "hearings": FakeHearingIndex(None, [DECISION_GOOGLE]),
        "jurisdiction": _country,
        "decisions_scope": "radius",
    }
    kw.update(over)
    return Ground(**kw)
