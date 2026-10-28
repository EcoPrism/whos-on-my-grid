"""The ground-truth providers' pure parts: clustering raw records into
facilities, choosing a utility among overlapping territories, turning the
EIA-861M rows into a 24-month price series. No network."""

from app.ground.facilities import RawSite, build_facilities, norm_operator, operator_from_name
from app.ground.prices import series_from_rows
from app.ground.utility import choose, display_name

HOME = (39.0163, -77.4588)


def site(provider, key, name, operator, lat, lon, status="live", building=True):
    url = (
        f"https://www.peeringdb.com/{key}"
        if provider == "peeringdb"
        else f"https://www.openstreetmap.org/{key}"
    )
    return RawSite(provider, key, name, operator, status, lat, lon, url, building)


def test_peeringdb_record_absorbs_osm_buildings_of_the_same_site() -> None:
    sites = [
        site(
            "peeringdb", "fac/1", "Equinix DC1-DC15 - Ashburn", "Equinix, Inc.", 39.0164, -77.4590
        ),
        site("osm", "way/10", "Equinix DC2", "Equinix", 39.0164, -77.4591),
        site("osm", "way/11", None, "Equinix", 39.0170, -77.4585),
        site("osm", "way/12", "Equinix DC18", "Equinix", 39.0255, -77.4543),  # 1 km away: separate
    ]
    out = build_facilities(sites, *HOME)
    assert [f.name for f in out] == ["Equinix DC1-DC15 - Ashburn", "Equinix DC18"]
    assert out[0].buildings == 2 and out[0].providers == ("osm", "peeringdb")
    assert out[0].operator == "Equinix, Inc." and out[0].source_url.endswith("fac/1")
    assert out[0].distance_km < 0.1


def test_different_operators_next_door_stay_separate() -> None:
    sites = [
        site(
            "peeringdb",
            "fac/5",
            "RagingWire VA1",
            "RagingWire Data Centers - NTT",
            39.0200,
            -77.4600,
        ),
        site("osm", "way/20", "Equinix DC10", "Equinix", 39.0208, -77.4600),  # ~90 m
    ]
    out = build_facilities(sites, *HOME)
    assert len(out) == 2


def test_unnamed_buildings_cluster_and_say_so() -> None:
    sites = [
        site("osm", "way/30", None, None, 39.0300, -77.4600),
        site("osm", "way/31", None, None, 39.0310, -77.4600),
        site("osm", "way/32", None, None, 39.0320, -77.4600),
    ]
    out = build_facilities(sites, *HOME)
    assert len(out) == 1
    assert out[0].name == "3 unnamed data-center buildings"
    assert not out[0].operator_known


def test_operator_from_name_and_aliases() -> None:
    assert operator_from_name("Vantage WA11") == "Vantage"
    assert operator_from_name("Facebook Altoona Data Center 1") == "Meta"
    assert operator_from_name("Something Else") is None
    assert norm_operator("Amazon Web Services") == norm_operator("AWS") == "amazon"
    assert norm_operator("Equinix, Inc.") == "equinix"
    sites = [
        site("osm", "way/40", "Facebook Altoona Data Center 1", "Meta", 41.6642, -93.5148),
        site("osm", "way/41", "Facebook Altoona Data Center 2", None, 41.6655, -93.5082),
    ]
    out = build_facilities(sites, 41.658, -93.489, radius_km=8.047)
    assert len(out) == 1 and out[0].operator == "Meta" and out[0].buildings == 2


def test_outside_the_ring_is_dropped_and_capped_by_distance() -> None:
    sites = [site("osm", "way/50", "Far", "X", 39.2, -77.4588)]  # ~20 km north
    assert build_facilities(sites, *HOME) == []


def test_choose_prefers_retail_with_most_customers() -> None:
    feats = [
        {"name": "CITY OF MILTON - (WA)", "type": "MUNICIPAL", "customers": -999999},
        {
            "name": "PUGET SOUND ENERGY INC",
            "type": "INVESTOR OWNED",
            "customers": 1181569,
            "holding_co": "MACQUARIE GROUP",
        },
        {"name": "WAPA-- WESTERN AREA POWER ADMINISTRATION", "type": "FEDERAL", "customers": 221},
    ]
    u = choose(feats, "WA")
    assert u is not None
    assert u.name == "Puget Sound Energy" and u.raw_name == "PUGET SOUND ENERGY INC"
    assert u.candidates == 2 and u.customers == 1181569 and u.holding == "MACQUARIE GROUP"
    assert choose([], "WA") is None


def test_display_name_fallback_title_cases() -> None:
    assert display_name("CITY OF BOZEMAN - (MT)") == "City of Bozeman"
    assert display_name("PUD NO 1 OF CHELAN COUNTY") == "PUD No 1 of Chelan County"
    assert display_name("PACIFICORP", "UT") == "Rocky Mountain Power (PacifiCorp)"
    assert display_name("PACIFICORP", "OR") == "Pacific Power (PacifiCorp)"


