"""Turn five drafts (or failures) into one Brief JSON. Every section in agent
mode is `reported` or `unavailable`; claims start `unchecked` and the
verifier fills them in afterwards."""

from typing import Any

from app.brief.draft import DraftResult, SectionFailure
from app.brief.headline import Drafts, bill_house_line, derive_card, derive_headline
from app.config import DRAFT_MODEL_ID
from app.geocode import GeocodeResult
from app.schema import SECTION_IDS

# What an unavailable section still carries so the UI renders a sensible block.
_EMPTY_EXTRA: dict[str, dict[str, Any]] = {
    "on_your_grid": {"facilities": []},
    "coming": {"facilities": [], "construction": []},
    "your_bill": {},
    "protection": {
        "tariff": {
            "large_load_tariff": "unknown",
            "name": None,
            "protects_households": None,
            "docket": None,
        }
    },
    "hearing": {"hearing": {"next_date": None, "body": None}},
}


def assemble_brief(
    geo: GeocodeResult,
    drafts: Drafts,
    house: list[dict[str, Any]] | None = None,
    *,
    brief_id: str,
    now_iso: str,
    verified: bool = True,
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    sections: dict[str, Any] = {}

    for sid in SECTION_IDS:
        d = drafts.get(sid)
        if isinstance(d, DraftResult):
            first = len(claims) + 1
            own = [_claim(sid, c, n, now_iso) for n, c in enumerate(d.claims, start=first)]
            claims.extend(own)
            section: dict[str, Any] = {
                "status": "reported",
                "confidence": max(0.0, min(1.0, d.confidence)),
                "model": DRAFT_MODEL_ID,
                "summary": d.summary,
                "gap": d.gap,
                "sources": _distinct_sources(own),
                **d.extra,
            }
            if sid == "coming":
                section.setdefault("construction", [])
        else:
            reason = d.reason if isinstance(d, SectionFailure) else "The section was not drafted."
            section = {
                "status": "unavailable",
                "confidence": 0.0,
                "model": DRAFT_MODEL_ID,
                "summary": "Not known.",
                "gap": reason,
                "sources": [],
                **_EMPTY_EXTRA[sid],
            }
        sections[sid] = section

    # The strip: the bill sentence first, then the model's lines, each `reported`
    # with the claims it rests on.
    at_your_house: list[dict[str, Any]] = []
    bill_line = bill_house_line(drafts)
    if bill_line:
        bill_line["sources"] = list(sections["your_bill"]["sources"])
        at_your_house.append(bill_line)
    for line in house or []:
        first = len(claims) + 1
        own = [
            _claim("at_your_house", c, n, now_iso)
            for n, c in enumerate(line["claims"], start=first)
        ]
        claims.extend(own)
        at_your_house.append(
            {
                "text": line["text"],
                "topic": line["topic"],
                "status": "reported",
                "confidence": max(0.0, min(1.0, float(line["confidence"]))),
                "sources": _distinct_sources(own),
            }
        )

    return {
        "brief_id": brief_id,
        "generated_at": now_iso,
        "source_mode": "agent",
        "fixture": False,
        "address": {
            "display": geo.display,
            "lat": geo.lat,
            "lon": geo.lon,
            "state": geo.state,
            **({"county": geo.county} if geo.county else {}),
            "zip": geo.zip,
            "utility": None,
        },
        "headline": derive_headline(drafts, geo),
        "sections": sections,
        "claims": claims,
        "at_your_house": at_your_house[:5],
        "card": derive_card(drafts, geo, claims, verified=verified),
    }


def _claim(sid: str, c: dict[str, Any], n: int, now_iso: str) -> dict[str, Any]:
    return {
        "id": f"c{n}",
        "section": sid,
        "text": c["text"],
        "source": {
            "title": c["source_title"],
            "url": c["source_url"],
            "retrieved_at": now_iso,
            "page": c.get("page"),
            "quote": c.get("quote") or "",
        },
        "drafted_by": DRAFT_MODEL_ID,
        "verdict": "unchecked",
        "verified_by": None,
        "verifier_note": None,
    }


def _distinct_sources(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for c in claims:
        s = c["source"]
        if s["url"] in seen:
            continue
        seen.add(s["url"])
        out.append(dict(s))
    return out
