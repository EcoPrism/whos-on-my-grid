"""Turn five drafts (or failures) and the engine's ground truth into one Brief
JSON. Facts the engine measured (facilities, utility, prices) are the
engine's; the model's drafts supply sentences, annotations and what no
dataset holds. Claims start `unchecked`; the verifier fills them in."""

import dataclasses
import re
from typing import Any

from app.brief.draft import DraftResult, SectionFailure
from app.brief.headline import (
    Drafts,
    bill_house_line,
    derive_card,
    derive_headline,
    land_house_line,
    monthly_change,
    noise_house_line,
)
from app.config import DRAFT_MODEL_ID
from app.geocode import GeocodeResult
from app.ground.facilities import compass, haversine_km
from app.ground.prices import EPM_TABLE_TITLE, EPM_TABLE_URL
from app.ground.types import (
    ConstructionSite,
    Decision,
    GroundFacility,
    GroundTruth,
    ImageryResult,
    PriceSeries,
)
from app.regions.locale import US_LOCALE, Locale
from app.schema import SECTION_IDS

KM_TO_MI = 0.621371
ENGINE_CLAIM_FACILITIES = 5  # nearest facilities that get their own checkable claim
BEYOND_MENTION_MAX = 5  # a sparse ring names the campus beyond it; a dense one need not
DECISION_RADIUS_KM = 25.0  # a campus voted on within 15 miles is this address's news
MONTHS = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
]  # fmt: skip

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

# Strip lines about impact need a facility to be about. These words mark a
# line that says there is none to report, which may stay.
_SAYS_NONE = re.compile(
    r"not (known|public|published)|no (data[- ]center|facilit|nearby|building)", re.I
)
_IMPACT_TOPICS = {"noise", "water", "air", "land"}
# The order people feel them: the bill, then water, then noise, then the rest.
_TOPIC_ORDER = {
    t: i for i, t in enumerate(["bill", "water", "noise", "land", "air", "grid", "taxes", "other"])
}


