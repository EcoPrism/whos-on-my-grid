"""The scenario's arithmetic: one pure function per strip line, each returning
the number, the sentence that shows the working, and the cited constants it
rests on. No model, no I/O. A function whose constant has no cited page
returns None, and that line is left out rather than guessed.

Unit conversions (hours in a year, litres in a US gallon, square feet in an
acre) are definitions, not citations."""

from dataclasses import dataclass
from typing import Literal

from app.ground.tariffs import TariffEntry
from app.ground.types import Utility
from app.scenario.constants import Constant, Constants
from app.scenario.inputs import Cooling

PJM = "PJM"  # EIA-861 BA Code of the one RTO whose capacity price is in the constants

KM_TO_MI = 0.621371
HOURS_PER_YEAR = 8_760
LITRES_PER_GALLON = 3.785411784
SQ_FT_PER_ACRE = 43_560
TAX_SPREAD = 0.5  # taxes are the least certain line: shown as ±50 %

WATER_IDS: dict[str, str] = {
    "evaporative": "water_evaporative_l_per_kwh",
    "closed_loop": "water_closed_loop_l_per_kwh",
}


@dataclass(frozen=True)
class Result:
    value: float | tuple[float, float] | None
    basis: str  # "100 MW × 0.8 × 8,760 h ÷ 10,791 kWh per home (2022)"
    constants: tuple[Constant, ...]
    confidence: float


@dataclass(frozen=True)
class BillOutcome:
    kind: Literal["shielded", "partial", "exposed", "unknown"]  # from TariffEntry.lead
    range_usd_per_month: tuple[float, float] | None
    basis: str
    confidence: float  # 0.3 when exposed; the tariff page's confidence when shielded
    constants: tuple[Constant, ...] = ()


def fmt(v: float) -> str:
    """A constant as the page would print it: 10,791 or 0.8 or 1.32 or 121,705.6.
    Fixed point from 1 up, so a large value never prints as 1.217e+05."""
    if float(v).is_integer():
        return f"{int(v):,}"
    if abs(v) >= 1:
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return f"{v:.3g}"


def pct(v: float) -> str:
    """A share as a percentage: whole points from 1%, one decimal below that,
    and "under 0.1%" for a share too small to print, so nothing reads as 0%."""
    p = v * 100
    if 0 < p < 0.1:
        return "under 0.1%"
    return f"{p:.1f}%" if p < 1 else f"{p:.0f}%"


def annual_gwh(mw: int, c: Constants) -> Result | None:
    lf = c.get("dc_load_factor")
    if lf is None:
        return None
    gwh = mw * lf.value * HOURS_PER_YEAR / 1000
    return Result(
        round(gwh, 1),
        f"{mw:,} MW × {fmt(lf.value)} load factor × 8,760 hours = {gwh:,.0f} GWh a year",
        (lf,),
        0.5,
    )


def homes_equivalent(gwh: float, c: Constants) -> Result | None:
    home = c.get("us_home_kwh_per_year")
    if home is None or home.value <= 0:
        return None
    homes = gwh * 1_000_000 / home.value
    return Result(
        round(homes),
        f"{gwh:,.0f} GWh ÷ {fmt(home.value)} kWh per home per year ({home.as_of}) "
        f"≈ {homes:,.0f} homes",
        (home,),
        0.5,
    )


def share_of_utility_homes(homes: float, utility: Utility | None) -> Result | None:
    if utility is None or not utility.customers:
        return None
    share = homes / utility.customers
    return Result(
        round(share, 4),
        f"{homes:,.0f} homes ÷ {utility.customers:,} {utility.name} customers = {pct(share)}",
        (),
        0.4,
    )


def water_gal_per_day(mw: int, cooling: Cooling, c: Constants) -> Result | None:
    lf = c.get("dc_load_factor")
    lpk = c.get(WATER_IDS[cooling])
    if lf is None or lpk is None:
        return None
    gal = mw * 1000 * lf.value * 24 * lpk.value / LITRES_PER_GALLON
    kind = "evaporative" if cooling == "evaporative" else "closed-loop"
    return Result(
        round(gal),
        f"{mw:,} MW × {fmt(lf.value)} load factor × 24 hours × {fmt(lpk.value)} litres per kWh "
        f"({kind} cooling) ÷ 3.785 litres per gallon ≈ {gal:,.0f} gallons a day",
        (lf, lpk),
        0.35,
    )


def water_homes_equivalent(gal_per_day: float, c: Constants) -> Result | None:
    home = c.get("us_home_water_gal_per_day")
    if home is None or home.value <= 0:
        return None
    homes = gal_per_day / home.value
    return Result(
        round(homes),
        f"{gal_per_day:,.0f} gallons a day ÷ {fmt(home.value)} gallons per home per day "
        f"≈ {homes:,.0f} homes",
        (home,),
        0.35,
    )


def land_acres(mw: int, c: Constants) -> Result | None:
    per = c.get("dc_acres_per_mw")
    if per is None:
        return None
    acres = mw * per.value
    return Result(
        round(acres, 1),
        f"{mw:,} MW × {fmt(per.value)} acres per MW ≈ {acres:,.0f} acres",
        (per,),
        0.3,
    )


