"""The what-if interpretation: three sentences from the drafting model around
the engine's numbers. Claims citing a page the scenario does not cite are
dropped, a paragraph with a figure of the model's own is refused, the result
is `reported` and stored with its verified claims, and a second call is free.
Fake providers and fictional pages throughout."""

import json

import pytest

from app.brief.draft import DraftResult, SectionFailure
from app.llm.fake_provider import KeyedFakeProvider
from app.scenario.inputs import ScenarioInputs
from app.scenario.interpret import (
    draft_interpretation,
    facts_block,
    foreign_numbers,
    scenario_sources,
)
from app.scenario.pipeline import InterpretFailed, InterpretUnavailable, ScenarioNotFound
from app.schema import scenario_errors
from tests import scenario_fakes

INPUTS = ScenarioInputs.create(zip="20147", mw=300, cooling="evaporative", pin=None)


async def _scenario(svc) -> dict:
    return await svc.compute(await svc.resolve(INPUTS))


async def test_claims_off_the_scenario_pages_are_dropped(tmp_path) -> None:
    scenario = await _scenario(scenario_fakes.service(tmp_path))
    provider = KeyedFakeProvider(scenario_fakes.interpretation())
    result = await draft_interpretation(provider, scenario)
    assert isinstance(result, DraftResult)
    urls = [c["source_url"] for c in result.claims]
    assert urls == [
        scenario_fakes.url("us_home_kwh_per_year"),
        scenario_fakes.url("dc_load_factor"),
    ]
    assert result.extra["dropped"] == 1
    # The page's own title and curated quote, not the model's.
    assert result.claims[0]["source_title"] == "Fictional source for us_home_kwh_per_year"
    assert result.claims[0]["quote"] == "average of 10,791 kilowatthours"


async def test_a_wrong_quote_or_a_new_figure_in_a_claim_is_dropped(tmp_path) -> None:
    scenario = await _scenario(scenario_fakes.service(tmp_path))
    base = scenario_fakes.interpretation()["draft_scenario"]["claims"][0]
    claims = [
        {**base, "quote": "a quote the page does not carry at all"},
        {**base, "text": "A typical home uses 12,345 kilowatthours a year."},
        {**base, "quote": ""},
    ]
    provider = KeyedFakeProvider(scenario_fakes.interpretation(claims=claims))
    result = await draft_interpretation(provider, scenario)
    assert isinstance(result, DraftResult) and result.claims == []


async def test_a_figure_the_engine_did_not_give_is_refused(tmp_path) -> None:
    scenario = await _scenario(scenario_fakes.service(tmp_path))
    bad = "This is hypothetical. It would use as much power as 250,000 homes. That is a lot."
    provider = KeyedFakeProvider(scenario_fakes.interpretation(summary=bad))
    result = await draft_interpretation(provider, scenario)
    assert isinstance(result, SectionFailure)
    assert "engine's figures" in result.reason
    assert len(provider.calls) == 2  # one retry, then give up


async def test_the_zip_never_reaches_the_model(tmp_path) -> None:
    scenario = await _scenario(scenario_fakes.service(tmp_path))
    sources = scenario_sources(scenario)
    assert not any("20147" in u for u in sources)
    assert "20147" not in facts_block(scenario, sources)
    provider = KeyedFakeProvider(scenario_fakes.interpretation())
    await draft_interpretation(provider, scenario)
    assert "20147" not in json.dumps(provider.calls)