def assemble_brief(
    geo: GeocodeResult,
    drafts: Drafts,
    house: list[dict[str, Any]] | None = None,
    *,
    brief_id: str,
    now_iso: str,
    verified: bool = True,
    truth: GroundTruth | None = None,
    public_base_url: str = "",
    locale: Locale = US_LOCALE,
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    sections: dict[str, Any] = {}
    card_lines: list[str] = []

    for sid in SECTION_IDS:
        d = drafts.get(sid)
        section = _from_draft(sid, d, claims, now_iso)
        card_line = d.card_line if isinstance(d, DraftResult) else None
        if truth is not None:
            section, card_line = _ground(sid, section, d, truth, claims, now_iso, geo, card_line)
        sections[sid] = section
        if card_line:
            card_lines.append(card_line)

    if truth is not None and truth.utility is not None:
        claims.append(
            _engine_claim(
                "on_your_grid",
                f"The electric retail service territory at this point is {truth.utility.raw_name} "
                f"({truth.utility.kind.lower()}) in the HIFLD / EIA service-territory map"
                + (
                    f", EIA utility number {truth.utility.eia_id}." if truth.utility.eia_id else "."
                ),
                truth.utility.source_url,
                "Electric Retail Service Territories (HIFLD, via EIA Atlas)",
                truth.utility.raw_name,
                len(claims) + 1,
                now_iso,
            )
        )
        sections["on_your_grid"]["sources"] = _distinct_sources(
            [c for c in claims if c["section"] == "on_your_grid"]
        )

    at_your_house = _strip(sections, house or [], claims, now_iso, truth)

    return {
        "brief_id": brief_id,
        "generated_at": now_iso,
        "source_mode": "full" if truth is not None else "agent",
        "fixture": False,
        "address": {
            "display": geo.display,
            "lat": geo.lat,
            "lon": geo.lon,
            "state": geo.state,
            **({"county": geo.county} if geo.county else {}),
            "zip": geo.zip,
            "country": geo.country,
            "region_code": geo.region_code,
            "postal_code": geo.postal_code,
            "utility": truth.utility.name if truth is not None and truth.utility else None,
        },
        "locale": dataclasses.asdict(locale),
        "headline": derive_headline(sections, geo, truth),
        "sections": sections,
        "claims": claims,
        "at_your_house": at_your_house[:5],
        "card": derive_card(
            card_lines,
            geo,
            claims,
            verified=verified,
            grounded=truth is not None,
            brief_id=brief_id,
            generated_at=now_iso,
            public_base_url=public_base_url,
        ),
    }


# --- drafts -------------------------------------------------------------------


def _from_draft(
    sid: str, d: DraftResult | SectionFailure | None, claims: list[dict[str, Any]], now_iso: str
) -> dict[str, Any]:
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
        return section
    reason = d.reason if isinstance(d, SectionFailure) else "The section was not drafted."
    return {
        "status": "unavailable",
        "confidence": 0.0,
        "model": DRAFT_MODEL_ID,
        "summary": "Not known.",
        "gap": reason,
        "sources": [],
        **_EMPTY_EXTRA[sid],
    }


# --- ground truth ---------------------------------------------------------------


def _ground(
    sid: str,
    section: dict[str, Any],
    d: DraftResult | SectionFailure | None,
    truth: GroundTruth,
    claims: list[dict[str, Any]],
    now_iso: str,
    geo: GeocodeResult,
    card_line: str | None,
) -> tuple[dict[str, Any], str | None]:
    drafted = isinstance(d, DraftResult)
    if sid == "on_your_grid" and truth.facilities is not None:
        return _grid_section(section, d, truth, claims, now_iso, drafted, card_line, geo)
    if sid == "coming":
        return _coming_section(section, truth, claims, now_iso, geo, drafted, card_line)
    if sid == "hearing":
        return _hearing_section(section, truth, claims, now_iso, geo, card_line)
    if sid == "your_bill" and truth.best_price is not None:
        return _bill_section(section, d, truth, claims, now_iso, geo, drafted, card_line)
    if sid == "protection" and truth.tariff is not None:
        return _protection_section(section, truth, claims, now_iso, drafted, card_line)
    if truth.notes and sid in ("on_your_grid", "your_bill"):
        section["gap"] = " ".join(filter(None, [section.get("gap"), *truth.notes]))
    return section, card_line


def _grid_section(
    section: dict[str, Any],
    d: DraftResult | SectionFailure | None,
    truth: GroundTruth,
    claims: list[dict[str, Any]],
    now_iso: str,
    drafted: bool,
    card_line: str | None,
    geo: GeocodeResult,
) -> tuple[dict[str, Any], str | None]:
    engine = truth.facilities or []
    spark = {_key(f["name"]): f for f in (section.get("facilities") or [])} if drafted else {}
    facilities = [_facility(f, spark.get(_key(f.name))) for f in engine]

    first = len(claims) + 1
    own = [
        _engine_claim(
            "on_your_grid",
            _facility_claim(f),
            f.source_url,
            f.source_title,
            f.name or "",
            n,
            now_iso,
        )
        for n, f in enumerate(engine[:ENGINE_CLAIM_FACILITIES], start=first)
    ]
    claims.extend(own)
    # A curated operator (data/regions/us/facilities.json) gets its own claim citing the
    # page that names it; the map record's claim above says nothing about who.
    cited: set[str] = set()
    for f in engine[:ENGINE_CLAIM_FACILITIES]:
        src = f.operator_source
        if src is not None and src.url not in cited:
            cited.add(src.url)
            claims.append(
                _engine_claim(
                    "on_your_grid",
                    src.claim,
                    src.url,
                    src.title,
                    src.quote,
                    len(claims) + 1,
                    now_iso,
                )
            )
    # The campus just past the ring, when the ring itself is sparse: the
    # thing a resident has heard of and would otherwise think we missed.
    beyond = truth.beyond_ring if len(engine) < BEYOND_MENTION_MAX else None
    if beyond is not None:
        claims.append(
            _engine_claim(
                "on_your_grid",
                _facility_claim(beyond),
                beyond.source_url,
                beyond.source_title,
                beyond.name or "",
                len(claims) + 1,
                now_iso,
            )
        )
        section["beyond_ring"] = _facility(beyond, None)

    live = sum(1 for f in engine if f.status == "live")
    building = len(engine) - live
    if not drafted:
        section["summary"] = _grid_summary(engine, live, building, beyond, geo)
        section["gap"] = " ".join(filter(None, [section.get("gap"), *truth.notes])) or None
    elif truth.notes:
        section["gap"] = " ".join(filter(None, [section.get("gap"), *truth.notes]))
    if drafted and beyond is not None and not _mentions(section.get("summary"), beyond):
        section["summary"] = (
            f"{(section.get('summary') or '').rstrip()} {_beyond_sentence(beyond, geo)}".strip()
        )
    section["facilities"] = facilities
    section["status"] = "measured"
    section["confidence"] = 0.9 if not truth.notes else 0.7
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "on_your_grid"])
    # The count is the engine's arithmetic; a drafted card line that disagrees is dropped.
    if truth.facilities is not None or not card_line:
        card_line = (
            f"{len(engine)} data center{'s' if len(engine) != 1 else ''} within 5 miles"
            if engine
            else "No data centers listed within 5 miles"
        )
    return section, card_line


