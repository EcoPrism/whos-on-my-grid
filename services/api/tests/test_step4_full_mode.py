"""Full mode with the step-4 indexes: Coming measured from imagery, Hearing
measured from a transcript, decisions on the record, and the gaps when an
address is outside both indexes. Everything here is fictional."""

from app.brief.fetch import FakeFetcher, TranscriptFetcher
from app.ground import (
    ConstructionSite,
    Decision,
    FakeHearingIndex,
    FakeImageryIndex,
    HearingQuote,
    HearingResult,
    ImageryItem,
    ImageryResult,
    ImageryVintage,
    Upcoming,
)
from app.schema import validate_brief
from tests import fakes
from tests.test_full_mode import ground

URL_THEN = "https://example.org/stac/naip/items/va_m_2023"
URL_NOW = "https://example.org/fpac/query?name=m_2025"
URL_PAGE = "https://example.granicus.com/player/clip/77?view_id=1"
URL_VOTE = "https://example.org/example/minutes/2025-08-06"

IMAGERY = ImageryResult(
    area_id="ashburn",
    area_name="Ashburn, VA",
    model="sam-3.1",
    then=ImageryVintage(2023, "USDA NAIP via Planetary Computer", (ImageryItem("va_m_2023", "2023-10-11", URL_THEN, "NAIP item va_m_2023"),)),
    now=ImageryVintage(2025, "USDA NAIP via USDA FPAC", (ImageryItem("m_2025", "2025-08-10", URL_NOW, "NAIP 2025 m_2025"),)),
    sites=(
        ConstructionSite("s1", "Northgate Campus DC1-DC9 expansion", "expansion", 39.02, -77.456, 0.4, 41.0, 58.4, True, True, "Northgate Campus DC1-DC9", ((39.02, -77.457), (39.02, -77.452), (39.017, -77.452), (39.017, -77.457))),
        ConstructionSite("s2", "New large roof, 1.4 mi north (unlisted)", "new", 39.03, -77.48, 2.3, 0.0, 23.1, False, True, None, ((39.031, -77.482), (39.031, -77.478), (39.028, -77.478), (39.028, -77.482))),
        ConstructionSite("s3", "Large roof, 3.9 mi east", "new", 39.01, -77.40, 6.2, 0.0, 9.0, False, False, None, ((39.011, -77.401), (39.011, -77.399), (39.009, -77.399), (39.009, -77.401))),
    ),
    indexed_at="2026-10-28T00:00:00Z",
)  # fmt: skip

HEARING = HearingResult(
    body_id="example-board",
    body="Example County Board of Supervisors",
    meeting_id="2026-10-14-77",
    date="2026-10-14",
    subject="Broad Run Technology Park rezoning",
    page_url=URL_PAGE,
    page_title="Example County Board of Supervisors meeting archive, 2026-10-14",
    quotes=(
        HearingQuote("We are not going to approve another campus on that substation until the utility shows us the capacity study.", 4812.0, "supervisor", None, "transcribe"),
        HearingQuote("The hum from the data center starts at ten and does not stop until morning.", 5330.5, "resident", None, "transcribe"),
    ),
    model="muse-voice-transcribe-1.0",
    agreement=0.9,
    upcoming=Upcoming("2099-11-12", "Broad Run vote", "https://example.org/agenda"),
    coverage="item 7, 30 min",
)  # fmt: skip
TRANSCRIPT = (
    "Transcript. [1:20:12] supervisor: We are not going to approve another campus on that substation until the utility shows us the capacity study. [1:28:50] resident: The hum from the data center starts at ten and does not stop until morning. "
    * 3
)

DECISION = Decision(
    project="Project Kestrel",
    codename="Project Kestrel",
    operator="Orrin Cloud",
    status="rejected",
    date="2025-08-06",
    body="Example County Board of Supervisors",
    text="The Example County Board voted 5-0 on 2025-08-06 to deny the Project Kestrel rezoning.",
    source_url=URL_VOTE,
    source_title="Example County Board minutes, 6 August 2025",
    quote="motion to deny carried 5-0",
    lat=39.05,
    lon=-77.50,
)
PAGES = {
    **fakes.PAGES,
    URL_THEN: '{"id": "va_m_2023", "properties": {"datetime": "2023-10-11"}} ' * 20,
    URL_NOW: '{"features": [{"attributes": {"Name": "m_2025", "QQDATE": "2025-08-10"}}]} ' * 20,
    URL_VOTE: "Minutes. Item 9, Project Kestrel rezoning: motion to deny carried 5-0. " * 10,
}


def service(tmp_path, **over):
    hearings = FakeHearingIndex(HEARING, [DECISION], TRANSCRIPT)
    svc = fakes.service(tmp_path, brief_source="full", pages=PAGES)
    svc.ground = ground(imagery=FakeImageryIndex(IMAGERY), hearings=hearings, **over)
    svc.fetcher = TranscriptFetcher(svc.fetcher, hearings)
    return svc


