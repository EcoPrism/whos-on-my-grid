"""Large-load tariffs the engine knows about: data/regions/<id>/tariffs.json, a hand-curated
table of commission orders and statutes keyed by jurisdiction (in the US, the
state) and utility, each with
the official page. The verifier fetches that page like any other source, so a
stale entry shows up as contradicted or unverifiable rather than as fact."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import REPO_ROOT

TARIFFS_PATH = REPO_ROOT / "data" / "regions" / "us" / "tariffs.json"


@dataclass(frozen=True)
class TariffEntry:
    jurisdiction: str  # US: the two-letter state
    utility_match: str
    name: str | None
    status: str  # in_force | proposed | none_found
    protects_households: bool | None
    docket: str | None
    summary: str
    url: str
    title: str
    min_mw: float | None = None  # the rule's size floor; None: no floor in the table
    min_mw_inclusive: bool = True  # "100 MW and above" (True) or "above 25 MW" (False)

    def covers(self, mw: float) -> bool:
        """Whether a load of `mw` is above the rule's size floor."""
        if self.min_mw is None:
            return True
        return mw >= self.min_mw if self.min_mw_inclusive else mw > self.min_mw

    @property
    def floor_words(self) -> str:
        """The floor as the rule words it: "of 100 MW and more", "above 25 MW"."""
        if self.min_mw is None:
            return "it covers"
        if self.min_mw_inclusive:
            return f"of {self.min_mw:g} MW and more"
        return f"above {self.min_mw:g} MW"

    @property
    def lead(self) -> str:
        """The first word a resident wants: does it shield you?"""
        if self.status == "none_found":
            return "No."
        if self.status == "proposed":
            return "Not yet."
        if self.protects_households is True:
            return "Yes, in part."
        if self.protects_households is False:
            return "No."
        return "Partly."


class TariffTable:
    def __init__(self, path: Path = TARIFFS_PATH) -> None:
        self.path = path
        self._entries: list[TariffEntry] | None = None

    def entries(self) -> list[TariffEntry]:
        if self._entries is None:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            self._entries = [TariffEntry(**e) for e in raw.get("entries", [])]
        return self._entries

    def match(self, jurisdiction: str, utility_raw_name: str | None) -> TariffEntry | None:
        """An entry for this utility in this jurisdiction, or one for the whole
        jurisdiction (utility_match "*"). No utility known: those entries only."""
        for e in self.entries():
            if e.jurisdiction != jurisdiction.upper():
                continue
            if e.utility_match == "*":
                return e
            if utility_raw_name and re.search(e.utility_match, utility_raw_name, re.I):
                return e
        return None


class FakeTariffs:
    def __init__(self, entry: TariffEntry | None = None) -> None:
        self.entry = entry

    def match(self, jurisdiction: str, utility_raw_name: str | None) -> TariffEntry | None:
        return self.entry
