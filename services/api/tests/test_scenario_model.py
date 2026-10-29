"""The scenario's arithmetic over a fake constants table, the merged loader,
and the noise bands the brief shares."""

import json
from dataclasses import replace

import pytest

from app.ground.types import Utility
from app.scenario import model
from app.scenario.constants import load
from tests.scenario_fakes import UTILITY, constants, tariff


def test_power_and_homes() -> None:
    c = constants()
    gwh = model.annual_gwh(100, c)
    assert gwh is not None and gwh.value == pytest.approx(700.8)
    assert [k.id for k in gwh.constants] == ["dc_load_factor"]
    homes = model.homes_equivalent(700.8, c)
    assert homes is not None and homes.value == pytest.approx(64_943, abs=1)
    assert "10,791 kWh per home" in homes.basis
    share = model.share_of_utility_homes(64_943, UTILITY)
    assert share is not None and share.value == pytest.approx(0.3247, abs=1e-4)
    assert model.share_of_utility_homes(64_943, None) is None
    no_count = Utility("X", "X", "MUNICIPAL", None, None, "https://example.org/x")
    assert model.share_of_utility_homes(64_943, no_count) is None


def test_closed_loop_uses_less_water() -> None:
    c = constants()
    evap = model.water_gal_per_day(300, "evaporative", c)
    closed = model.water_gal_per_day(300, "closed_loop", c)
    assert evap is not None and closed is not None
    assert closed.value < evap.value  # type: ignore[operator]
    # 300 MW × 0.8 × 24 h × 1000 kWh/MWh × 1.8 L/kWh ÷ 3.785 L/gal
    assert evap.value == pytest.approx(300 * 0.8 * 24_000 * 1.8 / 3.785411784, abs=1)
    homes = model.water_homes_equivalent(float(evap.value), c)  # type: ignore[arg-type]
    assert homes is not None and homes.value == round(float(evap.value) / 300)  # type: ignore[arg-type]


def test_land_taxes_jobs_timeline() -> None:
    c = constants()
    acres = model.land_acres(300, c)
    assert acres is not None and acres.value == 150
    fields = model.football_fields(150, c)
    assert fields is not None and fields.value == pytest.approx(150 * 43_560 / 57_600, abs=0.1)
    taxes = model.taxes_usd_per_year(100, c)
    assert taxes is not None and taxes.value == (2_000_000.0, 6_000_000.0)
    jobs = model.jobs(300, c)
    assert jobs is not None and jobs.value == 150
    months = model.construction_months(c)
    assert months is not None and months.value == (18, 36)


def test_bill_outcome() -> None:
    c = constants()
    shielded = model.bill_outcome(tariff("in_force", True), UTILITY, 300, c)
    assert shielded.kind == "shielded" and shielded.range_usd_per_month is None
    assert shielded.confidence == 0.8

    exposed = model.bill_outcome(tariff("none_found", None), UTILITY, 300, c)
    assert exposed.kind == "exposed" and exposed.confidence == 0.3
    # mw × cost × allocation ÷ customers ÷ 12, at both ends of the allocation range
    lo = 300 * 100_000 * 0.3 / 200_000 / 12
    hi = 300 * 100_000 * 0.4 / 200_000 / 12
    assert exposed.range_usd_per_month == (pytest.approx(lo, abs=0.01), pytest.approx(hi, abs=0.01))
    assert {k.id for k in exposed.constants} == {
        "pjm_capacity_usd_per_mw_year", "residential_allocation_lo", "residential_allocation_hi",
    }  # fmt: skip

    assert model.bill_outcome(tariff("proposed", None), UTILITY, 300, c).kind == "exposed"
    assert model.bill_outcome(tariff("in_force", None), UTILITY, 300, c).kind == "partial"
    assert model.bill_outcome(None, UTILITY, 300, c).kind == "exposed"
    unknown = model.bill_outcome(tariff("none_found", None), None, 300, c)
    assert unknown.kind == "unknown" and unknown.range_usd_per_month is None

    # The capacity price is PJM's: outside PJM, or with no BA known, there is no range.
    for ba in ("MISO", None):
        other = model.bill_outcome(None, replace(UTILITY, ba_code=ba), 300, c)
        assert other.kind == "unknown" and other.range_usd_per_month is None
        assert "PJM" in other.basis and other.constants == ()
    assert (
        "in the MISO balancing area"
        in model.bill_outcome(None, replace(UTILITY, ba_code="MISO"), 300, c).basis
    )
    # A shield still reads as a shield anywhere.
    shield = model.bill_outcome(tariff("in_force", True), replace(UTILITY, ba_code="ERCO"), 300, c)
    assert shield.kind == "shielded"


