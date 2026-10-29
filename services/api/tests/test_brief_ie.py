"""An Irish brief from the engine: the words, units and currency of plan 0.4-0.10,
the two price claims, the ESB utility claim, the CRU connection policy and its
stated aim, the national-price band rule and the coverage guard. Ground comes
from tests/fakes_ie.py; nothing here touches the network."""

import json
import re
from dataclasses import replace
from typing import Any

import pytest

from app.brief import prompts
from app.brief.assemble import CONNECTION_POLICY_AIM, CONNECTION_POLICY_CARD, assemble_brief
from app.brief.draft import SectionFailure
from app.ground import (
    FakeFacilityDatabase,
    FakeHearingIndex,
    FakePrices,
    GroundFacility,
    gather_ground,
)
from app.regions import IE_LOCALE
from app.schema import SECTION_IDS, brief_errors, house_schemas
from tests import fakes, fakes_ie

NOW = "2026-10-29T12:00:00Z"
FULL_EIRCODE = re.compile(r"\b(?:[AC-FHKNPRTV-Y]\d{2}|D6W)\s?[0-9AC-FHKNPRTV-Y]{4}\b")
LONG_COORD = re.compile(r"-?\d+\.\d{5,}")
US_WORDS = ("mile", " acres", "$", "ZIP", "statewide", "Statewide", "County Council County")

# A hearing draft with nothing American in it, so the pipeline has one drafted
# section and every other sentence is the engine's.
IE_HEARING_DRAFT = {
    "confidence": 0.1,
    "summary": "Not known.",
    "gap": "No meeting record was found.",
    "card_line": None,
    "hearing": {"next_date": None, "body": None},
    "claims": [],
}


def _failures() -> dict[str, SectionFailure]:
    return {sid: SectionFailure(sid, "Not drafted in this test.") for sid in SECTION_IDS}


async def _brief(ground: Any = None, *, geo: Any = fakes.GEO_IE, **kw: Any) -> dict[str, Any]:
    truth = await gather_ground(geo, ground or fakes_ie.ie_ground())
    return assemble_brief(
        geo,
        _failures(),
        [],
        brief_id=fakes.IE_BRIEF_ID,
        now_iso=NOW,
        truth=truth,
        locale=IE_LOCALE,
        coverage=frozenset({"on_your_grid", "your_bill", "protection"}),
        **kw,
    )


def _engine_text(brief: dict[str, Any]) -> list[str]:
    """Every sentence the engine wrote, less the facility and project names that
    come from OpenStreetMap, PeeringDB or the planning record."""
    names = [
        f["name"]
        for s in brief["sections"].values()
        for f in [*(s.get("facilities") or []), *([s["beyond_ring"]] if "beyond_ring" in s else [])]
    ]
    out = [brief["headline"]["one_liner"], brief["card"]["title"], *brief["card"]["lines"]]
    for s in brief["sections"].values():
        out += [s.get("summary") or "", s.get("gap") or ""]
    out += [line["text"] for line in brief.get("at_your_house") or []]
    out += [c["text"] for c in brief["claims"] if c["drafted_by"] == "engine"]
    cleaned = []
    for text in out:
        for n in names:
            text = text.replace(n, "<name>")
        cleaned.append(text)
    return cleaned


async def test_ie_brief_is_valid_and_irish() -> None:
    brief = await _brief()
    assert not brief_errors(brief)
    a = brief["address"]
    assert "state" not in a and "zip" not in a
    assert a["country"] == "IE" and a["region_code"] == "IE-D" and a["postal_code"] == "D15"
    assert a["county"] == "Fingal" and a["utility"] == "ESB Networks"
    assert brief["locale"] == {
        "country": "IE",
        "currency": "EUR",
        "units": "metric",
        "language": "en-IE",
    }
    text = " ".join(_engine_text(brief))
    for word in US_WORDS:
        assert word not in text, word
    assert not re.search(r"data[- ]centers?\b", text), text
    assert "8 km" in text and "€" in text and "data centre" in text
    assert "first half of 2026" in text and "first half of 2024" in text
    assert "No regulator" not in text
    assert brief["card"]["title"] == "Who's on my grid: Blanchardstown, Co. Dublin"
    assert brief["headline"]["percentile"] is None


