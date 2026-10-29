"""Ireland's ground layer (plan 6.B): get_ground_ie's wiring, prices and tariffs
keyed by country, decisions matched by distance across authorities, and the US
gather_ground unchanged. No network."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings
from app.ground import (
    IE_DATA_DIR,
    FakeHearingIndex,
    FakePrices,
    FakeTariffs,
    Ground,
    HearingIndex,
    TariffTable,
    gather_ground,
    get_ground_ie,
)
from app.ground import facilities as fac
from app.ground.eurostat import EurostatPrices
from app.ground.facilities import FacilityDatabase, OverpassSource, PeeringDBSource
from app.ground.geojson_utility import GeoJsonUtility
from tests.fakes import GEO, GEO_IE
from tests.fakes_ie import (
    DECISION_GOOGLE,
    PRICE_IE,
    TARIFF_IE,
    UTILITY_IE,
    FakeIeUtility,
    ie_ground,
)

HAS_IE_DATA = (IE_DATA_DIR / "tariffs.json").exists()


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, ground_dir=str(tmp_path))  # type: ignore[call-arg]


# --- wiring ---------------------------------------------------------------------------


def test_get_ground_ie_wiring(tmp_path: Path) -> None:
    g = get_ground_ie(_settings(tmp_path))
    assert isinstance(g.facilities, FacilityDatabase)
    pdb, osm = g.facilities.sources
    assert isinstance(pdb, PeeringDBSource) and isinstance(osm, OverpassSource)
    assert pdb.countries == ("IE", "GB")
    assert pdb.path == tmp_path / "peeringdb_fac_ie_gb.json"
    assert isinstance(g.utility, GeoJsonUtility)
    assert g.utility.path == IE_DATA_DIR / "utilities" / "ie.geojson"
    assert isinstance(g.prices, EurostatPrices)
    assert g.prices.country == "IE" and g.prices.label == "Ireland"
    assert g.prices.path == tmp_path / "eurostat_nrg_pc_204_ie.json"
    assert g.utility_prices is None
    assert isinstance(g.tariffs, TariffTable)
    assert g.tariffs.path == IE_DATA_DIR / "tariffs.json"
    assert g.imagery is None
    assert isinstance(g.hearings, HearingIndex) and g.hearings.dir == IE_DATA_DIR / "hearings"
    assert g.decisions_scope == "radius"
    assert g.jurisdiction(GEO_IE) == "IE"


@pytest.mark.skipif(not HAS_IE_DATA, reason="data/regions/ie not written yet")
def test_get_ground_ie_reads_the_committed_files(tmp_path: Path) -> None:
    g = get_ground_ie(_settings(tmp_path))
    assert isinstance(g.prices, EurostatPrices)
    assert g.prices.typical_kwh_month == 350.0
    assert g.prices.kwh_source is not None
    assert g.prices.kwh_source.source_url == "https://www.cru.ie/publications/25651/"
    assert 4256 in g.facilities.sources[0].name_fixes  # type: ignore[union-attr]
    t = g.tariffs.match("IE", None)  # type: ignore[union-attr]
    assert t == TARIFF_IE
    assert g.tariffs.match("VA", None) is None  # type: ignore[union-attr]
    decisions = g.hearings.all_decisions()  # type: ignore[union-attr]
    assert DECISION_GOOGLE in decisions
    # Fingal itself has no decision; the radius scope still finds South Dublin's.
    assert g.hearings.decisions_for("IE-D", "Fingal") == []  # type: ignore[union-attr]


def test_missing_kwh_constant_gives_none(tmp_path: Path) -> None:
    data = tmp_path / "ie"
    data.mkdir()
    (data / "constants.json").write_text(json.dumps({"constants": []}), encoding="utf-8")
    g = get_ground_ie(_settings(tmp_path / "cache"), data)
    assert isinstance(g.prices, EurostatPrices)
    assert g.prices.typical_kwh_month is None and g.prices.kwh_source is None
    assert g.facilities.sources[0].name_fixes == frozenset()  # type: ignore[union-attr]


def test_importing_app_ground_does_not_load_the_ie_modules() -> None:
    import subprocess
    import sys

    code = (
        "import sys, app.ground, app.regions; "
        "print(any(m in sys.modules for m in "
        "('app.ground.eurostat', 'app.ground.geojson_utility')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT / "services" / "api",
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "False"


# --- gather_ground with Ireland's keys ---------------------------------------------------


class _Recording:
    def __init__(self, inner: object) -> None:
        self.inner = inner
        self.keys: list[str] = []

    def match(self, jurisdiction: str, utility_raw_name: str | None):  # tariffs
        self.keys.append(jurisdiction)
        return self.inner.match(jurisdiction, utility_raw_name)  # type: ignore[attr-defined]

    async def series(self, jurisdiction: str):  # prices
        self.keys.append(jurisdiction)
        return await self.inner.series(jurisdiction)  # type: ignore[attr-defined]


async def test_tariff_and_prices_are_keyed_by_country() -> None:
    tariffs = _Recording(FakeTariffs(TARIFF_IE))
    prices = _Recording(FakePrices(PRICE_IE))
    truth = await gather_ground(GEO_IE, ie_ground(tariffs=tariffs, prices=prices))
    assert tariffs.keys == ["IE"] and prices.keys == ["IE"]
    assert truth.tariff == TARIFF_IE and truth.price == PRICE_IE
    assert truth.utility == UTILITY_IE
    assert truth.notes == []


@pytest.mark.skipif(not HAS_IE_DATA, reason="data/regions/ie not written yet")
async def test_real_tariff_table_matches_on_ie() -> None:
    truth = await gather_ground(
        GEO_IE, ie_ground(tariffs=TariffTable(IE_DATA_DIR / "tariffs.json"))
    )
    assert truth.tariff == TARIFF_IE


async def test_fingal_gets_south_dublin_decision_by_radius(tmp_path: Path) -> None:
    """Blanchardstown is in Fingal; the Google decision is South Dublin's. The
    authority scope would hide it, the radius scope hands it to assemble."""
    sdcc = {
        "id": "sdcc",
        "name": "South Dublin County Council",
        "state": "IE-D",
        "counties": ["South Dublin"],
        "meetings": [],
        "decisions": [
            {
                "project": DECISION_GOOGLE.project,
                "codename": None,
                "operator": DECISION_GOOGLE.operator,
                "status": DECISION_GOOGLE.status,
                "date": DECISION_GOOGLE.date,
                "text": DECISION_GOOGLE.text,
                "source_url": DECISION_GOOGLE.source_url,
                "source_title": DECISION_GOOGLE.source_title,
                "quote": DECISION_GOOGLE.quote,
                "lat": DECISION_GOOGLE.lat,
                "lon": DECISION_GOOGLE.lon,
                "estimated_mw": None,
                "decided_by": DECISION_GOOGLE.decided_by,
            }
        ],
        "upcoming": [],
    }
    fingal = {**sdcc, "id": "fingal", "name": "Fingal County Council", "counties": ["Fingal"]}
    fingal["decisions"] = []
    (tmp_path / "sources.json").write_text(json.dumps({"bodies": [sdcc, fingal]}), encoding="utf-8")
    index = HearingIndex(tmp_path)
    radius = await gather_ground(GEO_IE, ie_ground(hearings=index))
    assert radius.decisions == [DECISION_GOOGLE]
    assert radius.hearing is None
    assert radius.hearing_note == (
        "Fingal County Council is in the index but no meeting has been transcribed yet."
    )
    authority = await gather_ground(GEO_IE, ie_ground(hearings=index, decisions_scope="authority"))
    assert authority.decisions == []


async def test_radius_scope_drops_decisions_far_from_the_address() -> None:
    """Cork is about 220 km from Grange Castle: the prompt must not be told the
    Dublin grant is on this address's record when Coming leaves it out."""
    cork = replace(GEO_IE, lat=51.8985, lon=-8.4756, county="Cork City", matched="x")
    far = await gather_ground(cork, ie_ground())
    assert far.decisions == []
    near = await gather_ground(GEO_IE, ie_ground())
    assert near.decisions == [DECISION_GOOGLE]