async def test_interpret_stores_a_reported_paragraph_once(tmp_path) -> None:
    svc = scenario_fakes.service(tmp_path, draft=scenario_fakes.interpretation())
    scenario = await _scenario(svc)
    sid, before = scenario["scenario_id"], len(scenario["claims"])
    events: list[dict] = []

    done = await svc.interpret(sid, events.append)
    interp = done["interpretation"]
    assert interp["status"] == "reported" and interp["model"] == "muse-spark-1.3"
    assert interp["text"].startswith("This is a hypothetical")
    assert interp["draft"] is False  # both kept claims were supported
    added = done["claims"][before:]
    assert [c["section"] for c in added] == ["scenario", "scenario"]
    assert all(c["verdict"] == "supported" and c["source"]["quote"] for c in added)
    assert len({c["id"] for c in done["claims"]}) == len(done["claims"])
    assert scenario_errors(done) == []
    assert [e["stage"] for e in events] == ["drafting", "verifying", "verifying", "verifying"]
    assert events[-1] == {"stage": "verifying", "verified": 2, "claims": 2}

    # Stored, and a second call neither drafts nor changes anything.
    assert svc.cache.get(sid)["interpretation"] == interp
    calls = len(svc.draft_provider.calls)
    again = await svc.interpret(sid)
    assert again == svc.cache.get(sid) and len(svc.draft_provider.calls) == calls


async def test_interpret_without_verifier_is_a_draft(tmp_path) -> None:
    svc = scenario_fakes.service(tmp_path, verify=False, draft=scenario_fakes.interpretation())
    sid = (await _scenario(svc))["scenario_id"]
    done = await svc.interpret(sid)
    assert done["interpretation"]["draft"] is True
    assert {c["verdict"] for c in done["claims"]} == {"unchecked"}


async def test_interpret_errors(tmp_path) -> None:
    svc = scenario_fakes.service(tmp_path)
    with pytest.raises(ScenarioNotFound):
        await svc.interpret("0123456789abcdef")
    sid = (await _scenario(svc))["scenario_id"]
    with pytest.raises(InterpretUnavailable):
        await svc.interpret(sid)

    failing = scenario_fakes.service(tmp_path, draft={})
    with pytest.raises(InterpretFailed):
        await failing.interpret(sid)
    assert failing.cache.get(sid)["interpretation"] is None


FACTS = (
    "FACTS\nData centers already within 5 miles: 2.\n"
    "- 300 MW, as much as 194,829 homes. Working: 1.5 miles\n"
    '[S1] Table 99 | https://www.peeringdb.com/fac/8765 | quote: "campuses run at 80 percent"'
)


@pytest.mark.parametrize(
    "text",
    [
        "Bills could rise about $5 a month.",  # 5 is in the facts, but as miles
        "Bills could rise 10%.",
        "It would use two million gallons a day.",
        "Power for 8,765 homes.",  # only in a source URL
        "Enough for 1.5 million households.",  # 1.5 is miles, not millions
        "Table 99 says so.",  # only in a source title
        "It could double demand.",
        "About half the homes nearby.",
    ],
)
def test_a_figure_in_words_units_or_urls_is_foreign(text) -> None:
    assert foreign_numbers(text, FACTS), text


@pytest.mark.parametrize(
    "text",
    [
        "At 300 MW it would use as much as 194,829 homes.",
        "Two data centers are listed within five miles.",
        "Three sentences about two campuses.",
        "Campuses run at 80 percent of capacity.",
    ],
)
def test_the_engines_figures_and_bare_counts_pass(text) -> None:
    assert foreign_numbers(text, FACTS) == set(), text


async def test_a_page_without_a_curated_quote_cannot_be_cited(tmp_path) -> None:
    svc = scenario_fakes.service(tmp_path, tariff_entry=scenario_fakes.tariff())
    scenario = await _scenario(svc)
    bare = [u for u, s in scenario_sources(scenario).items() if not s["quotes"]]
    assert bare, "the tariff page carries no curated quote"
    base = scenario_fakes.interpretation()["draft_scenario"]["claims"][0]
    claim = {
        **base,
        "text": "The tariff keeps data-center costs off household bills.",
        "source_url": bare[0],
        "quote": "keeps data-center costs off household bills",
    }
    provider = KeyedFakeProvider(scenario_fakes.interpretation(claims=[claim]))
    result = await draft_interpretation(provider, scenario)
    assert isinstance(result, DraftResult) and result.claims == []
    assert bare[0] not in json.dumps(provider.calls)