async def test_coming_is_measured_from_imagery_and_the_record(tmp_path) -> None:
    svc = service(tmp_path)
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    coming = brief["sections"]["coming"]
    assert coming["status"] == "measured" and coming["model"] == "sam-3.1"
    labels = [c["label"] for c in coming["construction"]]
    assert labels == [
        "Northgate Campus DC1-DC9 expansion",
        "New large roof, 1.4 mi north (unlisted)",
        "Large roof, 3.9 mi east",
    ]
    assert coming["construction"][0]["kind"] == "expansion"
    assert coming["construction"][0]["vintages"] == [2023, 2025]
    assert (
        coming["construction"][1]["near_cluster"] is True
        and coming["construction"][2]["near_cluster"] is False
    )
    assert "40 acres" in coming["summary"] and "1 other large roof" in coming["summary"]
    # The vote on the record is a rejected entry with its own claim, ahead of the model's.
    names = [(f["name"], f["status"]) for f in coming["facilities"]]
    assert names[0] == ("Project Kestrel", "rejected")
    assert ("Waxpool North", "announced") in names
    urls = {c["source"]["url"] for c in brief["claims"] if c["section"] == "coming"}
    assert {URL_THEN, URL_NOW, URL_VOTE} <= urls
    by_url = {c["source"]["url"]: c for c in brief["claims"]}
    assert by_url[URL_VOTE]["verdict"] == "supported" and by_url[URL_VOTE]["drafted_by"] == "engine"
    assert "acres of new data-center roof since 2023" in " ".join(brief["card"]["lines"])
    # The strip has the engine's land line, and the model's land line is dropped.
    land = [ln for ln in brief["at_your_house"] if ln["topic"] == "land"]
    assert (
        len(land) == 1 and land[0]["status"] == "measured" and "football fields" in land[0]["text"]
    )


async def test_hearing_is_measured_from_the_transcript(tmp_path) -> None:
    svc = service(tmp_path)
    brief = await svc.brief_for_address("x")
    hearing = brief["sections"]["hearing"]
    assert hearing["status"] == "measured" and hearing["model"] == "muse-voice-transcribe-1.0"
    h = hearing["hearing"]
    assert h["body"] == "Example County Board of Supervisors" and h["next_date"] == "2099-11-12"
    assert h["last_meeting_date"] == "2026-10-14"
    assert [s["speaker_role"] for s in h["last_meeting_said"]] == ["supervisor", "resident"]
    assert h["last_meeting_said"][0]["timestamp_s"] == 4812.0
    assert hearing["summary"].startswith(
        "At the Example County Board of Supervisors meeting on 14 October 2026"
    )
    assert "Broad Run vote" in hearing["summary"]
    assert hearing["confidence"] == 0.87 and "item 7, 30 min" in hearing["gap"]
    # No Spark draft for the hearing section; its claims cite the archive page and were
    # checked against the transcript.
    names = [n for n, _ in svc.draft_provider.calls]
    assert "draft_hearing" not in names and "draft_coming" in names
    claims = [c for c in brief["claims"] if c["section"] == "hearing"]
    assert len(claims) == 2 and all(c["source"]["url"] == URL_PAGE for c in claims)
    assert all(c["verdict"] == "supported" for c in claims)
    assert "transcript of the official recording" in claims[0]["verifier_note"]


async def test_outside_both_indexes_the_sections_say_so(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = ground(imagery=FakeImageryIndex(None), hearings=FakeHearingIndex(None))
    brief = await svc.brief_for_address("x")
    validate_brief(brief)
    coming = brief["sections"]["coming"]
    assert coming["status"] == "reported" and coming["construction"] == []
    assert "has not been indexed for Loudoun County" in coming["gap"]
    hearing = brief["sections"]["hearing"]
    assert hearing["status"] == "reported" and "not indexed yet" in hearing["gap"]
    names = [n for n, _ in svc.draft_provider.calls]
    assert "draft_hearing" in names
    assert not [
        ln for ln in brief["at_your_house"] if ln["topic"] == "land" and ln["status"] == "measured"
    ]


async def test_ground_block_tells_spark_what_the_engine_measured(tmp_path) -> None:
    svc = service(tmp_path)
    await svc.brief_for_address("x")
    coming_prompt = next(m for n, m in svc.draft_provider.calls if n == "draft_coming")[1][
        "content"
    ]
    assert "SAM 3.1 on USDA NAIP 2023 vs 2025" in coming_prompt
    assert "Project Kestrel" in coming_prompt and "never present it as coming" in coming_prompt
    assert "the engine fills it from the imagery measurement" in coming_prompt
    assert "aerial imagery is not available" not in coming_prompt


async def test_fake_fetcher_still_serves_ordinary_pages(tmp_path) -> None:
    inner = FakeFetcher({"https://example.org/a": "A page. " * 40})
    f = TranscriptFetcher(inner, FakeHearingIndex(None))
    assert (await f.fetch("https://example.org/a")).ok