def _facility_claim(f: GroundFacility) -> str:
    """Only what the cited page itself shows: the record exists and what it is
    tagged as. Distance is the engine's arithmetic, not the page's."""
    if "peeringdb" in f.providers:
        return f"PeeringDB lists a facility named {f.name}" + (
            f" under the organization {f.operator}." if f.operator_known else "."
        )
    tag = "under construction" if f.status == "under_construction" else "a data center"
    what = f"{f.buildings} buildings" if f.buildings > 1 else "a building"
    name = (
        f" named {f.name}"
        if f.name
        and f.operator_source is None  # a curated name is not on the map page
        and not f.name.startswith(("Unnamed", f"{f.buildings} unnamed"))
        and "(" not in f.name
        else ""
    )
    # A curated operator is not on the map page; its own claim cites its own page.
    who = f", operator {f.operator}" if f.operator_known and f.operator_source is None else ""
    return f"OpenStreetMap maps {what}{name} here tagged as {tag}{who}."


def _mentions(summary: str | None, b: GroundFacility) -> bool:
    """Spark usually writes the campus beyond the ring in from the facts block;
    the engine adds its sentence only when neither the name nor the operator
    appears."""
    text = (summary or "").lower()
    return b.name.lower() in text or b.operator.lower() in text


def _beyond_sentence(b: GroundFacility, geo: GeocodeResult) -> str:
    what = b.name if b.operator.lower() in b.name.lower() else f"{b.name} ({b.operator})"
    return (
        f"The nearest large campus beyond the five-mile ring is {what}, "
        f"{b.distance_km * KM_TO_MI:.1f} miles to the {compass(geo.lat, geo.lon, b.lat, b.lon)}, "
        "outside the ring this brief measures."
    )


def _grid_summary(
    engine: list[GroundFacility],
    live: int,
    building: int,
    beyond: GroundFacility | None = None,
    geo: GeocodeResult | None = None,
) -> str:
    tail = f" {_beyond_sentence(beyond, geo)}" if beyond is not None and geo is not None else ""
    if not engine:
        return (
            "No data-center facility within five miles of this address is listed in PeeringDB "
            "or OpenStreetMap. Small server rooms inside offices are not in either database." + tail
        )
    nearest = engine[0]
    operators = []
    for f in engine:
        if f.operator_known and f.operator not in operators:
            operators.append(f.operator)
    who = ", ".join(operators[:4]) + (" and others" if len(operators) > 4 else "")
    parts = [
        f"{len(engine)} data-center {'facility is' if len(engine) == 1 else 'facilities are'} "
        f"within five miles of this address according to PeeringDB and OpenStreetMap: "
        f"{live} operating{f' and {building} under construction' if building else ''}."
    ]
    parts.append(
        f"The nearest is {nearest.name}, {nearest.distance_km * KM_TO_MI:.1f} miles away"
        + (f", operated by {nearest.operator}." if nearest.operator_known else ".")
    )
    if who:
        parts.append(f"Operators on record: {who}.")
    return " ".join(parts) + tail


