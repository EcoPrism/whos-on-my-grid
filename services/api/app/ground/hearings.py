"""What was said at the last indexed hearing for this county, read from the
hearing index: `data/regions/us/hearings/sources.json` (bodies, meetings, decisions,
upcoming dates; hand-curated like the tariff table) and one transcript file
per meeting beside it (`<body>/<meeting>.json`, written offline by
`app.hearings.index` from the official recording through Muse Voice
Transcribe, or from the archive's own closed captions where those exist).

Quotes are verbatim transcript text. The role of the speaker is the only
inferred field, and it says so in the transcript file."""

import json
import re
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.ground.types import Decision, HearingQuote, HearingResult, Upcoming

HEARINGS_DIR = REPO_ROOT / "data" / "regions" / "us" / "hearings"
TRANSCRIBE_MODEL_ID = "muse-voice-transcribe-1.0"

MAX_QUOTES = 3
MIN_QUOTE_CHARS = 80  # a procedural line ('so moved, seconded') is shorter
MAX_QUOTE_CHARS = 240
GENERIC_TERMS = [
    "data center",
    "data centers",
    "data centre",  # Irish and British spelling; no US transcript has it
    "data centres",
    "substation",
    "transmission",
    "noise",
    "power line",
]
OFFICIAL_ROLES = {"chair", "vice chair", "supervisor", "commissioner", "council member", "mayor"}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


class HearingIndex:
    def __init__(self, directory: Path = HEARINGS_DIR) -> None:
        self.dir = directory
        self._sources: dict[str, Any] | None = None
        self._transcripts: dict[str, dict[str, Any] | None] = {}

    # --- files -----------------------------------------------------------------

    def sources(self) -> dict[str, Any]:
        if self._sources is None:
            path = self.dir / "sources.json"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    self._sources = json.load(f)
            else:
                self._sources = {"bodies": []}
        return self._sources

    def bodies(self) -> list[dict[str, Any]]:
        return list(self.sources().get("bodies", []))

    def transcript(self, body_id: str, meeting_id: str) -> dict[str, Any] | None:
        key = f"{body_id}/{meeting_id}"
        if key not in self._transcripts:
            path = self.dir / body_id / f"{meeting_id}.json"
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    self._transcripts[key] = json.load(f)
            else:
                self._transcripts[key] = None
        return self._transcripts[key]

    # --- lookup ----------------------------------------------------------------

    def bodies_for(self, state: str, county: str | None) -> list[dict[str, Any]]:
        c = _norm(county)
        if not c:
            return []
        return [
            b
            for b in self.bodies()
            if b.get("state", "").upper() == state.upper()
            and any(_norm(x) == c for x in b.get("counties", []))
        ]

    def decisions_for(self, state: str, county: str | None) -> list[Decision]:
        return [d for b in self.bodies_for(state, county) for d in _decisions(b)]

    def all_decisions(self) -> list[Decision]:
        """Every body's decisions, for a region that matches them by distance
        (Ground.decisions_scope == "radius") rather than by the address's authority."""
        return [d for b in self.bodies() for d in _decisions(b)]

    def for_place(
        self, state: str, county: str | None, utility: str | None = None
    ) -> HearingResult | None:
        """The most recent indexed meeting with a transcript for a body that
        covers this county, with its best quotes. None when nothing is indexed."""
        candidates: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for b in self.bodies_for(state, county):
            for m in b.get("meetings", []):
                t = self.transcript(b["id"], m["id"])
                if t and t.get("turns") and t.get("usable", True):
                    candidates.append((m["date"], b, m, t))
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[0], reverse=True)
        _, body, meeting, transcript = candidates[0]
        quotes = select_quotes(
            transcript["turns"],
            projects=meeting.get("projects", []),
            keywords=[*meeting.get("keywords", []), *([utility] if utility else [])],
        )
        if not quotes:
            return None
        models = transcript.get("models") or {}
        from_transcribe = any(q.source == "transcribe" for q in quotes)
        upcoming = _next_upcoming(body.get("upcoming", []))
        return HearingResult(
            body_id=body["id"],
            body=body["name"],
            meeting_id=meeting["id"],
            date=meeting["date"],
            subject=meeting.get("subject", ""),
            page_url=meeting["page_url"],
            page_title=f"{body['name']} meeting archive, {meeting['date']}",
            quotes=tuple(quotes),
            model=(models.get("transcribe") or TRANSCRIBE_MODEL_ID) if from_transcribe else None,
            agreement=transcript.get("agreement"),
            upcoming=upcoming,
            coverage=transcript.get("coverage") or "",
        )

    def coverage_note(self, state: str, county: str | None) -> str | None:
        """Why an indexed county has no transcript to quote: nothing indexed
        yet, or a recording whose captions were unreadable and awaits the
        audio pass. None when the county is not in the index at all."""
        bodies = self.bodies_for(state, county)
        if not bodies:
            return None
        unusable = False
        for b in bodies:
            for m in b.get("meetings", []):
                t = self.transcript(b["id"], m["id"])
                if t and not t.get("usable", True):
                    unusable = True
        names = ", ".join(b["name"] for b in bodies)
        if unusable:
            return (
                f"{names}: the recording is in the index but the archive's captions are "
                "unreadable, so no quote is shown until it is transcribed from audio."
            )
        return f"{names} is in the index but no meeting has been transcribed yet."

    def transcript_text(self, url: str) -> str | None:
        """The transcript behind an archive page URL, for the verifier: one
        line per turn with its time and role. None for any other URL."""
        for b in self.bodies():
            for m in b.get("meetings", []):
                if m.get("page_url") != url:
                    continue
                t = self.transcript(b["id"], m["id"])
                if not t:
                    return None
                by = (t.get("models") or {}).get("transcribe")
                how = "Muse Voice Transcribe" if by else "the archive's closed captions"
                lines = [
                    f"{b['name']}, {m['date']}: {m.get('subject', '')}. Transcript of the "
                    f"official recording ({how})."
                ]
                for p in t.get("index_points", []):
                    lines.append(f"[{_hms(p['time_s'])}] Agenda index: {p['title']}")
                if not t.get("usable", True):
                    # Garbled captions: the agenda index is the record, not the words.
                    return "\n".join(lines)
                for turn in t.get("turns", []):
                    who = turn.get("name") or turn.get("role") or "speaker"
                    lines.append(f"[{_hms(turn['start_s'])}] {who}: {turn['text']}")
                return "\n".join(lines)
        return None


