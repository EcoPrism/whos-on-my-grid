"""Ireland's curated data (data/regions/ie, eval/ie): the loaders read it, every
quote is on its cited page, and nothing personal is committed.

Each cited page is checked against a saved text window
(tests/fixtures/pages/<name>.txt: the URL, a blank line, then the page's text
around the quote as app.brief.fetch.html_to_text made it on 2026-10-29). No
network here; re-fetch with the stream-E page script when a source changes.
"""

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.brief.verify import find_quote
from app.config import REPO_ROOT
from app.ground.facilities import load_name_fixes, load_overrides
from app.ground.hearings import HearingIndex
from app.ground.tariffs import TariffEntry, TariffTable
from app.scenario.constants import load_region

IE_DIR = REPO_ROOT / "data" / "regions" / "ie"
EVAL_IE = REPO_ROOT / "eval" / "ie" / "addresses.json"
PAGES = Path(__file__).parent / "fixtures" / "pages"
GEOJSON = IE_DIR / "utilities" / "ie.geojson"
# A full Eircode: routing key and unique identifier. Routing keys alone (D15, D6W) are fine.
FULL_EIRCODE = re.compile(
    r"\b[AC-FHKNPRTV-Y]\d{2}\s?[0-9AC-FHKNPRTV-Y]{4}\b|\bD6W\s?[0-9AC-FHKNPRTV-Y]{4}\b"
)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _pages() -> dict[str, str]:
    """URL -> saved text window."""
    out = {}
    for p in sorted(PAGES.glob("*.txt")):
        url, _, text = p.read_text(encoding="utf-8").partition("\n")
        out[url.strip()] = text
    return out


def _cited() -> list[tuple[str, str, str]]:
    """(where, url, quote) for every quote the IE data asks the verifier to find."""
    rows: list[tuple[str, str, str]] = []
    for c in _json(IE_DIR / "constants.json")["constants"]:
        rows.append((f"constants/{c['id']}", c["source_url"], c["quote"]))
    for e in _json(IE_DIR / "tariffs.json")["entries"]:
        rows.append((f"tariffs/{e['name']}", e["url"], e["quote"]))
    for b in _json(IE_DIR / "hearings" / "sources.json")["bodies"]:
        for d in b["decisions"]:
            rows.append((f"decisions/{d['project']}", d["source_url"], d["quote"]))
    props = _json(GEOJSON)["features"][0]["properties"]
    rows.append(("utility", props["source_url"], props["quote"]))
    rows.append(("utility customers", props["customers_source_url"], props["customers_quote"]))
    return rows


# --- loaders --------------------------------------------------------------------


def test_constants_load() -> None:
    table = load_region(IE_DIR)
    assert table["ie_home_kwh_per_year"].value == 4200
    assert table["ie_home_kwh_per_year"].source_url == "https://www.cru.ie/publications/25651/"
    assert table["ie_dc_share_metered_electricity"].value == 0.23
    # The shared equivalences are still underneath.
    assert len(table) > 2


def test_constants_only_what_a_code_path_reads() -> None:
    ids = {c["id"] for c in _json(IE_DIR / "constants.json")["constants"]}
    assert ids == {"ie_home_kwh_per_year", "ie_dc_share_metered_electricity"}


def test_tariff_row_loads_and_matches_country() -> None:
    table = TariffTable(IE_DIR / "tariffs.json")
    t = table.match("IE", None)
    assert t is not None and t.kind == "connection_policy"
    assert t.status == "in_force" and t.protects_households is False
    assert t.docket is None and t.min_mw is None and t.quote
    assert t.lead == "No."
    assert table.match("ie", "ESB Networks DAC") is t
    # Keyed by country, never by county code.
    assert table.match("IE-D", None) is None


def test_tariff_keys_are_tariff_entry_fields() -> None:
    fields = {f.name for f in dataclasses.fields(TariffEntry)}
    for e in _json(IE_DIR / "tariffs.json")["entries"]:
        assert set(e) == fields


def test_tariff_row_says_no_more_than_its_aim() -> None:
    e = _json(IE_DIR / "tariffs.json")["entries"][0]
    text = f"{e['name']} {e['summary']}".lower()
    assert "cru2025236" not in text  # the docket is not on the cited page
    for overclaim in ("bill shield", "protects households", "shields"):
        assert overclaim not in text


def test_hearing_sources_load() -> None:
    idx = HearingIndex(IE_DIR / "hearings")
    assert {b["id"] for b in idx.bodies()} == {"sdcc", "fingal"}
    decisions = idx.all_decisions()
    assert len(decisions) == 1
    d = decisions[0]
    assert (d.lat, d.lon) == (53.3144, -6.4443)  # OSM relation 4546404, Profile Park
    assert d.status == "approved" and d.body == "South Dublin County Council"
    assert d.source_url == "https://www.pleanala.ie/en-ie/case/320852"
    # Matched by authority, Fingal has none; by radius (all_decisions) it is there.
    assert idx.decisions_for("IE-D", "Fingal") == []
    assert idx.decisions_for("IE-D", "South Dublin") == decisions
    # No meeting is indexed, so nothing to quote, and the archive kinds do not break lookup.
    assert idx.for_place("IE-D", "South Dublin") is None
    assert idx.for_place("IE-D", "Fingal") is None