def _facility(f: GroundFacility, spark: dict[str, Any] | None) -> dict[str, Any]:
    """The engine's facility, with the fields only a model can add merged in
    from a draft entry of the same name."""
    out: dict[str, Any] = {
        "name": f.name,
        "codename": None,
        "operator": f.operator,
        "operator_confidence": 0.95 if f.operator_known else 0.0,
        "distance_km": f.distance_km,
        "status": f.status,
        "estimated_mw": None,
        "mw_basis": None,
        "shares_substation": None,
        "lat": f.lat,
        "lon": f.lon,
    }
    if spark:
        for k in ("codename", "estimated_mw", "mw_basis", "shares_substation"):
            if spark.get(k) is not None:
                out[k] = spark[k]
        if not f.operator_known and spark.get("operator"):
            out["operator"] = spark["operator"]
            out["operator_confidence"] = min(0.6, float(spark.get("operator_confidence") or 0.5))
    return out


def _coming_section(
    section: dict[str, Any],
    truth: GroundTruth,
    claims: list[dict[str, Any]],
    now_iso: str,
    geo: GeocodeResult,
    drafted: bool,
    card_line: str | None,
) -> tuple[dict[str, Any], str | None]:
    """What is coming, from three places: the model's announced campuses
    (kept, minus anything the database already has), the public record of
    votes on named campuses (the engine's `decisions`), and what SAM 3.1
    measured between two imagery vintages (the engine's `construction`)."""
    facilities = section.get("facilities") or []
    if truth.facilities is not None:
        facilities = _coming_facilities(facilities, truth, geo)
    decided = _decision_facilities(truth.decisions, geo, claims, now_iso)
    if decided:
        keys = {_key(f["name"]) for f in decided} | {_key(f.get("codename")) for f in decided}
        facilities = [
            f
            for f in facilities
            if _key(f["name"]) not in keys and _key(f.get("codename")) not in keys
        ]
    section["facilities"] = [*decided, *facilities]

    img = truth.imagery
    if img is None:
        if geo.county:
            section["gap"] = " ".join(
                filter(
                    None,
                    [
                        section.get("gap"),
                        f"Aerial imagery has not been indexed for {geo.county} County yet, so new "
                        "construction here comes only from OpenStreetMap tags and public "
                        "announcements.",
                    ],
                )
            )
        if decided and not drafted:
            section["summary"] = _coming_summary(None, section["facilities"])
            section["status"] = "reported"
            section["confidence"] = 0.7
            section["sources"] = _distinct_sources([c for c in claims if c["section"] == "coming"])
        return section, card_line

    section["construction"] = [_construction(s, img) for s in img.sites]
    for vintage in (img.then, img.now):
        for item in vintage.items:
            claims.append(
                _engine_claim(
                    "coming",
                    f"USDA NAIP aerial imagery {item.id}, acquired {item.date}, covers this area "
                    f"({vintage.source}).",
                    item.url,
                    item.title,
                    item.id,
                    len(claims) + 1,
                    now_iso,
                )
            )
    section["summary"] = _coming_summary(img, section["facilities"])
    section["status"] = "measured"
    section["model"] = img.model
    section["confidence"] = 0.8 if img.counted else 0.7
    section["gap"] = (
        "Roofs are measured from public aerial imagery; what is inside them is not. A large "
        "roof in no database is counted only when it adjoins a listed data center."
    )
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "coming"])
    acres = img.new_acres
    if acres > 0:
        card_line = f"{acres:.0f} acres of new data-center roof since {img.then.year}"[:80]
    elif not card_line:
        card_line = f"No new large data-center roof since {img.then.year} imagery"
    return section, card_line


