"""Granicus index parsing and captions-to-turns, on shapes copied from the
real JSON (nested list, 'meta' index points, '>>' speaker marks)."""

from app.hearings.granicus import Caption, captions_to_turns, parse_index, points_in
from app.hearings.transcribe import agreement

RAW = [
    [
        {"time": "661", "type": "meta", "text": "Agenda:1", "guid": "g", "title": "I. Call to Order &ndash; Chair <b>Randall</b>"},
        {"time": "669", "type": "text", "text": ">>> well, good evening"},
        {"time": "669.5", "type": "text", "text": "supervisors. Good evening staff"},
        {"time": "670", "type": "text", "text": "and good evening loudoun. We will take up the data center item now."},
        {"time": "690", "type": "text", "text": ">> Thank you, Madam Chair. Staff will present the amendment."},
        {"time": "693", "type": "text", "text": "It removes by-right data centers near homes."},
        {"time": "16319", "type": "meta", "text": "Agenda:7", "guid": "h", "title": "7. CPAM-2024-0001 &amp; ZOAM-2024-0001, Data Center Standards"},
    ]
]  # fmt: skip


def test_parse_index_flattens_and_cleans() -> None:
    points, captions = parse_index(RAW)
    assert [p.time_s for p in points] == [661.0, 16319.0]
    assert points[0].title == "I. Call to Order – Chair Randall"
    assert points[1].title.startswith("7. CPAM-2024-0001 & ZOAM-2024-0001")
    assert len(captions) == 5
    assert points_in(points, 600, 700) == [
        {"time_s": 661.0, "title": "I. Call to Order – Chair Randall"}
    ]


def test_captions_become_turns_split_on_speaker_marks() -> None:
    _, captions = parse_index(RAW)
    turns = captions_to_turns(captions, 0, 1000)
    assert len(turns) == 2
    assert turns[0]["text"].startswith("well, good evening supervisors.")
    assert turns[0]["text"].endswith("data center item now.")
    assert turns[0]["start_s"] == 669.0 and turns[0]["source"] == "captions"
    assert turns[1]["text"] == (
        "Thank you, Madam Chair. Staff will present the amendment. It removes by-right data "
        "centers near homes."
    )
    assert turns[1]["start_s"] == 690.0 and turns[1]["role"] == "unknown"
    # Outside the window: nothing.
    assert captions_to_turns(captions, 2000, 3000) == []


def test_apostrophes_split_across_cues_are_rejoined() -> None:
    caps = [
        Caption(10, "That'"),
        Caption(11, "s the consequence and I'"),
        Caption(12, "ve lived here for years."),
    ]
    turns = captions_to_turns(caps, 0, 100)
    assert turns[0]["text"] == "That's the consequence and I've lived here for years."


def test_long_silence_ends_a_turn() -> None:
    caps = [
        Caption(10, "first part of a sentence that keeps going on"),
        Caption(20, "and ends much later here."),
    ]
    turns = captions_to_turns(caps, 0, 100)
    assert [t["text"] for t in turns] == [
        "first part of a sentence that keeps going on",
        "and ends much later here.",
    ]


def test_agreement_is_token_f1() -> None:
    t = [{"text": "we will not approve another campus on that substation"}]
    c = [{"text": "we will not approve another campus on that substation tonight"}]
    assert agreement(t, c) == 0.947
    assert agreement(t, []) is None
    assert agreement(t, [{"text": "completely different words entirely"}]) == 0.0
