"""The home page's two measured lines: what PeeringDB lists today, and what a
data center is in house terms. The constants behind the equivalences live
in data/equivalences.json (and, outside the US, the region's
data/regions/<id>/constants.json), each with the page and the verbatim
sentence it comes from; the sentences here are the engine's arithmetic over
them, never a model's. One pulse per region, cached in-process for an hour;
nothing here costs tokens."""

import json
import time
from functools import lru_cache
from typing import Any

from app.config import REPO_ROOT
from app.ground import Ground
from app.scenario import constants as scenario_constants

EQUIVALENCES = REPO_ROOT / "data" / "equivalences.json"
CACHE_S = 3600


@lru_cache(maxsize=1)
def constants() -> dict[str, dict[str, Any]]:
    if not EQUIVALENCES.exists():
        return {}
    with open(EQUIVALENCES, encoding="utf-8") as f:
        return {row["id"]: row for row in json.load(f)["constants"]}


@lru_cache(maxsize=1)
def scale() -> list[dict[str, Any]]:
    """What a campus's MW means: the size tiers and the largest AI campuses
    announced, smallest first. Each row restates only its quote; the figures
    are reported (company plans as reported), not measured."""
    if not EQUIVALENCES.exists():
        return []
    with open(EQUIVALENCES, encoding="utf-8") as f:
        rows = json.load(f).get("scale", [])
    return sorted(rows, key=lambda r: r["mw"])


def _round_homes(n: float) -> str:
    if n >= 10_000:
        return f"{round(n / 1000) * 1000:,.0f}"
    return f"{round(n / 100) * 100:,.0f}"


def equivalences(
    region_id: str = "us",
    table: scenario_constants.Constants | None = None,
    label: str = "",
) -> list[dict[str, Any]]:
    """Each line names the figure it rests on and links the page that states it.
    The US reads data/equivalences.json; another region reads its own table
    (`table`, the region's merged constants), see `_regional`."""
    if region_id != "us":
        return _regional(region_id, table or {}, label)
    out: list[dict[str, Any]] = []
    c = constants()
    home = c.get("us_home_kwh_per_year")
    if home:
        kwh_year = float(home["value"])
        campus_mw = 100
        homes = campus_mw * 1000 * 8760 / kwh_year
        out.append(
            {
                "id": "homes_per_100mw",
                "text": (
                    f"A {campus_mw} MW campus running around the clock draws as much electricity "
                    f"in a year as about {_round_homes(homes)} average US homes."
                ),
                "basis": (
                    f"{campus_mw} MW × 8,760 hours ÷ {kwh_year:,.0f} kWh per home per year "
                    f"({home['as_of']})."
                ),
                "source_url": home["source_url"],
                "source_title": home["source_title"],
                "quote": home["quote"],
            }
        )
    field = c.get("football_field_sq_ft")
    if field:
        sq_ft = float(field["value"])
        roof = 1_000_000
        fields = roof / sq_ft
        acres = roof / 43_560
        out.append(
            {
                "id": "fields_per_million_sq_ft",
                "text": (
                    f"A one-million-square-foot data center roof covers about {acres:.0f} acres, "
                    f"the area of {fields:.0f} football fields including the end zones."
                ),
                "basis": f"{roof:,} sq ft ÷ {sq_ft:,.0f} sq ft per field; 43,560 sq ft per acre.",
                "source_url": field["source_url"],
                "source_title": field["source_title"],
                "quote": field["quote"],
            }
        )
    return out


def _regional(
    region_id: str, table: scenario_constants.Constants, label: str
) -> list[dict[str, Any]]:
    """Outside the US: the homes line from `{region}_home_kwh_per_year`, and the
    data-centre share of metered electricity from
    `{region}_dc_share_metered_electricity`, whose text is the constant's own
    curated claim (it restates only the quote). No football-field line: that
    comparison is American. A constant that is absent leaves its line out."""
    out: list[dict[str, Any]] = []
    home = table.get(f"{region_id}_home_kwh_per_year")
    if home is not None and home.value > 0:
        kwh_year = float(home.value)
        campus_mw = 100
        homes = campus_mw * 1000 * 8760 / kwh_year
        where = f"homes in {label}" if label else "homes"
        out.append(
            {
                "id": "homes_per_100mw",
                "text": (
                    f"A {campus_mw} MW campus running around the clock draws as much electricity "
                    f"in a year as about {_round_homes(homes)} {where} using {kwh_year:,.0f} kWh "
                    "a year each."
                ),
                "basis": (
                    f"{campus_mw} MW × 8,760 hours ÷ {kwh_year:,.0f} kWh per home per year"
                    + (f" ({home.as_of})." if home.as_of else ".")
                ),
                "source_url": home.source_url,
                "source_title": home.source_title,
                "quote": home.quote,
            }
        )
    share = table.get(f"{region_id}_dc_share_metered_electricity")
    if share is not None and share.claim:
        out.append(
            {
                "id": "dc_share_metered_electricity",
                "text": share.claim,
                "basis": (
                    f"{share.value * 100:.0f}% of total metered electricity consumption"
                    + (f" ({share.as_of})." if share.as_of else ".")
                ),
                "source_url": share.source_url,
                "source_title": share.source_title,
                "quote": share.quote,
            }
        )
    return out


# What the what-if slider needs to label its MW live, read from the same
# table the scenario engine reads (data/equivalences.json, then
# data/regions/us/constants.json), so the label and the scenario's own homes
# counter agree, and each value travels with its page and verbatim quote.
SLIDER_CONSTANTS = ("us_home_kwh_per_year", "dc_load_factor")


def cited_constants(
    table: scenario_constants.Constants | None = None,
) -> dict[str, dict[str, Any]]:
    """Each slider constant with its value and the page and sentence it comes
    from. One without a cited row is left out; the slider then shows no label.
    `table` is the region's; None reads the committed US table."""
    if table is None:
        table = scenario_constants.default()
    out: dict[str, dict[str, Any]] = {}
    for cid in SLIDER_CONSTANTS:
        c = table.get(cid)
        if c is None:
            continue
        out[cid] = {
            "value": c.value,
            "unit": c.unit,
            "as_of": c.as_of,
            "source_url": c.source_url,
            "source_title": c.source_title,
            "quote": c.quote,
        }
    return out


class Pulse:
    """One region's pulse. `countries` are the PeeringDB countries it counts
    (the region's own, not the wider set its briefs search); `scenarios` False
    leaves out the what-if slider's constants, since the what-if does not run
    there."""

    def __init__(
        self,
        ground: Ground | None,
        constants: scenario_constants.Constants | None = None,
        *,
        region_id: str = "us",
        label: str = "",
        countries: tuple[str, ...] = ("US",),
        scenarios: bool = True,
    ) -> None:
        self.ground = ground
        self.constants = constants
        self.region_id = region_id
        self.label = label
        self.countries = countries
        self.scenarios = scenarios
        self._value: dict[str, Any] | None = None
        self._at = 0.0

    async def get(self) -> dict[str, Any]:
        if self._value is not None and time.monotonic() - self._at < CACHE_S:
            return self._value
        peeringdb = None
        if self.ground is not None and self.ground.facilities is not None:
            peeringdb = await self.ground.facilities.summary(self.countries)
        self._value = {
            "peeringdb": peeringdb,
            "equivalences": equivalences(self.region_id, self.constants, self.label),
            "constants": cited_constants(self.constants) if self.scenarios else {},
            "scale": scale(),
        }
        self._at = time.monotonic()
        return self._value