def _construction(s: ConstructionSite, img: ImageryResult) -> dict[str, Any]:
    return {
        "label": s.label,
        "kind": s.kind,
        "distance_km": s.distance_km,
        "footprint_acres_then": s.footprint_acres_then,
        "footprint_acres_now": s.footprint_acres_now,
        "vintages": list(img.vintages),
        "in_database": s.in_database,
        "near_cluster": s.near_cluster,
        "polygon": [list(p) for p in s.polygon],
    }


def _coming_summary(img: ImageryResult | None, facilities: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    if img is not None:
        counted = img.counted
        other = [s for s in img.sites if not s.counted]
        then, now = img.vintages
        if counted:
            exp = sum(1 for s in counted if s.kind == "expansion")
            new = len(counted) - exp
            what = []
            if new:
                what.append(f"{new} new large roof{'s' if new != 1 else ''}")
            if exp:
                what.append(f"{exp} expansion{'s' if exp != 1 else ''} of a listed data center")
            nearest = counted[0]
            parts.append(
                f"Between the {then} and {now} aerial imagery, {' and '.join(what)} appeared "
                f"within five miles, about {img.new_acres:.0f} acres of roof in all. The nearest "
                f"is {nearest.label}, {nearest.distance_km * KM_TO_MI:.1f} miles away."
            )
        else:
            parts.append(
                f"Between the {then} and {now} aerial imagery, no new large roof appeared within "
                "five miles next to a listed data center."
            )
        if other:
            parts.append(
                f"{len(other)} other large roof{'s' if len(other) != 1 else ''} went up in that "
                "time with no data center listed nearby; the imagery cannot say what they are."
            )
    rejected = [f for f in facilities if f.get("status") == "rejected"]
    announced = [f for f in facilities if f.get("status") in ("announced", "under_construction")]
    for f in rejected:
        parts.append(
            f"{f['name']}{' (' + f['codename'] + ')' if f.get('codename') else ''}, "
            f"{f['distance_km'] * KM_TO_MI:.0f} miles away, was voted down or withdrawn."
        )
    if announced:
        names = ", ".join(
            f"{f['name']} ({f['operator']})" if f.get("operator") else f["name"]
            for f in announced[:3]
        )
        parts.append(f"Announced or filed: {names}.")
    return " ".join(parts) or "Not known."


def _decision_facilities(
    decisions: list[Decision],
    geo: GeocodeResult,
    claims: list[dict[str, Any]],
    now_iso: str,
) -> list[dict[str, Any]]:
    """A campus a county or city voted on, as a Coming entry with the vote as
    its claim. Within fifteen miles: a rejected campus is this address's news
    even when it sits outside the five-mile ring, and the distance is shown."""
    out = []
    for d in decisions:
        if d.lat is None or d.lon is None:
            continue
        dist = round(haversine_km(geo.lat, geo.lon, d.lat, d.lon), 2)
        if dist > DECISION_RADIUS_KM:
            continue
        status = {"rejected": "rejected", "approved": "announced", "announced": "announced"}.get(
            d.status, "rejected"
        )
        claims.append(
            _engine_claim(
                "coming", d.text, d.source_url, d.source_title, d.quote, len(claims) + 1, now_iso
            )
        )
        out.append(
            {
                "name": d.project,
                "codename": d.codename,
                "operator": d.operator or "Not known",
                "operator_confidence": 0.9 if d.operator else 0.0,
                "distance_km": dist,
                "status": status,
                "estimated_mw": d.estimated_mw,
                "mw_basis": "filed" if d.estimated_mw else None,
                "shares_substation": None,
                "lat": d.lat,
                "lon": d.lon,
            }
        )
    return out


def _hearing_section(
    section: dict[str, Any],
    truth: GroundTruth,
    claims: list[dict[str, Any]],
    now_iso: str,
    geo: GeocodeResult,
    card_line: str | None,
) -> tuple[dict[str, Any], str | None]:
    """The last indexed hearing for this county, quoted verbatim from the
    transcript of the official recording. Without an index the model's
    recollection stands, and the gap says so."""
    h = truth.hearing
    if h is None:
        why = truth.hearing_note or (
            f"Hearings for {geo.county} County are not indexed yet (docs/counties.md)"
            if geo.county
            else None
        )
        if why:
            section["gap"] = " ".join(
                filter(
                    None,
                    [
                        section.get("gap"),
                        f"{why.rstrip('.')}, so this section is the model's recollection, not "
                        "a transcript.",
                    ],
                )
            )
        return section, card_line

    said = []
    for q in h.quotes:
        said.append(
            {
                "speaker_role": q.role,
                "speaker_name": q.name,
                "quote": q.text,
                "timestamp_s": q.start_s,
            }
        )
        who = (
            f"{q.name}, {q.role}"
            if q.name
            else f"a {q.role}"
            if q.role != "unknown"
            else "a speaker"
        )
        claims.append(
            _engine_claim(
                "hearing",
                f"At the {h.body} meeting on {h.date} ({h.subject}), {who} said: “{q.text}”",
                h.page_url,
                h.page_title,
                q.text,
                len(claims) + 1,
                now_iso,
            )
        )
    upcoming = h.upcoming if h.upcoming and h.upcoming.date >= now_iso[:10] else None
    section["hearing"] = {
        "next_date": upcoming.date if upcoming else None,
        "body": h.body,
        "subject": h.subject,
        "last_meeting_date": h.date,
        "last_meeting_said": said,
    }
    first = h.quotes[0]
    who = (
        f"{first.name} ({first.role})"
        if first.name
        else f"a {first.role}"
        if first.role != "unknown"
        else "a speaker"
    )
    text = (
        f"At the {h.body} meeting on {_date_words(h.date)}, on {h.subject}, {who} said: "
        f"“{first.text}”"
    )
    text += (
        f" The next listed hearing is {upcoming.subject} on {_date_words(upcoming.date)}."
        if upcoming
        else " No upcoming data-center hearing is listed for this body."
    )
    section["summary"] = text
    section["status"] = "measured"
    section["model"] = h.model
    if h.model and h.agreement is not None:
        section["confidence"] = round(0.6 + 0.3 * max(0.0, min(1.0, h.agreement)), 2)
    else:
        section["confidence"] = 0.75 if h.model else 0.8
    section["gap"] = (
        f"Only part of the recording is indexed: {h.coverage}. Speaker roles are inferred from "
        "the transcript; the words are verbatim."
        if h.coverage
        else "Speaker roles are inferred from the transcript; the words are verbatim."
    )
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "hearing"])
    card_line = f"On the record {h.date[:4]}: {h.subject}"[:80]
    return section, card_line