def test_missing_constants_leave_lines_out() -> None:
    c = constants("dc_load_factor", "dc_acres_per_mw", "pjm_capacity_usd_per_mw_year")
    assert model.annual_gwh(100, c) is None
    assert model.water_gal_per_day(100, "evaporative", c) is None
    assert model.land_acres(100, c) is None
    assert model.bill_outcome(None, UTILITY, 100, c).kind == "unknown"
    assert model.homes_equivalent(700.8, {}) is None
    assert model.construction_months(constants("dc_construction_months_hi")) is None


def test_noise_bands_match_the_brief() -> None:
    near, mid, far = model.noise_at(0.5), model.noise_at(1.5), model.noise_at(5.0)
    assert near.basis.startswith("At that distance cooling fans") and near.confidence == 0.4
    assert "unlikely to carry" in mid.basis and mid.confidence == 0.4
    assert far.basis == "That is too far for its equipment to be heard from your house."
    assert far.confidence == 0.5 and far.value is None and far.constants == ()


def test_loader_merges_and_skips(tmp_path) -> None:
    first = tmp_path / "equivalences.json"
    second = tmp_path / "scenario_constants.json"
    row = {
        "id": "us_home_kwh_per_year",
        "value": 10791,
        "unit": "kWh",
        "as_of": "2022",
        "source_title": "EIA",
        "source_url": "https://www.eia.gov/x",
        "quote": "10,791 kilowatthours",
        "checked": "2026-10-28",
    }
    first.write_text(json.dumps({"constants": [row]}), encoding="utf-8")
    second.write_text(
        json.dumps(
            {
                "constants": [
                    {**row, "value": 11000},
                    {**row, "id": "no_quote", "quote": ""},
                    {**row, "id": "not_a_number", "value": "lots"},
                    {**row, "id": "dc_load_factor", "value": 0.8, "checked": None},
                ]
            }
        ),
        encoding="utf-8",
    )
    table = load((first, second, tmp_path / "absent.json"))
    assert set(table) == {"us_home_kwh_per_year", "dc_load_factor"}
    assert table["us_home_kwh_per_year"].value == 11000  # later file wins
    src = table["us_home_kwh_per_year"].source("2026-10-29T12:00:00Z")
    assert src == {
        "title": "EIA",
        "url": "https://www.eia.gov/x",
        "retrieved_at": "2026-10-28T00:00:00Z",
        "quote": "10,791 kilowatthours",
    }
    assert table["dc_load_factor"].source("2026-10-29T12:00:00Z")["retrieved_at"] == (
        "2026-10-29T12:00:00Z"
    )
    assert load((tmp_path / "absent.json",)) == {}


def test_fmt_and_pct_print_plainly() -> None:
    assert model.fmt(12345.6) == "12,345.6"
    assert model.fmt(121705.6) == "121,705.6"
    assert model.fmt(10791) == "10,791"
    assert model.fmt(1.32) == "1.32" and model.fmt(0.373) == "0.373"
    assert model.pct(0.0024) == "0.2%"
    assert model.pct(0.0004) == "under 0.1%"
    assert model.pct(0.3247) == "32%"


def test_shield_respects_the_size_floor() -> None:
    c = constants()
    ga = replace(tariff("in_force", True), min_mw=100, min_mw_inclusive=True)
    below = model.bill_outcome(ga, UTILITY, 50, c)
    assert below.kind != "shielded"
    assert "applies only to loads of 100 MW and more; a 50 MW campus is below that" in below.basis
    assert model.bill_outcome(ga, UTILITY, 100, c).kind == "shielded"
    assert model.bill_outcome(ga, UTILITY, 150, c).kind == "shielded"
    va = replace(tariff("in_force", True), min_mw=25, min_mw_inclusive=False)
    assert model.bill_outcome(va, UTILITY, 25, c).kind != "shielded"
    assert model.bill_outcome(va, UTILITY, 26, c).kind == "shielded"
    partly = replace(tariff("in_force", None), min_mw=75)
    assert model.bill_outcome(partly, UTILITY, 50, c).kind == "exposed"
    assert model.bill_outcome(partly, UTILITY, 300, c).kind == "partial"


def test_construction_is_the_shell_not_power() -> None:
    months = model.construction_months(constants())
    assert months is not None
    assert "to build the shell; connecting power can take longer" in months.basis
    assert "permit to power" not in months.basis