def _rows(start_year: int, months: int, price_cents_by_index) -> list:
    """Synthetic monthly rows newest first: revenue k$, sales MWh, customers."""
    rows = []
    y, m = start_year, 12
    for i in range(months):
        sales = 1_000_000.0  # MWh
        customers = 1_000_000.0  # -> 1,000 kWh per customer per month
        revenue = price_cents_by_index(i) / 100 * sales  # k$ : $/kWh * MWh == k$
        rows.append((y, m, revenue, sales, customers, "Final"))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return rows


def test_series_is_trailing_twelve_versus_twelve_ending_two_years_earlier() -> None:
    # newest 12 months at 15 c/kWh, then 12 at 13, then 12 at 12.
    rows = _rows(2026, 36, lambda i: 15.0 if i < 12 else 13.0 if i < 24 else 12.0)
    s = series_from_rows("VA", rows)
    assert s is not None
    assert s.rate_now == 0.15 and s.rate_then == 0.12
    assert s.trend_pct == 25.0 and s.typical_kwh_month == 1000.0
    assert s.latest == (2026, 12) and s.window_months == 24 and s.data_status == "Final"


def test_series_needs_both_windows() -> None:
    assert series_from_rows("VA", _rows(2026, 30, lambda i: 15.0)) is None
    assert series_from_rows("VA", []) is None


def test_utility_series_is_annual_and_per_customer() -> None:
    from app.ground.prices import utility_series_from_rows

    now = (50832.0, 845768.0, 42485.0, "PUD No 2 of Grant County")
    then = (51018.0, 917714.0, 41052.0, "PUD No 2 of Grant County")
    s = utility_series_from_rows("14624", "WA", now, then, 2024, 2022)
    assert s is not None and s.scope == "utility" and s.as_of == "2024-12"
    assert s.rate_now == 0.0601 and s.rate_then == 0.0556 and s.window_months == 24
    assert s.typical_kwh_month == 1659.0 and s.label == "PUD No 2 of Grant County"
    assert utility_series_from_rows("1", "WA", now, None, 2024, 2022) is None


def test_tariff_table_matches_by_state_and_utility() -> None:
    from app.ground.tariffs import TariffTable

    t = TariffTable()
    e = t.match("VA", "VIRGINIA ELECTRIC & POWER CO")
    assert e is not None and e.status == "in_force" and e.lead == "Yes, in part."
    assert t.match("VA", "RAPPAHANNOCK ELECTRIC COOP") is None
    assert t.match("MT", "NORTHWESTERN ENERGY") is None
    none = t.match("WA", "PUGET SOUND ENERGY INC")
    assert none is not None and none.status == "none_found" and none.lead == "No."
    for entry in t.entries():
        assert entry.url.startswith("https://") and entry.status in (
            "in_force",
            "proposed",
            "none_found",
        )


def test_choose_prefers_the_utility_named_for_the_city() -> None:
    feats = [
        {
            "name": "UTILITY BOARD OF THE CITY OF KEY WEST, F",
            "type": "MUNICIPAL",
            "customers": 30908,
            "id": "10226",
        },
        {
            "name": "FLORIDA POWER & LIGHT CO",
            "type": "INVESTOR OWNED",
            "customers": 5136952,
            "id": "6452",
        },
    ]
    hints = {"10226": (27460, True), "6452": (5337118, True)}  # both report Monroe County
    assert choose(feats, "FL", hints, city="Key West").raw_name.startswith("UTILITY BOARD")
    assert choose(feats, "FL", hints, city="Miami").raw_name == "FLORIDA POWER & LIGHT CO"
    # A county the small utility does not report drops it before the city rule applies.
    hints = {"10226": (27460, False), "6452": (5337118, True)}
    assert choose(feats, "FL", hints, city="Key West").raw_name == "FLORIDA POWER & LIGHT CO"
    # EIA's count beats HIFLD's missing one: Oncor over a co-op whose polygon covers Dallas.
    feats = [
        {
            "name": "ONCOR ELECTRIC DELIVERY COMPANY LLC",
            "type": "INVESTOR OWNED",
            "customers": -999999,
            "id": "44372",
        },
        {
            "name": "FARMERS ELECTRIC COOP, INC - (TX)",
            "type": "COOPERATIVE",
            "customers": 74641,
            "id": "6182",
        },
    ]
    assert choose(
        feats, "TX", {"44372": (3545814, True), "6182": (88221, True)}, city="Dallas"
    ).raw_name.startswith("ONCOR")


def test_same_operator_twice_gets_distinct_names() -> None:
    sites = [
        site("osm", "way/1", None, "Amazon Web Services", 39.0200, -77.4588),
        site("osm", "way/2", None, "Amazon Web Services", 39.0202, -77.4588),
        site("osm", "way/3", None, "Amazon Web Services", 39.0163, -77.4700),
        site("osm", "way/4", None, "Amazon Web Services", 39.0163, -77.4702),
    ]
    out = build_facilities(sites, *HOME)
    names = [f.name for f in out]
    assert len(names) == 2 and len(set(names)) == 2
    assert names[0].startswith("Amazon Web Services (2 buildings), ")
    assert {n.rsplit(", ", 1)[1] for n in names} == {"north", "west"}
