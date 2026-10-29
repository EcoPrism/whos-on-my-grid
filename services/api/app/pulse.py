"""The home page's two measured lines: what PeeringDB lists today, and what a
data center is in house terms. The constants behind the equivalences live
in data/equivalences.json, each with the page and the verbatim sentence it
comes from; the sentences here are the engine's arithmetic over them, never
a model's. Cached in-process for an hour; nothing here costs tokens."""

import json
import time
from functools import lru_cache
from typing import Any

from app.config import REPO_ROOT
from app.ground import Ground

EQUIVALENCES = REPO_ROOT / "data" / "equivalences.json"
CACHE_S = 3600


@lru_cache(maxsize=1)
def constants() -> dict[str, dict[str, Any]]:
    if not EQUIVALENCES.exists():
        return {}
    with open(EQUIVALENCES, encoding="utf-8") as f:
        return {row["id"]: row for row in json.load(f)["constants"]}


def _round_homes(n: float) -> str:
    if n >= 10_000:
        return f"{round(n / 1000) * 1000:,.0f}"
    return f"{round(n / 100) * 100:,.0f}"


def equivalences() -> list[dict[str, Any]]:
    """Each line names the figure it rests on and links the page that states it."""
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


class Pulse:
    def __init__(self, ground: Ground | None) -> None:
        self.ground = ground
        self._value: dict[str, Any] | None = None
        self._at = 0.0

    async def get(self) -> dict[str, Any]:
        if self._value is not None and time.monotonic() - self._at < CACHE_S:
            return self._value
        peeringdb = None
        if self.ground is not None and self.ground.facilities is not None:
            peeringdb = await self.ground.facilities.summary()
        self._value = {"peeringdb": peeringdb, "equivalences": equivalences()}
        self._at = time.monotonic()
        return self._value