def _date_words(d: str) -> str:
    try:
        y, m, day = (int(x) for x in d.split("-"))
        return f"{day} {MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return d


def _coming_facilities(
    drafted: list[dict[str, Any]], truth: GroundTruth, geo: GeocodeResult
) -> list[dict[str, Any]]:
    """What the model knows that no database holds: announced, permitted and
    rejected campuses. Anything that matches a database facility, or claims to
    be live, is dropped: existence is the engine's call."""
    engine_keys = {_key(f.name) for f in truth.facilities or []}
    engine_ops = {_key(f.operator) for f in truth.facilities or [] if f.operator_known}
    out = []
    for f in drafted:
        if f.get("status") not in ("announced", "under_construction", "rejected"):
            continue
        if _key(f["name"]) in engine_keys:
            continue
        if f.get("status") == "under_construction" and _key(f.get("operator")) in engine_ops:
            continue  # the database already has that operator's buildings here
        if isinstance(f.get("lat"), int | float) and isinstance(f.get("lon"), int | float):
            f["distance_km"] = round(haversine_km(geo.lat, geo.lon, f["lat"], f["lon"]), 2)
        out.append(f)
    return out


def _bill_section(
    section: dict[str, Any],
    d: DraftResult | SectionFailure | None,
    truth: GroundTruth,
    claims: list[dict[str, Any]],
    now_iso: str,
    geo: GeocodeResult,
    drafted: bool,
    card_line: str | None,
) -> tuple[dict[str, Any], str | None]:
    p = truth.best_price
    assert p is not None
    attribution = (section.get("price") or {}).get("attribution") if drafted else None
    price: dict[str, Any] = {
        "currency": p.currency,
        "rate_now": p.rate_now,
        "rate_then": p.rate_then,
        "trend_pct": p.trend_pct,
        "window_months": p.window_months,
        "typical_household_kwh_month": p.typical_kwh_month,
        "attribution": attribution or None,
    }
    if p.as_of:
        price["as_of"] = p.as_of
    price["granularity"] = p.granularity
    for text, url, title, quote in _price_claims(truth, geo):
        claims.append(_engine_claim("your_bill", text, url, title, quote, len(claims) + 1, now_iso))
    change = monthly_change(price)
    if not drafted:
        section["summary"] = _bill_summary(truth, geo, change)
        section["gap"] = " ".join(filter(None, [section.get("gap"), *truth.notes])) or None
    section["price"] = price
    section["status"] = "modelled"
    section["confidence"] = 0.85 if p.scope == "utility" else 0.8
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "your_bill"])
    if not card_line:
        sign = "+" if change >= 0 else "−"
        card_line = f"{sign}${abs(change):.0f}/mo for a typical {geo.state} home vs 2 yrs ago"
    return section, card_line


