"""The Scenario JSON: valid against its schema with fakes, every line
modelled with its working and sources, every claim quoted, no facility the
ground truth does not list, and graceful when constants are missing."""

import re
from dataclasses import replace

from app.card.spec import CardSpec, spec_from_scenario
from app.ground.census import households
from app.ground.prices import EIA861_PAGE
from app.ground.types import GroundTruth
from app.scenario.assemble import assemble_scenario
from app.scenario.inputs import ScenarioInputs
from app.schema import scenario_errors
from tests.scenario_fakes import FACILITIES, ZIP_GEO, constants, tariff, truth

NOW = "2026-10-29T12:00:00Z"
SID = "0123456789abcdef"
# Fictional names the lines must never mention unless the ground truth lists them.
OTHER_NAMES = ["Waxpool North", "Project Kestrel", "Pinefield"]


def make(inputs=None, t=None, c=None, hh=None, **kw):
    inputs = inputs or ScenarioInputs.create(zip="20147", mw=300, cooling="evaporative")
    return assemble_scenario(
        inputs,
        ZIP_GEO,
        truth() if t is None else t,
        households("20147", 25_000, 2024) if hh is None else hh,
        constants() if c is None else c,
        scenario_id=SID,
        now_iso=NOW,
        **kw,
    )


def test_schema_valid_and_modelled() -> None:
    s = make(public_base_url="https://grid.example")
    assert scenario_errors(s) == []
    assert s["kind"] == "scenario" and s["disclosure"] == "Hypothetical. Modelled, not measured."
    assert s["interpretation"] is None
    assert 1 <= len(s["lines"]) <= 7
    for line in s["lines"]:
        assert line["status"] == "modelled"
        assert line["basis"]
    topics = [line["topic"] for line in s["lines"]]
    assert topics == ["grid", "bill", "water", "land", "noise", "taxes"]
    grid = s["lines"][0]
    assert "300 MW" in grid["text"] and "2 data centers are already listed" in grid["text"]
    assert "20147 has 25,000 households" in grid["text"]
    urls = {src["url"] for src in grid["sources"]}
    assert "https://example.org/constants/dc_load_factor" in urls
    assert "https://example.org/hifld" in urls  # the share line leans on the utility page
    bill = s["lines"][1]
    assert any(src["url"] == "https://example.org/tariff" for src in bill["sources"])
    assert s["impact"]["bill"]["kind"] == "exposed"
    assert s["baseline"]["facility_count"] == 2
    assert [f["name"] for f in s["baseline"]["facilities"]] == [f.name for f in FACILITIES]
    assert s["place"]["households"]["count"] == 25_000


def test_every_claim_quoted_and_unchecked() -> None:
    s = make()
    assert s["claims"]
    assert [c["id"] for c in s["claims"]] == [f"c{n}" for n in range(1, len(s["claims"]) + 1)]
    for c in s["claims"]:
        assert c["section"] == "scenario" and c["verdict"] == "unchecked"
        assert c["source"]["quote"].strip(), c
        assert c["drafted_by"] == "engine"
    # One claim per constant used, each saying only what its page shows.
    constant_claims = [c for c in s["claims"] if "/constants/" in c["source"]["url"]]
    assert len({c["source"]["url"] for c in constant_claims}) == len(constant_claims)
    load = next(c for c in constant_claims if c["source"]["url"].endswith("dc_load_factor"))
    # No curated claim: the quote itself, never the engine's value or unit.
    assert load["text"] == (
        'Fictional source for dc_load_factor states: "campuses run at 80 percent of capacity".'
    )
    c = constants()
    c["dc_load_factor"] = replace(c["dc_load_factor"], claim="Campuses run at 80 percent.")
    curated = make(c=c)
    assert any(cl["text"] == "Campuses run at 80 percent." for cl in curated["claims"])


def test_no_line_names_an_unlisted_facility() -> None:
    s = make()
    text = " ".join(line["text"] for line in s["lines"]) + " ".join(s["card"]["lines"])
    for name in OTHER_NAMES:
        assert name not in text
    empty = make(t=truth(facilities=[]))
    assert "No data center is listed within five miles" in empty["lines"][0]["text"]
    assert empty["baseline"]["facility_count"] == 0
    assert scenario_errors(empty) == []


