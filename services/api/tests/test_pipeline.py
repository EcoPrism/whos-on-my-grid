import pytest

from app.brief.pipeline import DraftingUnavailable
from app.config import DRAFT_MODEL_ID
from app.llm.base import LLMError
from app.schema import SECTION_IDS, validate_brief
from tests import fakes


async def test_full_brief_is_valid_and_reported(tmp_path) -> None:
    svc = fakes.service(tmp_path)
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    validate_brief(brief)
    assert brief["source_mode"] == "agent" and brief["fixture"] is False
    assert len(brief["brief_id"]) == 16
    for sid in SECTION_IDS:
        assert brief["sections"][sid]["status"] == "reported"
        assert brief["sections"][sid]["model"] == DRAFT_MODEL_ID
    assert [c["id"] for c in brief["claims"]] == [f"c{i}" for i in range(1, 8)]
    assert brief["claims"][-1]["section"] == "at_your_house"
    assert brief["sections"]["coming"]["construction"] == []
    assert brief["sections"]["coming"]["facilities"][0]["status"] == "announced"
    # Verdicts: fetched pages are supported, the missing page is unverifiable with the reason.
    by_url = {c["source"]["url"]: c for c in brief["claims"]}
    assert by_url[fakes.URL_REG]["verdict"] == "supported"
    assert by_url[fakes.URL_REG]["verified_by"] == svc.settings.verify_model
    gone = by_url[fakes.URL_GONE]
    assert gone["verdict"] == "unverifiable" and "HTTP 404" in gone["verifier_note"]
    assert gone["verified_by"] is None
    # Headline from the price object.
    h = brief["headline"]
    assert (
        h["ai_rent_usd_per_month"] == 20.9 and h["band"] == "critical" and h["percentile"] is None
    )
    assert h["ai_rent_range_usd_per_month"] == [17.0, 25.0]
    assert "$21 more a month" in h["one_liner"]
    # The strip: the bill sentence is derived, the rest is drafted and reported.
    strip = brief["at_your_house"]
    assert [line["topic"] for line in strip] == ["bill", "water", "noise"]
    assert strip[0]["status"] == "modelled" and "$21 a month higher" in strip[0]["text"]
    assert "between $17 and $25" in strip[0]["text"]
    assert strip[0]["sources"] == brief["sections"]["your_bill"]["sources"]
    assert strip[1]["status"] == "reported" and strip[1]["sources"][0]["url"] == fakes.URL_WATER
    assert strip[2]["sources"] == []
    # The strip is drafted after the sections, from their summaries.
    names = [n for n, _ in svc.draft_provider.calls]
    assert names[-1] == "draft_at_your_house"
    house_messages = svc.draft_provider.calls[-1][1]
    assert "Two data-center campuses" in house_messages[1]["content"]
    assert brief["card"]["title"] == "Who's on my grid: Ashburn, VA"
    assert len(brief["card"]["lines"]) == 4 and "example.org" in brief["card"]["footer"]
    # Cached on disk, and the address is not in the file name.
    files = list(svc.cache.dir.glob("*.json"))
    assert len(files) == 1 and files[0].stem == brief["brief_id"]


async def test_failed_section_is_unavailable(tmp_path) -> None:
    responses = fakes.drafts()
    responses["draft_hearing"] = LLMError("boom")
    svc = fakes.service(tmp_path, draft_responses=responses)
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    hearing = brief["sections"]["hearing"]
    assert (
        hearing["status"] == "unavailable"
        and hearing["gap"]
        and hearing["hearing"] == {"next_date": None, "body": None}
    )
    assert brief["sections"]["your_bill"]["status"] == "reported"
    # Two attempts were made for the failed section only.
    names = [n for n, _ in svc.draft_provider.calls]
    assert names.count("draft_hearing") == 2 and names.count("draft_your_bill") == 1


async def test_invalid_draft_is_retried_then_unavailable(tmp_path) -> None:
    responses = fakes.drafts()
    responses["draft_protection"] = {
        "confidence": 2,
        "summary": "",
        "gap": None,
        "card_line": None,
        "tariff": {},
        "claims": [],
    }
    svc = fakes.service(tmp_path, draft_responses=responses)
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    assert brief["sections"]["protection"]["status"] == "unavailable"
    assert brief["sections"]["protection"]["tariff"]["large_load_tariff"] == "unknown"


async def test_all_sections_failed_raises(tmp_path) -> None:
    svc = fakes.service(tmp_path, draft_responses={})
    with pytest.raises(DraftingUnavailable):
        await svc.brief_for_address("x")
    assert not list(svc.cache.dir.glob("*.json"))


async def test_verifier_error_is_unverifiable(tmp_path) -> None:
    svc = fakes.service(tmp_path, verify_responses={"verdict": LLMError("down")})
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    fetched = [c for c in brief["claims"] if c["source"]["url"] != fakes.URL_GONE]
    assert all(
        c["verdict"] == "unverifiable" and "unavailable" in c["verifier_note"] for c in fetched
    )


async def test_quote_not_found_is_noted(tmp_path) -> None:
    responses = fakes.drafts()
    responses["draft_your_bill"]["claims"][0]["quote"] = "this text is not on the page at all"
    svc = fakes.service(tmp_path, draft_responses=responses)
    brief = await svc.brief_for_address("x")
    c = next(c for c in brief["claims"] if c["source"]["url"] == fakes.URL_EIA)
    assert "not found verbatim" in c["verifier_note"]


async def test_headline_without_price_uses_facilities(tmp_path) -> None:
    responses = fakes.drafts()
    responses["draft_your_bill"] = LLMError("no")
    svc = fakes.service(tmp_path, draft_responses=responses)
    brief = await svc.brief_for_address("x")
    h = brief["headline"]
    assert h["ai_rent_usd_per_month"] is None and h["band"] == "medium"
    assert "$" not in h["one_liner"]


async def test_house_draft_failure_leaves_bill_sentence(tmp_path) -> None:
    responses = fakes.drafts()
    responses["draft_at_your_house"] = LLMError("no")
    svc = fakes.service(tmp_path, draft_responses=responses)
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    assert [line["topic"] for line in brief["at_your_house"]] == ["bill"]
    assert all(c["section"] != "at_your_house" for c in brief["claims"])


async def test_no_price_means_no_bill_sentence(tmp_path) -> None:
    responses = fakes.drafts()
    responses["draft_your_bill"] = LLMError("no")
    svc = fakes.service(tmp_path, draft_responses=responses)
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    assert brief["headline"]["ai_rent_range_usd_per_month"] is None
    assert [line["topic"] for line in brief["at_your_house"]] == ["water", "noise"]


async def test_cache_hit_makes_no_model_calls(tmp_path) -> None:
    svc = fakes.service(tmp_path)
    first = await svc.brief_for_address("x")
    calls = len(svc.draft_provider.calls)
    second = await svc.brief_for_address("x")
    assert second == first and len(svc.draft_provider.calls) == calls


async def test_one_fetch_per_url(tmp_path) -> None:
    svc = fakes.service(tmp_path)
    await svc.brief_for_address("x")
    assert sorted(svc.fetcher.calls) == sorted(set(svc.fetcher.calls))
