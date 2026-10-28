"""The hearing index: quote selection, the file-backed provider, and the
transcript-aware fetcher. Every body, meeting and quote here is fictional."""

import json

from app.brief.fetch import FakeFetcher, TranscriptFetcher
from app.ground.hearings import HearingIndex, select_quotes, trim_quote

TURNS = [
    {"start_s": 100.0, "end_s": 110.0, "speaker": "A", "role": "chair", "name": None, "source": "transcribe",
     "text": "We will now take up item seven, the data center standards amendment, with the staff report first."},
    {"start_s": 400.0, "end_s": 430.0, "speaker": "B", "role": "supervisor", "name": "Supervisor Vane", "source": "transcribe",
     "text": "I am not going to approve another campus on that substation until the utility shows us the capacity study. That is the whole question for me tonight."},
    {"start_s": 900.0, "end_s": 915.0, "speaker": "C", "role": "resident", "name": None, "source": "transcribe",
     "text": "The hum from the data center starts at ten and does not stop until morning, and my kids sleep on that side of the house."},
    {"start_s": 1200.0, "end_s": 1210.0, "speaker": "D", "role": "staff", "name": None, "source": "transcribe",
     "text": "Short remark."},
    {"start_s": 1500.0, "end_s": 1530.0, "speaker": "E", "role": "supervisor", "name": None, "source": "transcribe",
     "text": "The transmission line routing is the county's concern and the data center applicant has agreed to the buffer along the substation side of the parcel."},
    {"start_s": 1600.0, "end_s": 1630.0, "speaker": "F", "role": "supervisor", "name": None, "source": "transcribe",
     "text": "I second the motion on the data center item and I want the record to show the substation condition is part of it."},
]  # fmt: skip


def test_select_quotes_prefers_relevant_turns_and_keeps_a_resident() -> None:
    quotes = select_quotes(TURNS, projects=["capacity study"], keywords=["substation"])
    assert len(quotes) == 3
    texts = [q.text for q in quotes]
    assert any("capacity study" in t for t in texts)
    assert any(q.role == "resident" for q in quotes)
    # Meeting order, verbatim text, timestamps carried.
    assert [q.start_s for q in quotes] == sorted(q.start_s for q in quotes)
    for q in quotes:
        assert any(q.text in t["text"] for t in TURNS)
    assert all(len(q.text) >= 40 for q in quotes)


def test_select_quotes_drops_short_and_irrelevant_turns() -> None:
    quotes = select_quotes([TURNS[3]], projects=[], keywords=[])
    assert quotes == []


def test_trim_quote_cuts_at_a_sentence_and_stays_verbatim() -> None:
    long = "First sentence about the data center is here. " * 8
    out = trim_quote(long, limit=120)
    assert out in long and out.endswith(".") and len(out) <= 120


def write_index(tmp_path, *, with_transcript=True, transcribe=True):
    body = {
        "id": "example-board",
        "name": "Example County Board of Supervisors",
        "state": "VA",
        "counties": ["Example"],
        "archive": {"kind": "granicus", "site": "example", "view_id": 1},
        "meetings": [
            {
                "id": "2026-10-14-77",
                "date": "2026-10-14",
                "clip_id": 77,
                "page_url": "https://example.granicus.com/player/clip/77?view_id=1",
                "subject": "Broad Run Technology Park rezoning",
                "projects": ["Broad Run"],
                "keywords": ["capacity study"],
                "windows": [{"item": "7", "start_s": 0, "end_s": 1800}],
            }
        ],
        "decisions": [
            {
                "project": "Project Kestrel",
                "codename": "Project Kestrel",
                "operator": "Orrin Cloud",
                "status": "rejected",
                "date": "2025-08-06",
                "text": "The Example County Board voted 5-0 on 2025-08-06 to deny the Project Kestrel rezoning.",
                "source_url": "https://example.org/example/minutes/2025-08-06",
                "source_title": "Example County Board minutes, 6 August 2025",
                "quote": "motion to deny carried 5-0",
                "lat": 39.05,
                "lon": -77.50,
            }
        ],
        "upcoming": [
            {"date": "2026-11-12", "subject": "Broad Run vote", "url": "https://example.org/agenda"}
        ],
    }
    (tmp_path / "sources.json").write_text(json.dumps({"bodies": [body]}), "utf-8")
    if with_transcript:
        d = tmp_path / "example-board"
        d.mkdir()
        (d / "2026-10-14-77.json").write_text(
            json.dumps(
                {
                    "meeting_id": "2026-10-14-77",
                    "models": {
                        "transcribe": "muse-voice-transcribe-1.0" if transcribe else None,
                        "roles": "muse-spark-1.3",
                    },
                    "captions": True,
                    "agreement": 0.9,
                    "coverage": "item 7, 30 min",
                    "turns": [
                        dict(t, source="transcribe" if transcribe else "captions") for t in TURNS
                    ],
                }
            ),
            "utf-8",
        )
    return HearingIndex(tmp_path)