async def test_ie_bill_section_and_claims() -> None:
    brief = await _brief()
    bill = brief["sections"]["your_bill"]
    assert bill["status"] == "modelled"
    assert bill["price"] == {
        "currency": "EUR",
        "rate_now": 0.3871,
        "rate_then": 0.259,
        "trend_pct": 49.5,
        "window_months": 24,
        "typical_household_kwh_month": 350.0,
        "attribution": None,
        "as_of": "2026-06",
        "granularity": "semiannual",
    }
    assert bill["summary"] == (
        "For homes in Ireland, the average home electricity price was €0.387 per kWh in the first "
        "half of 2026, against €0.259 in the first half of 2024, a change of +49.5%. For a typical "
        "home here using about 350 kWh a month, that is about €45 a month more."
    )
    claims = [c for c in brief["claims"] if c["section"] == "your_bill"]
    assert [(c["text"], c["source"]["url"], c["source"]["quote"]) for c in claims] == [
        (fakes_ie.EUROSTAT_CLAIM, fakes_ie.EUROSTAT_COMPACT_URL, fakes_ie.EUROSTAT_QUOTE),
        (fakes_ie.CRU_KWH_CLAIM, fakes_ie.CRU_KWH_URL, fakes_ie.CRU_KWH_QUOTE),
    ]
    assert all(c["drafted_by"] == "engine" for c in claims)
    assert claims[1]["source"]["title"] == fakes_ie.CRU_KWH_TITLE
    assert not any("eia.gov" in c["source"]["url"] for c in brief["claims"])  # no EPM claim
    assert "+€45/mo for a typical home in Ireland vs 2 yrs ago" in brief["card"]["lines"]
    h = brief["headline"]
    assert h["ai_rent_usd_per_month"] == 44.8 and h["ai_rent_range_usd_per_month"] == [36.0, 54.0]
    assert h["one_liner"].endswith(
        "A typical home in Ireland paid about €45 more a month in the first half of 2026 than in "
        "the first half of 2024."
    )
    strip = brief["at_your_house"][0]
    assert strip["topic"] == "bill" and strip["text"] == (
        "Your power bill was about €45 a month higher in the first half of 2026 than in the first "
        "half of 2024, somewhere between €36 and €54 depending on how much electricity you use."
    )


async def test_ie_bill_without_typical_use_is_not_measured() -> None:
    price = replace(fakes_ie.PRICE_IE, typical_kwh_month=None)
    brief = await _brief(fakes_ie.ie_ground(prices=FakePrices(price)))
    assert not brief_errors(brief)
    bill = brief["sections"]["your_bill"]
    assert bill["status"] == "unavailable" and "price" not in bill
    assert "No typical household consumption figure" in bill["gap"]
    assert brief["headline"]["ai_rent_usd_per_month"] is None


async def test_ie_utility_claim_and_outside_map() -> None:
    brief = await _brief()
    esb = [c for c in brief["claims"] if c["source"]["url"] == fakes_ie.ESB_SOURCE_URL]
    assert len(esb) == 1
    assert esb[0]["text"] == fakes_ie.ESB_CLAIM and esb[0]["source"]["quote"] == fakes_ie.ESB_QUOTE
    assert esb[0]["source"]["title"] == "ESB Networks, About ESB Networks DAC"
    assert "only" not in esb[0]["text"] and "single" not in esb[0]["text"]

    outside = await _brief(fakes_ie.ie_ground(utility=fakes_ie.FakeIeUtility(outside=True)))
    assert not brief_errors(outside)
    assert outside["address"]["utility"] is None
    gap = outside["sections"]["on_your_grid"]["gap"]
    assert "The point is outside the ESB Networks service map." in gap

    failed = await _brief(fakes_ie.ie_ground(utility=fakes_ie.FakeIeUtility(fail=True)))
    gap = failed["sections"]["on_your_grid"]["gap"]
    assert fakes_ie.ESB_FAILURE_NOTE in gap and "outside the ESB" not in gap