def test_decision_text_keeps_history_out() -> None:
    for b in _json(IE_DIR / "hearings" / "sources.json")["bodies"]:
        for d in b["decisions"]:
            assert "judicial review" not in d["text"].lower()
            assert "refused" not in d["text"].lower()


def test_facilities_file() -> None:
    path = IE_DIR / "facilities.json"
    assert load_name_fixes(path) == frozenset({4256})
    assert load_overrides(path) == []


def test_geojson_shape_and_attribution() -> None:
    doc = _json(GEOJSON)
    assert doc["type"] == "FeatureCollection" and len(doc["features"]) == 1
    f = doc["features"][0]
    assert f["geometry"]["type"] == "MultiPolygon"
    p = f["properties"]
    assert (p["name"], p["raw_name"], p["kind"]) == ("ESB Networks", "ESB Networks DAC", "DSO")
    assert p["boundary_licence"] == "CC BY 4.0"
    assert p["boundary_attribution"] == "© Tailte Éireann"
    assert p["simplify_tolerance_deg"] == 0.002
    assert (
        p["claim"]
        == "ESB Networks DAC is the licensed Distribution System Operator (DSO) for Ireland."
    )
    for word in ("single", "only"):
        assert word not in p["claim"].lower()
    assert GEOJSON.stat().st_size < 400_000
    assert "CC BY 4.0" in (IE_DIR / "README.md").read_text(encoding="utf-8")


INSIDE = {
    "Dublin": (53.3498, -6.2603),
    "Cork": (51.8985, -8.4756),
    "Galway": (53.2707, -9.0568),
    "Dundalk": (54.0090, -6.4049),
    "Clones": (54.1797, -7.2318),
    "Lifford": (54.8337, -7.4797),
}
OUTSIDE = {
    "Belfast": (54.5973, -5.9301),
    "Derry": (54.9966, -7.3086),
    "Strabane": (54.8270, -7.4633),
    "Newry": (54.1751, -6.3402),
}


@pytest.fixture(scope="module")
def esb() -> Any:
    mod = pytest.importorskip("app.ground.geojson_utility")
    return mod.GeoJsonUtility(GEOJSON)


@pytest.mark.parametrize("place", sorted(INSIDE))
def test_irish_towns_are_on_the_map(esb: Any, place: str) -> None:
    lat, lon = INSIDE[place]
    u = esb.match(lat, lon)
    assert u is not None and u.name == "ESB Networks"


@pytest.mark.parametrize("place", sorted(OUTSIDE))
def test_northern_ireland_is_off_the_map(esb: Any, place: str) -> None:
    lat, lon = OUTSIDE[place]
    assert esb.match(lat, lon, "GB") is None


def test_every_eval_row_is_on_the_map(esb: Any) -> None:
    for row in _json(EVAL_IE)["addresses"]:
        g = row["geocode"]
        assert esb.match(g["lat"], g["lon"]) is not None, row["id"]


# --- quotes on their pages ------------------------------------------------------


def test_every_cited_page_has_a_window() -> None:
    pages = _pages()
    missing = sorted({url for _, url, _ in _cited()} - set(pages))
    assert missing == []


@pytest.mark.parametrize("where,url,quote", _cited(), ids=[w for w, _, _ in _cited()])
def test_quote_is_on_its_page(where: str, url: str, quote: str) -> None:
    text = _pages()[url]
    assert find_quote(text, quote) is not None


def test_windows_are_short() -> None:
    for p in PAGES.glob("*.txt"):
        assert len(p.read_text(encoding="utf-8")) < 2500, p.name


def test_planning_window_stops_before_the_parties() -> None:
    text = (PAGES / "acp_320852.txt").read_text(encoding="utf-8")
    assert "Parties" not in text
    assert "Grant Permissions with Conditions" in text


# --- nothing personal ------------------------------------------------------------


def _committed_ie_files() -> list[Path]:
    files = [p for p in IE_DIR.rglob("*") if p.is_file()]
    files += [EVAL_IE, *PAGES.glob("*.txt")]
    return files


def test_no_full_eircode_anywhere() -> None:
    hits = []
    for p in _committed_ie_files():
        n = len(FULL_EIRCODE.findall(p.read_text(encoding="utf-8")))
        if n:
            hits.append(f"{p.name}: {n}")  # never the match itself
    assert hits == []


def test_eircode_pattern_catches_the_shape() -> None:
    # Built from parts so no full Eircode sits in this file as a literal.
    sample = "D15" + " " + "T1FD"
    assert FULL_EIRCODE.search(sample)
    assert FULL_EIRCODE.search("D6W" + "X1Y2")
    assert not FULL_EIRCODE.search("Blanchardstown, Fingal, Co. Dublin, D15")


def test_eval_rows_have_no_house_numbers() -> None:
    for row in _json(EVAL_IE)["addresses"]:
        for text in (row["address"], row["geocode"]["display"], row["geocode"]["matched"]):
            assert not re.match(r"^\s*\d", text), row["id"]
        g = row["geocode"]
        assert round(g["lat"], 3) == g["lat"] and round(g["lon"], 3) == g["lon"]
