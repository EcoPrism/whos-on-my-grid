"""'Data centre' scores like 'data center' (plan 0.10), and the indexed US
transcripts score exactly as they did before the two terms were added."""

import json

import pytest

from app.ground import US_DATA_DIR, Decision
from app.ground import hearings as h
from app.ground.hearings import HearingIndex, score_turn

LONG = " The council heard from residents about the proposal at length this evening."


def turn(text: str, role: str = "resident") -> dict:
    return {"text": text + LONG, "role": role, "start_s": 0.0, "source": "transcribe"}


def test_centres_score_as_centers() -> None:
    us = score_turn(turn("Two more data centers are planned near the school."), [], [])
    ie = score_turn(turn("Two more data centres are planned near the school."), [], [])
    assert us == ie > 0
    one_us = score_turn(turn("A data center is planned near the school."), [], [])
    one_ie = score_turn(turn("A data centre is planned near the school."), [], [])
    assert one_us == one_ie > 0


def _us_turns() -> list[dict]:
    turns: list[dict] = []
    for path in sorted((US_DATA_DIR / "hearings").glob("*/*.json")):
        turns.extend(json.loads(path.read_text(encoding="utf-8")).get("turns") or [])
    return turns


def test_us_transcripts_have_no_centre_spelling() -> None:
    turns = _us_turns()
    assert turns
    assert not any("centre" in t["text"].lower() for t in turns)


def test_us_transcript_scores_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = _us_turns()
    now = [score_turn(t, ["Project"], ["Dominion"]) for t in turns]
    before = [x for x in h.GENERIC_TERMS if x not in ("data centre", "data centres")]
    monkeypatch.setattr(h, "GENERIC_TERMS", before)
    assert [score_turn(t, ["Project"], ["Dominion"]) for t in turns] == now


def test_all_decisions_spans_every_body(tmp_path) -> None:
    def body(i: str, county: str, n: int) -> dict:
        return {
            "id": i,
            "name": f"{county} Council",
            "state": "IE-D",
            "counties": [county],
            "meetings": [],
            "decisions": [
                {
                    "project": f"{county} {k}",
                    "date": "2026-01-01",
                    "text": "t",
                    "source_url": "https://example.org/d",
                    "source_title": "d",
                    "status": "approved",
                }
                for k in range(n)
            ],
        }

    (tmp_path / "sources.json").write_text(
        json.dumps({"bodies": [body("a", "Fingal", 0), body("b", "South Dublin", 2)]}),
        encoding="utf-8",
    )
    index = HearingIndex(tmp_path)
    found = index.all_decisions()
    assert [d.project for d in found] == ["South Dublin 0", "South Dublin 1"]
    assert all(isinstance(d, Decision) and d.body == "South Dublin Council" for d in found)
    assert index.decisions_for("IE-D", "Fingal") == []
    assert HearingIndex(tmp_path / "absent").all_decisions() == []