def _period(p: PriceSeries) -> tuple[str, str]:
    """('calendar 2024', 'calendar 2022') or ('the twelve months to August 2026', 'the
    twelve months ending 24 months earlier')."""
    if p.scope == "utility":
        return f"calendar {p.latest[0]}", f"calendar {p.latest[0] - p.window_months // 12}"
    month = f"{MONTHS[p.latest[1] - 1]} {p.latest[0]}"
    return f"the twelve months to {month}", "the twelve months ending 24 months earlier"


def _price_claims(truth: GroundTruth, geo: GeocodeResult) -> list[tuple[str, str, str, str]]:
    out = []
    u = truth.utility_price
    if u:
        now, then = _period(u)
        out.append(
            (
                f"EIA-861 sales to ultimate customers: {u.label} residential revenue over sales in "
                f"{geo.state} was {u.rate_now * 100:.2f} cents per kWh in {now} and "
                f"{u.rate_then * 100:.2f} cents in {then}, at {u.typical_kwh_month:.0f} kWh a "
                "month per customer.",
                u.source_url,
                u.source_title,
                f"Sales_Ult_Cust_{u.latest[0]}",
            )
        )
    s = truth.price
    if s:
        now, then = _period(s)
        out.append(
            (
                f"EIA-861M: {geo.state} statewide residential revenue over sales was "
                f"{s.rate_now * 100:.2f} cents per kWh for {now} and {s.rate_then * 100:.2f} "
                f"cents for {then} ({s.data_status.lower()} data).",
                s.source_url,
                s.source_title,
                "sales_revenue.xlsx",
            )
        )
        if s.latest_month_rate is not None:
            month = f"{MONTHS[s.latest[1] - 1]} {s.latest[0]}"
            out.append(
                (
                    f"EIA Electric Power Monthly Table 5.6.A lists the {geo.state} residential "
                    f"average price for {month} at {s.latest_month_rate * 100:.2f} cents per kWh.",
                    EPM_TABLE_URL,
                    EPM_TABLE_TITLE,
                    f"{s.latest_month_rate * 100:.2f}",
                )
            )
    return out