def _hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _next_upcoming(items: list[dict[str, Any]]) -> Upcoming | None:
    """The soonest listed date. Dates are compared as strings (ISO); the
    assembler decides whether a past one is still worth showing."""
    items = sorted(items, key=lambda u: u["date"])
    return Upcoming(items[0]["date"], items[0]["subject"], items[0]["url"]) if items else None


# --- quote selection (pure) -------------------------------------------------------


def score_turn(turn: dict[str, Any], projects: list[str], keywords: list[str]) -> float:
    text = turn["text"].lower()
    score = 0.0
    for p in projects:
        if p and p.lower() in text:
            score += 3
    for k in keywords:
        if k and k.lower() in text:
            score += 1
    for g in GENERIC_TERMS:
        if g in text:
            score += 1
    role = (turn.get("role") or "unknown").lower()
    if role in OFFICIAL_ROLES or role == "resident":
        score += 0.5
    if role != "unknown":
        score += 0.5  # a voice the brief can name beats one it cannot
    if turn.get("source") == "transcribe":
        score += 0.25
    n = len(turn["text"])
    if n < MIN_QUOTE_CHARS:
        return 0.0
    if n > 600:
        score -= 0.5
    return score


_FRAGMENT = re.compile(r"^[^.!?]*[.!?]\s+(?=[A-Z])")
# Procedure at the top of a turn: a caption stream often runs the chair's
# motion handling into the next speaker's words. These sentences are dropped
# from the front of a quote when enough speech follows them.
_PROCEDURAL = re.compile(
    r"^(so moved|second(ed)?\b|moved and seconded|motion\b|discussion\b|roll call|all in favor"
    r"|any opposed|the motion (carries|passes|fails)|thank you,? (chair|mr\.?|madam|mayor)"
    r"|supervisor [a-z]+\.$|next (speaker|item))",
    re.IGNORECASE,
)
_SHORT_OPENER = 40