def test_facts_line_names_the_body_that_decided() -> None:
    """The Google grant was An Coimisiún Pleanála's, on appeal, not the council's."""
    from app.brief.prompts import _record_lines
    from app.ground.types import GroundTruth

    lines: list[str] = []
    _record_lines(lines, GroundTruth(decisions=[DECISION_GOOGLE]))
    assert "was approved by An Coimisiún Pleanála on 2026-09-23" in lines[0]
    assert "South Dublin County Council" not in lines[0]
    us = replace(DECISION_GOOGLE, decided_by=None)
    lines = []
    _record_lines(lines, GroundTruth(decisions=[us]))
    assert "was approved by the South Dublin County Council on" in lines[0]


async def test_provider_names_label_failures() -> None:
    truth = await gather_ground(GEO_IE, ie_ground(utility=FakeIeUtility(fail=True)))
    assert truth.utility is None
    assert FakeIeUtility.failure_note in truth.notes

    class _Failing:
        name = EurostatPrices.name
        failure_note = EurostatPrices.failure_note

        async def series(self, jurisdiction: str):
            raise RuntimeError("down")

    truth = await gather_ground(GEO_IE, ie_ground(prices=_Failing()))
    assert truth.price is None and EurostatPrices.failure_note in truth.notes


async def test_outside_the_map_has_no_note() -> None:
    truth = await gather_ground(GEO_IE, ie_ground(utility=FakeIeUtility(outside=True)))
    assert truth.utility is None and truth.notes == []
    # No utility: the country-wide policy row still applies.
    assert truth.tariff == TARIFF_IE