def test_index_finds_the_meeting_for_the_county_and_quotes_it(tmp_path) -> None:
    idx = write_index(tmp_path)
    r = idx.for_place("VA", "Example")
    assert r is not None
    assert r.body == "Example County Board of Supervisors" and r.date == "2026-10-14"
    assert r.model == "muse-voice-transcribe-1.0" and r.agreement == 0.9
    assert r.upcoming is not None and r.upcoming.date == "2026-11-12"
    assert len(r.quotes) == 3 and r.coverage == "item 7, 30 min"
    # Other county, other state: nothing.
    assert idx.for_place("VA", "Other") is None
    assert idx.for_place("MD", "Example") is None
    # Decisions come with the county.
    d = idx.decisions_for("VA", "Example")
    assert len(d) == 1 and d[0].status == "rejected" and d[0].lat == 39.05


def test_index_without_transcript_has_decisions_but_no_hearing(tmp_path) -> None:
    idx = write_index(tmp_path, with_transcript=False)
    assert idx.for_place("VA", "Example") is None
    assert "no meeting has been transcribed yet" in (idx.coverage_note("VA", "Example") or "")
    assert len(idx.decisions_for("VA", "Example")) == 1


def test_captions_only_transcript_has_no_model(tmp_path) -> None:
    idx = write_index(tmp_path, transcribe=False)
    r = idx.for_place("VA", "Example")
    assert r is not None and r.model is None


async def test_transcript_fetcher_serves_the_transcript_for_the_archive_page(tmp_path) -> None:
    idx = write_index(tmp_path)
    inner = FakeFetcher({"https://example.org/other": "Other page text. " * 20})
    f = TranscriptFetcher(inner, idx)
    page = await f.fetch("https://example.granicus.com/player/clip/77?view_id=1")
    assert page.ok and "capacity study" in page.text and page.note == TranscriptFetcher.NOTE
    assert "[0:06:40]" in page.text
    other = await f.fetch("https://example.org/other")
    assert other.ok and other.note == "" and inner.calls == ["https://example.org/other"]


def test_trim_quote_drops_leading_procedure_run_in_by_captions() -> None:
    turn = (
        "Second moved and seconded by Supervisor Christy. Discussion supervisor Kino. "
        "Thank you, Chair Scott, I do want to just preview that my comments in relation to "
        "this binding memorandum of agreement are a bit extensive, but I'll do my best to "
        "make it quick. I want to acknowledge the two groups who joined us today."
    )
    q = trim_quote(turn)
    assert q.startswith("I want to acknowledge") or q.startswith("Thank you, Chair Scott")
    assert q in turn
    assert "Second moved" not in q


def test_trim_quote_keeps_procedure_when_nothing_else_follows() -> None:
    turn = "So moved. The motion carries and the agreement is approved."
    assert trim_quote(turn) == turn


def test_trim_quote_drops_a_leading_fragment() -> None:
    text = "appearing in my front yard. That's the consequence of building too many data centers."
    assert trim_quote(text) == "That's the consequence of building too many data centers."
    # Nothing to drop when the turn starts at a sentence.
    assert trim_quote("We will not approve it. Period.") == "We will not approve it. Period."


def test_unusable_transcript_is_skipped_but_its_index_is_served(tmp_path) -> None:
    idx = write_index(tmp_path)
    path = tmp_path / "example-board" / "2026-10-14-77.json"
    data = json.loads(path.read_text("utf-8"))
    data["usable"] = False
    data["index_points"] = [{"time_s": 400.0, "title": "Vote to Approve Item 7 (Approved)"}]
    path.write_text(json.dumps(data), "utf-8")
    assert idx.for_place("VA", "Example") is None
    assert "captions are unreadable" in (idx.coverage_note("VA", "Example") or "")
    assert idx.coverage_note("VA", "Other") is None
    text = idx.transcript_text("https://example.granicus.com/player/clip/77?view_id=1")
    assert text and "Vote to Approve Item 7" in text and "capacity study" not in text