def football_fields(acres: float, c: Constants) -> Result | None:
    field = c.get("football_field_sq_ft")
    if field is None or field.value <= 0:
        return None
    fields = acres * SQ_FT_PER_ACRE / field.value
    return Result(
        round(fields, 1),
        f"{acres:,.0f} acres × 43,560 sq ft ÷ {fmt(field.value)} sq ft per field "
        f"≈ {fields:,.0f} football fields",
        (field,),
        0.3,
    )


def bill_outcome(
    tariff: TariffEntry | None, utility: Utility | None, mw: int, c: Constants
) -> BillOutcome:
    """Shielded when the tariff table says a rule in force keeps large-load costs
    off households and the campus is above the rule's size floor. Otherwise, only for a utility whose EIA-861 balancing
    authority is PJM: PJM's capacity price for a campus this size, times the
    residential share at both ends of the cited range, spread over the
    utility's customers. The capacity price is PJM's alone, so anywhere else
    there is no range."""
    covered = tariff is not None and tariff.covers(mw)
    lead = tariff.lead if tariff is not None and covered else None
    # A rule with a size floor the campus is under does not apply to it.
    below = (
        f"{tariff.name or 'The large-load rule'} applies only to loads {tariff.floor_words}; "
        f"a {mw:,} MW campus is below that. "
        if tariff is not None and not covered
        else ""
    )
    if lead == "Yes, in part.":
        assert tariff is not None
        return BillOutcome(
            "shielded",
            None,
            f"{tariff.name or 'A large-load tariff'} is in force for this utility for loads "
            f"{tariff.floor_words}; its stated purpose is to keep the cost of serving them off "
            "other customers.",
            0.8,
        )
    kind: Literal["partial", "exposed"] = "partial" if lead == "Partly." else "exposed"
    cost = c.get("pjm_capacity_usd_per_mw_year")
    lo, hi = c.get("residential_allocation_lo"), c.get("residential_allocation_hi")
    customers = utility.customers if utility is not None else None
    if not customers:
        return BillOutcome(
            "unknown", None, below + "The utility's customer count is not known, so no range.", 0.2
        )
    ba = utility.ba_code if utility is not None else None
    if ba != PJM:
        where = f"is in the {ba} balancing area" if ba else "is not known to be in PJM"
        return BillOutcome(
            "unknown",
            None,
            below + f"The only capacity price the engine has is PJM's, and this utility {where}, "
            "so no range.",
            0.2,
        )
    if cost is None or lo is None or hi is None:
        return BillOutcome(
            "unknown",
            None,
            below + "The capacity-price figures have no cited page yet, so no range.",
            0.2,
        )

    def monthly(alloc: float) -> float:
        return round(mw * cost.value * alloc / customers / 12, 2)

    a, b = sorted((monthly(lo.value), monthly(hi.value)))
    why = (
        "No large-load tariff for this utility is in the engine's table. "
        if tariff is None
        else below
        or f"{tariff.name or 'The large-load rule'} ({tariff.status.replace('_', ' ')}) "
        "does not say it keeps these costs off households. "
    )
    return BillOutcome(
        kind,
        (a, b),
        why + f"{mw:,} MW × ${fmt(cost.value)} PJM capacity price per MW-year × "
        f"{pct(lo.value)} to "
        f"{pct(hi.value)} residential share ÷ {customers:,} customers ÷ 12 months "
        f"= ${a:,.2f} to ${b:,.2f} a month",
        0.3,
        (cost, lo, hi),
    )


def taxes_usd_per_year(mw: int, c: Constants) -> Result | None:
    per = c.get("dc_tax_usd_per_mw_year")
    if per is None:
        return None
    mid = mw * per.value
    lo, hi = round(mid * (1 - TAX_SPREAD)), round(mid * (1 + TAX_SPREAD))
    return Result(
        (float(lo), float(hi)),
        f"{mw:,} MW × ${fmt(per.value)} local tax per MW-year ≈ ${mid:,.0f}, "
        f"shown as ${lo:,.0f} to ${hi:,.0f} because rates differ by county",
        (per,),
        0.2,
    )


def jobs(mw: int, c: Constants) -> Result | None:
    per = c.get("dc_permanent_jobs_per_100mw")
    if per is None:
        return None
    n = mw / 100 * per.value
    return Result(
        round(n),
        f"{mw:,} MW ÷ 100 × {fmt(per.value)} permanent jobs per 100 MW ≈ {n:,.0f} jobs",
        (per,),
        0.25,
    )


def construction_months(c: Constants) -> Result | None:
    lo, hi = c.get("dc_construction_months_lo"), c.get("dc_construction_months_hi")
    if lo is None or hi is None:
        return None
    a, b = sorted((lo.value, hi.value))
    return Result(
        (a, b),
        f"{fmt(a)} to {fmt(b)} months to build the shell; connecting power can take longer",
        (lo, hi),
        0.3,
    )


def noise_at(distance_km: float, where: str = "your house") -> Result:
    """Whether a campus this far away can be heard. Bands, not decibels: no
    sound measurement is public. The brief's noise line uses the same bands."""
    miles = distance_km * KM_TO_MI
    if miles < 0.5:
        return Result(
            None,
            "At that distance cooling fans and backup-generator tests can be heard outdoors, "
            "especially at night. No sound measurement is public.",
            (),
            0.4,
        )
    if miles < 1.5:
        return Result(
            None,
            "At that distance its equipment is unlikely to carry over ordinary neighborhood "
            "sound. No sound measurement is public.",
            (),
            0.4,
        )
    return Result(None, f"That is too far for its equipment to be heard from {where}.", (), 0.5)