def trim_quote(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    """The first whole sentences that fit, so the quote is still a verbatim
    substring. A turn cut from a caption stream can start mid-sentence; that
    opening fragment is dropped when a sentence start follows."""
    text = text.strip()
    if text[:1].islower():
        text = _FRAGMENT.sub("", text, count=1)
    text = _drop_procedure(text)
    if len(text) <= limit:
        return text
    out = ""
    for sentence in _SENTENCE_END.split(text):
        candidate = f"{out} {sentence}".strip()
        if len(candidate) > limit:
            break
        out = candidate
    if len(out) >= MIN_QUOTE_CHARS:
        return out
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut


def _drop_procedure(text: str) -> str:
    """Strip leading procedural or very short sentences while what remains is
    still a quotable length. The result is a suffix of the input, so the
    quote stays a verbatim substring of the turn."""
    sentences = _SENTENCE_END.split(text)
    while len(sentences) > 1:
        head = sentences[0]
        rest = " ".join(sentences[1:])
        if len(rest) < MIN_QUOTE_CHARS:
            break
        if _PROCEDURAL.match(head) or len(head) < _SHORT_OPENER:
            sentences = sentences[1:]
            continue
        break
    return " ".join(sentences)


def select_quotes(
    turns: list[dict[str, Any]],
    *,
    projects: list[str],
    keywords: list[str],
    limit: int = MAX_QUOTES,
) -> list[HearingQuote]:
    """The best few turns by keyword relevance. When the top picks are all
    officials and a resident spoke to the point (or the reverse), the last
    slot goes to that other voice. Returned in meeting order."""
    scored = [(score_turn(t, projects, keywords), i, t) for i, t in enumerate(turns)]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: (-s[0], s[1]))
    picked = [(i, t) for _, i, t in scored[:limit]]

    def role(t: dict[str, Any]) -> str:
        return (t.get("role") or "unknown").lower()

    if len(picked) == limit:
        has_official = any(role(t) in OFFICIAL_ROLES for _, t in picked)
        has_resident = any(role(t) == "resident" for _, t in picked)
        missing = None
        if not has_resident:
            missing = "resident"
        elif not has_official:
            missing = "official"
        if missing:
            pool = [
                (i, t)
                for _, i, t in scored[limit:]
                if (role(t) == "resident" if missing == "resident" else role(t) in OFFICIAL_ROLES)
            ]
            if pool:
                picked[-1] = pool[0]
    picked.sort(key=lambda p: p[0])
    return [
        HearingQuote(
            text=trim_quote(t["text"]),
            start_s=float(t["start_s"]),
            role=(t.get("role") or "unknown"),
            name=t.get("name"),
            source=t.get("source", "transcribe"),
        )
        for _, t in picked
    ]


# A campus voted on within 15 miles is this address's news (assemble's Coming
# list and, under the radius scope, gather_ground's filter both use it).
DECISION_RADIUS_KM = 25.0


def _decisions(b: dict[str, Any]) -> list[Decision]:
    return [
        Decision(
            project=d["project"],
            codename=d.get("codename"),
            operator=d.get("operator"),
            status=d.get("status", "rejected"),
            date=d["date"],
            body=b["name"],
            text=d["text"],
            source_url=d["source_url"],
            source_title=d["source_title"],
            quote=d.get("quote", ""),
            lat=d.get("lat"),
            lon=d.get("lon"),
            estimated_mw=d.get("estimated_mw"),
            decided_by=d.get("decided_by") or None,
        )
        for d in b.get("decisions", [])
    ]


class FakeHearingIndex:
    def __init__(
        self,
        result: HearingResult | None = None,
        decisions: list[Decision] | None = None,
        transcript: str | None = None,
        note: str | None = None,
    ) -> None:
        self.result = result
        self.note = note
        self.decisions = decisions or []
        self.transcript = transcript
        self.calls = 0

    def for_place(
        self, state: str, county: str | None, utility: str | None = None
    ) -> HearingResult | None:
        self.calls += 1
        return self.result

    def decisions_for(self, state: str, county: str | None) -> list[Decision]:
        return list(self.decisions)

    def all_decisions(self) -> list[Decision]:
        return list(self.decisions)

    def coverage_note(self, state: str, county: str | None) -> str | None:
        return self.note

    def transcript_text(self, url: str) -> str | None:
        if self.result is not None and url == self.result.page_url:
            return self.transcript
        return None