def _bill_summary(truth: GroundTruth, geo: GeocodeResult, change: float) -> str:
    p = truth.best_price
    assert p is not None
    now, then = _period(p)
    word = "more" if change >= 0 else "less"
    who = (
        f"{truth.utility.name} customers"
        if p.scope == "utility" and truth.utility
        else f"homes in {geo.state}"
    )
    text = (
        f"For {who}, the average home electricity price was {p.rate_now * 100:.1f} cents per kWh "
        f"in {now}, against {p.rate_then * 100:.1f} cents in {then}, a change of "
        f"{p.trend_pct:+.1f}%. For a typical home here using about {p.typical_kwh_month:.0f} kWh "
        f"a month, that is about ${abs(change):.0f} a month {word}."
    )
    s = truth.price
    if p.scope == "utility" and s is not None:
        s_now, _ = _period(s)
        text += (
            f" Statewide, {geo.state} averaged {s.rate_now * 100:.1f} cents in {s_now}, "
            f"{s.trend_pct:+.1f}% over two years."
        )
    return text + " No regulator or utility statement tying the change to data centers was found."


def _protection_section(
    section: dict[str, Any],
    truth: GroundTruth,
    claims: list[dict[str, Any]],
    now_iso: str,
    drafted: bool,
    card_line: str | None,
) -> tuple[dict[str, Any], str | None]:
    """A tariff the engine's table knows about overrides what the model
    recalled; the model's claims stay for the verifier."""
    t = truth.tariff
    assert t is not None
    claims.append(
        _engine_claim("protection", t.summary, t.url, t.title, "", len(claims) + 1, now_iso)
    )
    section["tariff"] = {
        "large_load_tariff": t.status,
        "name": t.name,
        "protects_households": t.protects_households,
        "docket": t.docket,
    }
    section["summary"] = f"{t.lead} {t.summary}"
    section["status"] = "reported"
    section["confidence"] = max(float(section.get("confidence") or 0.0), 0.8)
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "protection"])
    if t.status == "in_force" and t.protects_households:
        card_line = f"Bill shield: {t.name or 'large-load tariff'} in force"[:80]
    elif t.status == "proposed":
        card_line = "Bill shield: large-load tariff proposed, not approved"
    elif t.status == "none_found":
        card_line = "No large-load tariff found for this utility"
    return section, card_line


# --- the strip -------------------------------------------------------------------


def _strip(
    sections: dict[str, Any],
    house: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    now_iso: str,
    truth: GroundTruth | None,
) -> list[dict[str, Any]]:
    """The bill sentence first, the engine's noise sentence when it has a
    facility list, then the model's lines, each `reported` with its claims."""
    out: list[dict[str, Any]] = []
    bill = bill_house_line(sections)
    if bill:
        out.append(bill)
    engine_noise = noise_house_line(truth, now_iso) if truth is not None else None
    if engine_noise:
        out.append(engine_noise)
    engine_land = land_house_line(truth, now_iso) if truth is not None else None
    if engine_land:
        out.append(engine_land)
    grounded_empty = truth is not None and truth.facilities is not None and not truth.facilities
    for line in house:
        if engine_noise and line["topic"] == "noise":
            continue
        if engine_land and line["topic"] == "land":
            continue
        if (
            grounded_empty
            and line["topic"] in _IMPACT_TOPICS
            and not _SAYS_NONE.search(line["text"])
        ):
            continue
        first = len(claims) + 1
        own = [
            _claim("at_your_house", c, n, now_iso)
            for n, c in enumerate(line["claims"], start=first)
        ]
        claims.extend(own)
        out.append(
            {
                "text": line["text"],
                "topic": line["topic"],
                "status": "reported",
                "confidence": max(0.0, min(1.0, float(line["confidence"]))),
                "sources": _distinct_sources(own),
            }
        )
    out.sort(key=lambda line: _TOPIC_ORDER.get(line["topic"], 99))
    return out


# --- claims ---------------------------------------------------------------------


def _key(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


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


def _engine_claim(
    sid: str, text: str, url: str, title: str, quote: str, n: int, now_iso: str
) -> dict[str, Any]:
    """A claim the engine makes from a dataset. Drafted by the engine, not a
    model; the verifier still fetches the page and judges it like any other."""
    return {
        "id": f"c{n}",
        "section": sid,
        "text": text,
        "source": {
            "title": title,
            "url": url,
            "retrieved_at": now_iso,
            "page": None,
            "quote": quote,
        },
        "drafted_by": "engine",
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