async def test_us_gather_ground_is_unchanged_by_the_ie_fields() -> None:
    """The defaults: state key, authority scope. Covered byte for byte by the
    golden; here, the keys actually passed."""
    tariffs = _Recording(FakeTariffs(None))
    prices = _Recording(FakePrices(None))
    hearings = FakeHearingIndex(None, [replace(DECISION_GOOGLE, body="X")])
    called: list[str] = []
    orig_all = hearings.all_decisions

    def all_decisions():
        called.append("all")
        return orig_all()

    hearings.all_decisions = all_decisions  # type: ignore[method-assign]
    g = Ground(tariffs=tariffs, prices=prices, hearings=hearings)
    await gather_ground(GEO, g)
    assert tariffs.keys == ["VA"] and prices.keys == ["VA"]
    assert called == []


# --- facility vocabulary --------------------------------------------------------------

# The step-5 list, copied from b02e7d1. Appending keeps every earlier match.
_US_VOCAB = [
    "Equinix", "Digital Realty", "Vantage", "Sabey", "Microsoft", "Meta", "Facebook", "Google",
    "Amazon", "AWS", "NTT", "RagingWire", "CyrusOne", "STACK", "QTS", "CloudHQ", "Aligned",
    "Compass", "Iron Mountain", "CoreSite", "Flexential", "H5", "EdgeCore", "Novva", "Switch",
    "Cologix", "DataBank", "Lumen", "Level 3", "Centersquare", "PowerHouse", "Yahoo", "Apple",
    "Oracle", "Vantage", "Stream", "T5", "Cyxtera", "Evoque", "Lightedge", "Colocation Northwest",
    "Centeris", "Intergate", "Westin", "Zayo", "Telx", "365", "Expedient", "TierPoint",
]  # fmt: skip


def test_vocabulary_only_appends() -> None:
    assert fac._OPERATOR_VOCAB[: len(_US_VOCAB)] == _US_VOCAB
    for name in ("Interxion DUB1", "Keppel DC Dublin 1", "Servecentric Blanchardstown",
                 "Cork Internet Exchange", "CIX Cork", "Echelon DUB10"):  # fmt: skip
        assert fac.operator_from_name(name) is not None


def test_us_oracle_names_resolve_as_before() -> None:
    """Every operator the US eval set expects, and the names it would appear
    under, resolve exactly as with the step-5 vocabulary."""
    rows = json.loads((REPO_ROOT / "eval" / "us" / "addresses.json").read_text(encoding="utf-8"))
    names = {op for r in rows["addresses"] for op in (r.get("expect", {}).get("operators") or [])}
    names |= {f"{n} campus 1" for n in names}
    assert names

    def old(name: str) -> str | None:
        low = name.lower()
        for op in _US_VOCAB:
            if low.startswith(op.lower()):
                return {"Facebook": "Meta", "AWS": "Amazon", "RagingWire": "NTT",
                        "Intergate": "Sabey"}.get(op, op)  # fmt: skip
        return None

    for n in sorted(names):
        assert fac.operator_from_name(n) == old(n), n
    for us in ("Amazon Web Services", "Facebook", "Equinix, Inc.", "Digital Realty Trust"):
        assert fac.norm_operator(us) in {"amazon", "meta", "equinix", "digital realty"}