async def test_ie_protection_is_a_connection_policy() -> None:
    brief = await _brief()
    p = brief["sections"]["protection"]
    assert p["tariff"] == {
        "large_load_tariff": "in_force",
        "name": "CRU connection policy for new data centres (December 2025)",
        "protects_households": False,
        "docket": None,
        "kind": "connection_policy",
    }
    assert p["summary"].startswith(f"No. {CONNECTION_POLICY_AIM} The Commission for Regulation")
    assert CONNECTION_POLICY_AIM == (
        "Its stated aim is grid constraints, security of supply and renewable targets, not "
        "household costs."
    )
    assert CONNECTION_POLICY_CARD in brief["card"]["lines"]
    assert CONNECTION_POLICY_CARD == (
        "CRU data-centre connection policy in force; household bills not its stated aim"
    )
    assert len(CONNECTION_POLICY_CARD) == 78
    claim = next(c for c in brief["claims"] if c["section"] == "protection")
    assert claim["source"]["quote"] == fakes_ie.TARIFF_IE.quote
    assert "shield" not in " ".join(_engine_text(brief)).lower()


def _live(n: int) -> list[GroundFacility]:
    base = fakes_ie.FACILITIES_IE[0]
    return [replace(base, name=f"Fictional Site {i}", distance_km=1.0 + i) for i in range(n)]


@pytest.mark.parametrize(("n", "band"), [(0, "low"), (2, "medium"), (3, "high"), (6, "high")])
async def test_ie_band_comes_from_facilities_not_the_national_price(n: int, band: str) -> None:
    brief = await _brief(fakes_ie.ie_ground(facilities=FakeFacilityDatabase(_live(n))))
    assert brief["headline"]["ai_rent_usd_per_month"] == 44.8  # +€45: critical on the US scale
    assert brief["headline"]["band"] == band


async def test_ie_coming_lists_the_google_decision_with_distance() -> None:
    brief = await _brief()
    coming = brief["sections"]["coming"]
    google = coming["facilities"][0]
    assert google["name"] == fakes_ie.DECISION_GOOGLE.project
    assert google["status"] == "announced" and 9.0 < google["distance_km"] < 10.0
    assert (google["lat"], google["lon"]) == (53.3144, -6.4443)
    assert coming["status"] == "reported"
    assert "Aerial imagery is not indexed for Ireland" in coming["gap"]
    claim = next(c for c in brief["claims"] if c["section"] == "coming")
    assert claim["source"]["url"] == "https://www.pleanala.ie/en-ie/case/320852"


async def test_ie_grid_section_in_km() -> None:
    brief = await _brief()
    grid = brief["sections"]["on_your_grid"]
    assert grid["status"] == "measured"
    assert grid["summary"].startswith(
        "2 data-centre facilities are within 8 km of this address according to PeeringDB and "
        "OpenStreetMap: 1 operating and 1 under construction. The nearest is Halvex Dublin 15 "
        "Campus, 0.9 km away, operated by Halvex Digital."
    )
    assert "2 data centres within 8 km" in brief["card"]["lines"]
    noise = next(line for line in brief["at_your_house"] if line["topic"] == "noise")
    assert "0.9 km from your house" in noise["text"]
    osm = next(c for c in brief["claims"] if "osm/way/9002" in c["source"]["url"])
    assert "under construction" in osm["text"]


async def test_ie_hearing_gap_names_no_us_docs() -> None:
    brief = await _brief()
    gap = brief["sections"]["hearing"]["gap"]
    assert "docs/counties.md" not in gap and "County" not in gap.replace("County Council", "")
    noted = await _brief(
        fakes_ie.ie_ground(
            hearings=FakeHearingIndex(
                None,
                [fakes_ie.DECISION_GOOGLE],
                note="Fingal County Council is in the index but no meeting has been transcribed "
                "yet",
            )
        )
    )
    assert "Fingal County Council is in the index" in noted["sections"]["hearing"]["gap"]