def test_shielded_bill_and_card() -> None:
    s = make(t=truth(tariff=tariff("in_force", True)))
    assert s["impact"]["bill"] == {
        "kind": "shielded",
        "range_usd_per_month": None,
        "basis": s["impact"]["bill"]["basis"],
    }
    assert "Schedule LL-1 is in force" in s["lines"][1]["text"]
    assert "Bill shield: large-load tariff in force" in s["card"]["lines"]
    spec = spec_from_scenario(s, public_base_url="https://grid.example")
    assert spec.hypothetical and spec.big is None
    assert spec.disclosure.endswith(f"https://grid.example/what-if/{SID} · 2026-10-29")


def test_exposed_card_shows_the_range() -> None:
    s = make(verified=False)
    lo, hi = s["impact"]["bill"]["range_usd_per_month"]
    assert lo < hi
    spec = spec_from_scenario(s)
    assert spec.big is not None and spec.big.startswith("+$")
    assert not any(re.match(r"^[+−-]\$", line) for line in spec.lines)
    assert "sources not yet checked" in spec.disclosure
    assert len(s["card"]["lines"]) <= 4 and all(len(x) <= 80 for x in s["card"]["lines"])


def test_missing_constants_degrade() -> None:
    s = make(c={}, t=GroundTruth(), hh=None)
    assert scenario_errors(s) == []
    impact = s["impact"]
    assert impact["power"] is None and impact["water"] is None and impact["land"] is None
    assert impact["taxes"] is None and impact["jobs"] is None and impact["timeline"] is None
    assert impact["bill"]["kind"] == "unknown"
    assert [line["topic"] for line in s["lines"]] == ["bill", "noise"]
    assert s["baseline"]["utility"] is None and s["baseline"]["facility_count"] is None
    assert all("/constants/" not in c["source"]["url"] for c in s["claims"])

    partial = make(c=constants("water_closed_loop_l_per_kwh"),
                   inputs=ScenarioInputs.create(zip="20147", mw=50, cooling="closed_loop"))  # fmt: skip
    assert partial["impact"]["water"] is None and partial["impact"]["power"] is not None
    assert "water" not in [line["topic"] for line in partial["lines"]]
    assert scenario_errors(partial) == []


def test_pin_sets_the_noise_distance() -> None:
    pinned = ScenarioInputs.create(zip="20147", mw=100, cooling="closed_loop", pin=(39.07, -77.49))
    s = make(inputs=pinned)
    assert s["inputs"]["pin"] == {"lat": 39.07, "lon": -77.49}
    assert s["impact"]["noise"]["distance_km"] > 2.5
    noise = next(line for line in s["lines"] if line["topic"] == "noise")
    assert noise["text"].startswith("Dropped at the pin, the campus would sit 1.8 miles")
    assert "heard from the centre of the ZIP" in noise["text"]
    # The facility ring is around the ZIP centre, and a pinned campus says so.
    assert "within five miles of the centre of ZIP 20147" in s["lines"][0]["text"]
    ring = [x for x in s["card"]["lines"] if "within 5 miles" in x]  # the card keeps four
    assert all(x.endswith("within 5 miles of the ZIP centre") for x in ring)
    centre = make()
    assert centre["impact"]["noise"]["distance_km"] == 0
    assert centre["inputs"]["pin"] is None
    unpinned = next(line for line in centre["lines"] if line["topic"] == "noise")
    assert unpinned["text"].startswith(
        "With no pin set, the campus sits at the centre of ZIP 20147, 0.0 miles from it."
    )
    assert "among its homes" not in unpinned["text"]
    assert "already listed within five miles." in centre["lines"][0]["text"]


def test_committed_constants_table() -> None:
    """The curated files load whole, and every cooling and size assembles valid."""
    from app.scenario import constants as constants_mod

    table = constants_mod.load()
    for cid in ("dc_load_factor", "us_home_kwh_per_year", "football_field_sq_ft",
                "water_evaporative_l_per_kwh", "water_closed_loop_l_per_kwh"):  # fmt: skip
        assert cid in table, cid
    for c in table.values():
        assert c.quote and c.source_url.startswith("https://")
    for cooling in ("evaporative", "closed_loop"):
        for mw in (10, 100, 2000):
            s = make(c=table, inputs=ScenarioInputs.create(zip="20147", mw=mw, cooling=cooling))
            assert scenario_errors(s) == []
            assert all(line["status"] == "modelled" for line in s["lines"])


