"""The glance block and the quieter strip: one tile entry per concern, the
noise sentence only where it says something, and the model's 'not public'
lines folded into one."""

import dataclasses

from app.ground import FakeFacilityDatabase, FakeHearingIndex
from app.llm.base import LLMError
from app.schema import validate_brief
from tests import fakes
from tests.test_full_mode import FACILITIES, ground
from tests.test_step4_full_mode import DECISION, HEARING, TRANSCRIPT

ASHBURN = "21715 Filigree Ct, Ashburn, VA"


def _far(km: float) -> FakeFacilityDatabase:
    """The Ashburn fakes with the nearest campus moved out to `km`."""
    first, rest = FACILITIES[0], FACILITIES[1:]
    return FakeFacilityDatabase([dataclasses.replace(first, distance_km=km), *rest])


def _quiet_water() -> dict:
    """A house draft whose water line only says nothing is published."""
    d = fakes.drafts()
    d["draft_at_your_house"]["lines"][0] = {
        "text": "The data centers near you do not publish how much water they use.",
        "topic": "water",
        "confidence": 0.6,
        "claims": [
            fakes.claim(
                "No water-use figure for the Northgate campus is on the water authority's page.",
                fakes.URL_WATER,
                "4.2 MGD",
                "Water permits",
            )
        ],
    }
    return d


async def test_glance_has_a_number_where_the_engine_has_one(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground()
    brief = await svc.brief_for_address(ASHBURN)
    validate_brief(brief)
    g = brief["glance"]
    assert list(g) == ["bill", "grid", "noise", "water", "land", "taxes", "air"]

    assert g["bill"]["status"] == "modelled" and g["bill"]["value"] == "+$16 to $24"
    assert g["bill"]["sub"] == "a month for a typical home, vs two years ago"
    assert g["bill"]["text"].startswith("Your power bill is about $20 a month higher")

    assert g["grid"]["status"] == "measured" and g["grid"]["value"] == "2"
    assert g["grid"]["sub"] == "within five miles, nearest 0.2 miles"

    noise = g["noise"]
    assert noise["status"] == "modelled" and noise["value"] == "0.2 miles"
    assert noise["sub"] == "to Northgate Campus DC1-DC9, can be heard outdoors, especially at night"
    assert noise["text"] and "0.2 miles from your house" in noise["text"]
    assert noise["sources"][0]["url"] == "https://www.peeringdb.com/fac/1"

    # The model's water line says something: the tile carries the sentence.
    assert g["water"]["status"] == "reported" and g["water"]["value"] is None
    assert g["water"]["text"].startswith("The data centers near you may use up to 4.2 million")
    assert g["water"]["sources"][0]["url"] == fakes.URL_WATER

    # Nothing written on taxes, land or air: Not public, with who to ask.
    for topic in ("land", "taxes", "air"):
        assert g[topic]["status"] == "unavailable" and g[topic]["value"] is None
        assert g[topic]["sub"] == "Ask Loudoun County and Dominion Energy Virginia"


async def test_quiet_lines_fold_into_one(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full", draft_responses=_quiet_water())
    svc.ground = ground()
    brief = await svc.brief_for_address(ASHBURN)
    validate_brief(brief)
    topics = [line["topic"] for line in brief["at_your_house"]]
    assert topics == ["bill", "noise", "other"]
    folded = brief["at_your_house"][-1]
    assert folded["status"] == "unavailable" and folded["confidence"] == 0.6
    assert folded["text"] == (
        "Not public: water use. The operators near you do not publish it; Loudoun County and "
        "Dominion Energy Virginia are where to ask."
    )
    # The page the model cited for the gap stays a claim, on the folded line.
    assert folded["sources"][0]["url"] == fakes.URL_WATER
    assert any(
        c["section"] == "at_your_house" and c["source"]["url"] == fakes.URL_WATER
        for c in brief["claims"]
    )
    water = brief["glance"]["water"]
    assert water["status"] == "unavailable" and water["text"] is None
    assert water["sub"] == "Ask Loudoun County and Dominion Energy Virginia"
    assert water["confidence"] == 0.6


async def test_noise_sentence_only_within_half_a_mile(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(facilities=_far(1.5))  # 0.9 miles
    brief = await svc.brief_for_address(ASHBURN)
    validate_brief(brief)
    assert all(line["topic"] != "noise" for line in brief["at_your_house"])
    noise = brief["glance"]["noise"]
    assert noise["status"] == "modelled" and noise["value"] == "0.9 miles"
    assert noise["sub"] == "to Northgate Campus DC1-DC9, unlikely to carry over neighborhood sound"
    assert noise["text"] is None and noise["sources"][0]["url"] == "https://www.peeringdb.com/fac/1"


async def test_noise_sentence_returns_when_a_hearing_raised_it(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(
        facilities=_far(1.5), hearings=FakeHearingIndex(HEARING, [DECISION], TRANSCRIPT)
    )
    brief = await svc.brief_for_address(ASHBURN)
    validate_brief(brief)
    noise = next(line for line in brief["at_your_house"] if line["topic"] == "noise")
    assert noise["status"] == "measured"
    assert noise["text"] == (
        "Noise came up at the Example County Board of Supervisors meeting on 2026-10-14. The "
        "nearest data-center building, Northgate Campus DC1-DC9, is 0.9 miles from your house."
    )
    # The transcript line is the quote; the facility page is the second source.
    assert noise["sources"][0]["quote"].startswith("The hum from the data center")
    assert noise["sources"][1]["url"] == "https://www.peeringdb.com/fac/1"
    tile = brief["glance"]["noise"]
    assert tile["status"] == "measured" and tile["sub"].endswith("came up at a public meeting")


async def test_nothing_nearby_says_so_on_every_tile(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(facilities=FakeFacilityDatabase([]))
    brief = await svc.brief_for_address("1 Main St, Bozeman, MT")
    validate_brief(brief)
    g = brief["glance"]
    assert g["grid"]["value"] == "0" and g["grid"]["sub"] == "none within five miles"
    assert g["noise"]["status"] == "measured" and g["noise"]["value"] == "None"
    assert g["noise"]["sub"] == "nothing within five miles to hear"
    # Nothing nearby is a measured fact on every tile, not a gap in what is published.
    for topic in ("water", "land", "taxes", "air"):
        assert g[topic]["status"] == "measured" and g[topic]["value"] == "None"
        assert g[topic]["sub"] == "no data center within five miles"


async def test_no_price_leaves_the_bill_tile_not_public(tmp_path) -> None:
    responses = fakes.drafts()
    responses["draft_your_bill"] = LLMError("no")
    svc = fakes.service(tmp_path, draft_responses=responses)
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    bill = brief["glance"]["bill"]
    assert bill["status"] == "unavailable" and bill["value"] is None
    assert bill["sub"] == "No household price series for this utility"
    # Agent mode has no facility list: no noise tile beyond the model's own line.
    assert brief["glance"]["noise"]["status"] == "reported"