async def test_coverage_guard_downgrades_measured_sections() -> None:
    truth = await gather_ground(fakes.GEO_IE, fakes_ie.ie_ground())
    brief = assemble_brief(
        fakes.GEO_IE,
        _failures(),
        [],
        brief_id=fakes.IE_BRIEF_ID,
        now_iso=NOW,
        truth=truth,
        locale=IE_LOCALE,
        coverage=frozenset({"your_bill"}),
    )
    assert brief["sections"]["on_your_grid"]["status"] == "reported"
    assert not brief_errors(brief)
    full = await _brief()
    for sid, section in full["sections"].items():
        if section["status"] == "measured":
            assert sid in {"on_your_grid", "your_bill", "protection"}, sid


async def test_us_brief_has_no_kind_and_keeps_state() -> None:
    from tests.test_full_mode import ground

    truth = await gather_ground(fakes.GEO, ground())
    brief = assemble_brief(fakes.GEO, _failures(), [], brief_id="0" * 16, now_iso=NOW, truth=truth)
    assert brief["address"]["state"] == "VA" and brief["address"]["zip"] == "20147"
    assert "kind" not in json.dumps(brief["sections"]["protection"].get("tariff") or {})


# --- prompts ------------------------------------------------------------------------


async def _ie_prompts() -> list[str]:
    truth = await gather_ground(fakes.GEO_IE, fakes_ie.ie_ground())
    out = [
        prompts.system_prompt(NOW, locale=IE_LOCALE),
        prompts.house_system_prompt(NOW, locale=IE_LOCALE),
        prompts.house_prompt(fakes.GEO_IE, {}, truth, locale=IE_LOCALE),
        prompts.house_prompt(fakes.GEO_IE, {"on_your_grid": "x"}, locale=IE_LOCALE),
    ]
    for t in (None, truth):
        out += [
            prompts.section_prompt(sid, fakes.GEO_IE, t, locale=IE_LOCALE) for sid in SECTION_IDS
        ]
    return out


async def test_ie_prompts_speak_to_an_irish_resident() -> None:
    texts = await _ie_prompts()
    assert "an Irish resident" in texts[0]
    joined = "\n".join(texts)
    assert "EUR" in joined
    assert "Address (town and Eircode routing key only):" in joined
    assert "routing key D15" in joined
    assert "Address (street and city only)" not in joined
    assert not FULL_EIRCODE.search(joined)
    assert not LONG_COORD.search(joined), LONG_COORD.findall(joined)[:3]
    for word in ("ZIP", "State:", " mi |", "five miles", "cents/kWh", "HIFLD"):
        assert word not in joined, word
    grid = texts[4 + 5]  # section_prompt("on_your_grid", truth)
    assert "Facilities within 8 km" in grid and "0.9 km |" in grid
    bill = texts[4 + 5 + 2]
    assert "Eurostat nrg_pc_204" in bill and "EUR 0.3871 per kWh in 2026-S1" in bill
    assert "currency EUR, rate_then 0.259, rate_now 0.3871" in bill
    protection = texts[4 + 5 + 3]
    assert "Connection policy on record:" in protection


def test_metric_house_schema_compares_to_kilometres() -> None:
    us, _ = house_schemas()
    metric, _ = house_schemas("metric")
    item = metric["properties"]["lines"]["items"]["properties"]["text"]["description"]
    assert "kilometres" in item and "miles" not in item
    assert "miles" in us["properties"]["lines"]["items"]["properties"]["text"]["description"]


# --- the service --------------------------------------------------------------------


async def test_ie_service_passes_locale_and_coverage(tmp_path) -> None:
    svc = fakes.services(tmp_path, ("us", "ie"), brief_source="full")["ie"]
    svc.draft_provider._responses = {"draft_hearing": IE_HEARING_DRAFT}
    brief = await svc.brief_for_address("Blanchardstown Centre, Dublin 15")
    assert not brief_errors(brief)
    assert brief["brief_id"] == fakes.IE_BRIEF_ID
    assert brief["locale"]["country"] == "IE" and "state" not in brief["address"]
    sent = {name: msgs for name, msgs in svc.draft_provider.calls}
    assert "an Irish resident" in sent["draft_on_your_grid"][0]["content"]
    assert "routing key D15" in sent["draft_your_bill"][1]["content"]
    assert "neighbour" in sent["draft_at_your_house"][0]["content"]
    assert brief["sections"]["hearing"]["status"] == "reported"
    text = " ".join(_engine_text(brief))
    assert "$" not in text and "mile" not in text