def test_closed_loop_zero_and_oversized_campus() -> None:
    """A zero-water design reads as none, not "about 0 gallons"; a campus bigger
    than the utility's customer base is not a percentage over 100."""
    c = constants()
    c["water_closed_loop_l_per_kwh"] = replace(c["water_closed_loop_l_per_kwh"], value=0.0)
    s = make(c=c, inputs=ScenarioInputs.create(zip="20147", mw=2000, cooling="closed_loop"))
    assert scenario_errors(s) == []
    water = next(line for line in s["lines"] if line["topic"] == "water")
    assert "no water for cooling" in water["text"] and "0 gallons" not in water["text"]
    assert "No water for cooling (closed loop)" in s["card"]["lines"]
    grid = s["lines"][0]["text"]
    assert s["impact"]["power"]["share_of_utility_homes"] > 1
    assert "more than all 200,000 of" in grid and "%" not in grid


def test_constant_claims_state_only_what_the_quote_shows() -> None:
    """Every number in a committed constant's claim is printed in its quote: no
    derived value (×365, ÷300 MW, a share of a total) is put on the page."""
    from app.scenario import constants as constants_mod

    table = constants_mod.load()
    number = re.compile(r"\d[\d,.]*\d|\d")
    for c in table.values():
        if not c.claim:
            continue
        for n in number.findall(c.claim):
            assert n in c.quote, (c.id, n)
    s = make(c=table, inputs=ScenarioInputs.create(zip="20147", mw=100, cooling="evaporative"))
    for cl in s["claims"]:
        if cl["source"]["url"].startswith("https://example.org"):
            continue  # the fake ground truth's facility and utility claims
        if cl["source"]["title"].startswith("EIA-861"):
            continue  # the engine's own count from the EIA-861 sheet
        for n in number.findall(cl["text"]):
            assert n in cl["source"]["quote"], (cl["text"], n)


def test_zip_stays_off_the_card() -> None:
    pinned = ScenarioInputs.create(zip="20147", mw=100, cooling="closed_loop", pin=(39.07, -77.49))
    for inputs in (None, pinned):
        s = make(inputs=inputs)
        card = s["card"]
        assert card["title"].endswith("came to Loudoun County, VA")
        assert "20147" not in card["title"]
        assert not any("20147" in x for x in card["lines"])
        spec = spec_from_scenario(s, public_base_url="https://grid.example")
        assert isinstance(spec, CardSpec)
        assert "20147" not in str(spec.as_json())


def test_customer_count_cites_eia_861() -> None:
    s = make()
    grid, bill = s["lines"][0], s["lines"][1]
    assert s["impact"]["bill"]["range_usd_per_month"] is not None
    assert EIA861_PAGE in {src["url"] for src in grid["sources"]}
    assert EIA861_PAGE in {src["url"] for src in bill["sources"]}
    assert s["baseline"]["utility"]["customers_source"]["url"] == EIA861_PAGE
    eia = [c for c in s["claims"] if c["source"]["url"] == EIA861_PAGE]
    assert len(eia) == 1
    assert "200,000 residential customers and balancing authority PJM" in eia[0]["text"]
    assert scenario_errors(s) == []


def test_small_campus_share_is_never_zero_percent() -> None:
    s = make(inputs=ScenarioInputs.create(zip="20147", mw=10, cooling="evaporative"),
             t=truth(utility=replace(truth().utility, customers=2_662_831)))  # fmt: skip
    grid = s["lines"][0]
    assert " 0% " not in grid["text"] and "= 0%" not in grid["basis"]
    assert re.search(r"or 0\.\d% of Northgate Power's customers", grid["text"])


def test_shield_needs_the_campus_above_the_floor() -> None:
    floor = replace(tariff("in_force", True), min_mw=100, min_mw_inclusive=True)
    small = make(inputs=ScenarioInputs.create(zip="20147", mw=50, cooling="evaporative"),
                 t=truth(tariff=floor))  # fmt: skip
    assert small["impact"]["bill"]["kind"] != "shielded"
    assert "applies only to loads of 100 MW and more" in small["impact"]["bill"]["basis"]
    assert "Bill shield: large-load tariff in force" not in small["card"]["lines"]
    big = make(inputs=ScenarioInputs.create(zip="20147", mw=150, cooling="evaporative"),
               t=truth(tariff=floor))  # fmt: skip
    assert big["impact"]["bill"]["kind"] == "shielded"
    assert "for loads of 100 MW and more" in big["lines"][1]["text"]
    assert scenario_errors(small) == [] and scenario_errors(big) == []
