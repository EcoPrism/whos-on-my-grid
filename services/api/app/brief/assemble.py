"""Turn five drafts (or failures) and the engine's ground truth into one Brief
JSON. Facts the engine measured (facilities, utility, prices) are the
engine's; the model's drafts supply sentences, annotations and what no
dataset holds. Claims start `unchecked`; the verifier fills them in."""

import dataclasses
import re
from typing import Any

from app.brief import units as u
from app.brief.draft import DraftResult, SectionFailure
from app.brief.headline import (
    NOISE_SENTENCE_MI,
    Drafts,
    bill_house_line,
    derive_card,
    derive_headline,
    half_year,
    land_house_line,
    monthly_change,
    noise_house_line,
    period_words,
)
from app.brief.vocab import CONNECTION_POLICY_AIM, US_VOCAB, Vocab, vocab_for
from app.config import DRAFT_MODEL_ID
from app.geocode import GeocodeResult
from app.ground.facilities import compass, haversine_km
from app.ground.hearings import DECISION_RADIUS_KM
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
from app.scenario.model import noise_at
from app.schema import SECTION_IDS
from app.telemetry import log_event

KM_TO_MI = u.KM_TO_MI
HIFLD_TITLE = "Electric Retail Service Territories (HIFLD, via EIA Atlas)"
ENGINE_CLAIM_FACILITIES = 5  # nearest facilities that get their own checkable claim
BEYOND_MENTION_MAX = 5  # a sparse ring names the campus beyond it; a dense one need not
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
# line that only says there is nothing to report: nothing published, nothing
# nearby. Such lines fold into one (see _quiet_line).
_SAYS_NONE = re.compile(
    r"not (known|public|published|disclosed|available|reported|on record)"
    r"|do(?:es)? not (publish|disclose|report|share|say)"
    r"|no (public |published )?(figure|data|record|number|breakdown)"
    r"|no (data[- ]cent(?:er|re)|facilit|nearby|building)",
    re.I,
)
_IMPACT_TOPICS = {"noise", "water", "air", "land"}
# Model lines on these topics that only say nothing is published are folded
# into one short line; the glance block marks the topic Not public.
_QUIET_TOPICS = ("water", "land", "air", "taxes")
_QUIET_WORDS = {
    "US": {
        "water": "water use",
        "land": "land",
        "air": "generator permits",
        "taxes": "property taxes",
    },
    "IE": {
        "water": "water use",
        "land": "land",
        "air": "generator licences",
        "taxes": "commercial rates",
    },
}
# The tiles on the brief page, in the order people feel them.
GLANCE_TOPICS = ("bill", "grid", "noise", "water", "land", "taxes", "air")
# The order people feel them: the bill, then water, then noise, then the rest.
_TOPIC_ORDER = {
    t: i for i, t in enumerate(["bill", "water", "noise", "land", "air", "grid", "taxes", "other"])
}

# Plan 0.6: the card line for a connection policy whose stated purpose is not
# household costs (CONNECTION_POLICY_AIM is the summary's sentence).
CONNECTION_POLICY_CARD = (
    "CRU data-centre connection policy in force; household bills not its stated aim"
)
NO_TYPICAL_USE = (
    "No typical household consumption figure is on record, so the monthly change is not computed."
)


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
    coverage: frozenset[str] | None = None,
) -> dict[str, Any]:
    """`locale` sets the words, units and currency of what the engine writes (the
    US default is byte-identical to the engine before regions). `coverage` names
    the sections this region can make `measured`; any other section that came out
    measured is downgraded to `reported`. None: every section."""
    claims: list[dict[str, Any]] = []
    sections: dict[str, Any] = {}
    card_lines: list[str] = []
    v = vocab_for(locale)

    for sid in SECTION_IDS:
        d = drafts.get(sid)
        section = _from_draft(sid, d, claims, now_iso)
        card_line = d.card_line if isinstance(d, DraftResult) else None
        if truth is not None:
            section, card_line = _ground(
                sid, section, d, truth, claims, now_iso, geo, card_line, locale
            )
        sections[sid] = section
        if card_line:
            card_lines.append(card_line)

    if truth is not None and truth.utility is not None:
        utility = truth.utility
        claims.append(
            _engine_claim(
                "on_your_grid",
                utility.claim_text
                or (
                    f"The electric retail service territory at this point is {utility.raw_name} "
                    f"({utility.kind.lower()}) in the HIFLD / EIA service-territory map"
                    + (f", EIA utility number {utility.eia_id}." if utility.eia_id else ".")
                ),
                utility.source_url,
                utility.source_title or HIFLD_TITLE,
                utility.quote if utility.quote is not None else utility.raw_name,
                len(claims) + 1,
                now_iso,
            )
        )
        sections["on_your_grid"]["sources"] = _distinct_sources(
            [c for c in claims if c["section"] == "on_your_grid"]
        )
    elif truth is not None and v.outside_map and not _utility_failed(truth, v):
        grid = sections["on_your_grid"]
        grid["gap"] = " ".join(filter(None, [grid.get("gap"), v.outside_map]))

    if coverage is not None:
        for sid in SECTION_IDS:
            if sid not in coverage and sections[sid].get("status") == "measured":
                sections[sid]["status"] = "reported"
                log_event("coverage_downgrade", section=sid)

    at_your_house = _strip(sections, house or [], claims, now_iso, truth, locale, geo)
    headline = derive_headline(sections, geo, truth, locale=locale)

    return {
        "brief_id": brief_id,
        "generated_at": now_iso,
        "source_mode": "full" if truth is not None else "agent",
        "fixture": False,
        "address": _address(geo, truth),
        "locale": dataclasses.asdict(locale),
        "headline": headline,
        "sections": sections,
        "claims": claims,
        "at_your_house": at_your_house[:5],
        "glance": _glance(
            sections, at_your_house, house or [], truth, headline, geo, now_iso, locale
        ),
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


def _address(geo: GeocodeResult, truth: GroundTruth | None) -> dict[str, Any]:
    """The address block. `state` and `zip` are US aliases, written only for a
    US address; elsewhere country, region_code, county and postal_code."""
    us = geo.country == "US"
    return {
        "display": geo.display,
        "lat": geo.lat,
        "lon": geo.lon,
        **({"state": geo.state} if us else {}),
        **({"county": geo.county} if geo.county else {}),
        **({"zip": geo.zip} if us else {}),
        "country": geo.country,
        "region_code": geo.region_code,
        "postal_code": geo.postal_code,
        "utility": truth.utility.name if truth is not None and truth.utility else None,
    }


def _utility_failed(truth: GroundTruth, v: Vocab) -> bool:
    """The utility provider raised (its failure note is in `notes`), as opposed
    to the point lying outside the map, which leaves no note."""
    marker = f"the serving {v.utility_word} is not known"
    return any(marker in n for n in truth.notes)


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
    locale: Locale = US_LOCALE,
) -> tuple[dict[str, Any], str | None]:
    drafted = isinstance(d, DraftResult)
    if sid == "on_your_grid" and truth.facilities is not None:
        return _grid_section(section, d, truth, claims, now_iso, drafted, card_line, geo, locale)
    if sid == "coming":
        return _coming_section(section, truth, claims, now_iso, geo, drafted, card_line, locale)
    if sid == "hearing":
        return _hearing_section(section, truth, claims, now_iso, geo, card_line, locale)
    if sid == "your_bill" and _usable(truth.best_price) is not None:
        return _bill_section(section, d, truth, claims, now_iso, geo, drafted, card_line, locale)
    if sid == "protection" and truth.tariff is not None:
        return _protection_section(section, truth, claims, now_iso, drafted, card_line)
    notes = list(truth.notes)
    if sid == "your_bill" and truth.best_price is not None:
        notes.append(NO_TYPICAL_USE)  # a price without a typical home is not a bill change
    if notes and sid in ("on_your_grid", "your_bill"):
        section["gap"] = " ".join(filter(None, [section.get("gap"), *notes]))
    return section, card_line


def _usable(p: PriceSeries | None) -> PriceSeries | None:
    """A series the bill can be computed from: it needs a typical home's use."""
    return p if p is not None and p.typical_kwh_month is not None else None


def _grid_section(
    section: dict[str, Any],
    d: DraftResult | SectionFailure | None,
    truth: GroundTruth,
    claims: list[dict[str, Any]],
    now_iso: str,
    drafted: bool,
    card_line: str | None,
    geo: GeocodeResult,
    locale: Locale = US_LOCALE,
) -> tuple[dict[str, Any], str | None]:
    v = vocab_for(locale)
    units = locale.units
    engine = truth.facilities or []
    spark = {_key(f["name"]): f for f in (section.get("facilities") or [])} if drafted else {}
    facilities = [_facility(f, spark.get(_key(f.name))) for f in engine]

    first = len(claims) + 1
    own = [
        _engine_claim(
            "on_your_grid",
            _facility_claim(f, v),
            f.source_url,
            f.source_title,
            _facility_quote(f),
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
                _facility_claim(beyond, v),
                beyond.source_url,
                beyond.source_title,
                _facility_quote(beyond),
                len(claims) + 1,
                now_iso,
            )
        )
        section["beyond_ring"] = _facility(beyond, None)

    live = sum(1 for f in engine if f.status == "live")
    building = len(engine) - live
    if not drafted:
        section["summary"] = _grid_summary(engine, live, building, beyond, geo, locale)
        section["gap"] = " ".join(filter(None, [section.get("gap"), *truth.notes])) or None
    elif truth.notes:
        section["gap"] = " ".join(filter(None, [section.get("gap"), *truth.notes]))
    if drafted and beyond is not None and not _mentions(section.get("summary"), beyond):
        section["summary"] = (
            f"{(section.get('summary') or '').rstrip()} "
            f"{_beyond_sentence(beyond, geo, units)}".strip()
        )
    section["facilities"] = facilities
    section["status"] = "measured"
    section["confidence"] = 0.9 if not truth.notes else 0.7
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "on_your_grid"])
    # The count is the engine's arithmetic; a drafted card line that disagrees is dropped.
    if truth.facilities is not None or not card_line:
        ring = u.card_radius(units)
        card_line = (
            f"{len(engine)} {v.dc_noun if len(engine) == 1 else v.dc_plural} within {ring}"
            if engine
            else f"No {v.dc_plural} listed within {ring}"
        )
    return section, card_line


def _facility_quote(f: GroundFacility) -> str:
    """The verbatim quote for _facility_claim: the organization when the shown
    name is a stand-in for a hidden PeeringDB record name, else the name."""
    if f.name_from_org and f.operator_known:
        return f.operator
    return f.name or ""


def _facility_claim(f: GroundFacility, v: Vocab = US_VOCAB) -> str:
    """Only what the cited page itself shows: the record exists and what it is
    tagged as. Distance is the engine's arithmetic, not the page's."""
    if "peeringdb" in f.providers:
        if f.name_from_org and f.operator_known:
            return f"PeeringDB lists a facility under the organization {f.operator}."
        return f"PeeringDB lists a facility named {f.name}" + (
            f" under the organization {f.operator}." if f.operator_known else "."
        )
    tag = "under construction" if f.status == "under_construction" else f"a {v.dc_noun}"
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


def _beyond_sentence(b: GroundFacility, geo: GeocodeResult, units: u.Units = "us") -> str:
    what = b.name if b.operator.lower() in b.name.lower() else f"{b.name} ({b.operator})"
    return (
        f"The nearest large campus beyond {u.ring_words(units)} is {what}, "
        f"{u.dist(b.distance_km, units)} to the {compass(geo.lat, geo.lon, b.lat, b.lon)}, "
        "outside the ring this brief measures."
    )


def _grid_summary(
    engine: list[GroundFacility],
    live: int,
    building: int,
    beyond: GroundFacility | None = None,
    geo: GeocodeResult | None = None,
    locale: Locale = US_LOCALE,
) -> str:
    units = locale.units
    adj = vocab_for(locale).dc_noun.replace(" ", "-")
    radius = u.radius_words(units)
    tail = (
        f" {_beyond_sentence(beyond, geo, units)}" if beyond is not None and geo is not None else ""
    )
    if not engine:
        return (
            f"No {adj} facility within {radius} of this address is listed in PeeringDB "
            "or OpenStreetMap. Small server rooms inside offices are not in either database." + tail
        )
    nearest = engine[0]
    operators = []
    for f in engine:
        if f.operator_known and f.operator not in operators:
            operators.append(f.operator)
    who = ", ".join(operators[:4]) + (" and others" if len(operators) > 4 else "")
    parts = [
        f"{len(engine)} {adj} {'facility is' if len(engine) == 1 else 'facilities are'} "
        f"within {radius} of this address according to PeeringDB and OpenStreetMap: "
        f"{live} operating{f' and {building} under construction' if building else ''}."
    ]
    parts.append(
        f"The nearest is {nearest.name}, {u.dist(nearest.distance_km, units)} away"
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
    locale: Locale = US_LOCALE,
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

    v = vocab_for(locale)
    units = locale.units
    img = truth.imagery
    if img is None:
        if geo.country != "US":
            section["gap"] = " ".join(
                filter(
                    None,
                    [
                        section.get("gap"),
                        f"Aerial imagery is not indexed for {v.country_name} yet, so new "
                        "construction here comes only from OpenStreetMap tags, planning "
                        "decisions and public announcements.",
                    ],
                )
            )
        elif geo.county:
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
            section["summary"] = _coming_summary(None, section["facilities"], locale)
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
    section["summary"] = _coming_summary(img, section["facilities"], locale)
    section["status"] = "measured"
    section["model"] = img.model
    section["confidence"] = 0.8 if img.counted else 0.7
    section["gap"] = (
        "Roofs are measured from public aerial imagery; what is inside them is not. A large "
        f"roof in no database is counted only when it adjoins a listed {v.dc_noun}."
    )
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "coming"])
    acres = img.new_acres
    adj = v.dc_noun.replace(" ", "-")
    if acres > 0:
        card_line = f"{u.area(acres, units)} of new {adj} roof since {img.then.year}"[:80]
    elif not card_line:
        card_line = f"No new large {adj} roof since {img.then.year} imagery"
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


def _coming_summary(
    img: ImageryResult | None, facilities: list[dict[str, Any]], locale: Locale = US_LOCALE
) -> str:
    v = vocab_for(locale)
    units = locale.units
    radius = u.radius_words(units)
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
                what.append(f"{exp} expansion{'s' if exp != 1 else ''} of a listed {v.dc_noun}")
            nearest = counted[0]
            parts.append(
                f"Between the {then} and {now} aerial imagery, {' and '.join(what)} appeared "
                f"within {radius}, about {u.area(img.new_acres, units)} of roof in all. The "
                f"nearest is {nearest.label}, {u.dist(nearest.distance_km, units)} away."
            )
        else:
            parts.append(
                f"Between the {then} and {now} aerial imagery, no new large roof appeared within "
                f"{radius} next to a listed {v.dc_noun}."
            )
        if other:
            parts.append(
                f"{len(other)} other large roof{'s' if len(other) != 1 else ''} went up in that "
                f"time with no {v.dc_noun} listed nearby; the imagery cannot say what they are."
            )
    rejected = [f for f in facilities if f.get("status") == "rejected"]
    announced = [f for f in facilities if f.get("status") in ("announced", "under_construction")]
    for f in rejected:
        parts.append(
            f"{f['name']}{' (' + f['codename'] + ')' if f.get('codename') else ''}, "
            f"{u.dist_whole(f['distance_km'], units)} away, was voted down or withdrawn."
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
    locale: Locale = US_LOCALE,
) -> tuple[dict[str, Any], str | None]:
    """The last indexed hearing for this county, quoted verbatim from the
    transcript of the official recording. Without an index the model's
    recollection stands, and the gap says so."""
    h = truth.hearing
    adj = vocab_for(locale).dc_noun.replace(" ", "-")
    if h is None:
        if geo.country != "US":
            fallback = f"Meetings of {geo.county} are not indexed yet" if geo.county else None
        else:
            fallback = (
                f"Hearings for {geo.county} County are not indexed yet (docs/counties.md)"
                if geo.county
                else None
            )
        why = truth.hearing_note or fallback
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
        else f" No upcoming {adj} hearing is listed for this body."
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
    locale: Locale = US_LOCALE,
) -> tuple[dict[str, Any], str | None]:
    p = truth.best_price
    assert p is not None
    v = vocab_for(locale)
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
        section["summary"] = _bill_summary(truth, geo, change, v)
        section["gap"] = " ".join(filter(None, [section.get("gap"), *truth.notes])) or None
    section["price"] = price
    section["status"] = "modelled"
    section["confidence"] = 0.85 if p.scope == "utility" else 0.8
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "your_bill"])
    if not card_line:
        sign = "+" if change >= 0 else "−"
        cost = u.money_abs(change, p.currency)
        if p.scope == "country":
            home = f"home in {p.label or v.country_name}"
        else:
            home = f"{geo.state} home"
        card_line = f"{sign}{cost}/mo for a typical {home} vs 2 yrs ago"
    return section, card_line


def _period(p: PriceSeries) -> tuple[str, str]:
    """('calendar 2024', 'calendar 2022'), ('the twelve months to August 2026', 'the
    twelve months ending 24 months earlier') or, for a semiannual series, ('the first
    half of 2026', 'the first half of 2024') from the source's own labels."""
    if p.granularity == "semiannual":
        return _half(p.period_now, p.latest), _half(
            p.period_then, (p.latest[0] - p.window_months // 12, p.latest[1])
        )
    if p.scope == "utility":
        return f"calendar {p.latest[0]}", f"calendar {p.latest[0] - p.window_months // 12}"
    month = f"{MONTHS[p.latest[1] - 1]} {p.latest[0]}"
    return f"the twelve months to {month}", "the twelve months ending 24 months earlier"


def _half(label: str | None, latest: tuple[int, int]) -> str:
    """'2026-S1' -> 'the first half of 2026'; without a label, from (year, month)."""
    if label and len(label) == 7 and label[4:6] == "-S" and label[:4].isdigit():
        return half_year(int(label[:4]), 6 if label[6] == "1" else 12)
    return half_year(latest[0], latest[1])


def _own_claims(p: PriceSeries) -> list[tuple[str, str, str, str]]:
    """A provider that writes its own claim (Eurostat): the price claim, then
    the typical-consumption claim with its own page. Nothing else."""
    out = [(p.claim_text or "", p.source_url, p.source_title, p.quote or "")]
    if p.kwh_claim_text and p.kwh_source_url:
        out.append(
            (
                p.kwh_claim_text,
                p.kwh_source_url,
                p.kwh_source_title or p.kwh_source_url,
                p.kwh_quote or "",
            )
        )
    return out


def _price_claims(truth: GroundTruth, geo: GeocodeResult) -> list[tuple[str, str, str, str]]:
    out = []
    up = truth.utility_price
    if up and up.claim_text:
        out.extend(_own_claims(up))
    elif up:
        now, then = _period(up)
        out.append(
            (
                f"EIA-861 sales to ultimate customers: {up.label} residential revenue over sales "
                f"in {geo.state} was {up.rate_now * 100:.2f} cents per kWh in {now} and "
                f"{up.rate_then * 100:.2f} cents in {then}, at {up.typical_kwh_month:.0f} kWh a "
                "month per customer.",
                up.source_url,
                up.source_title,
                f"Sales_Ult_Cust_{up.latest[0]}",
            )
        )
    s = truth.price
    if s and s.claim_text:
        out.extend(_own_claims(s))
    elif s:
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


def _bill_summary(
    truth: GroundTruth, geo: GeocodeResult, change: float, v: Vocab = US_VOCAB
) -> str:
    p = truth.best_price
    assert p is not None
    now, then = _period(p)
    word = "more" if change >= 0 else "less"
    if p.scope == "utility" and truth.utility:
        who = f"{truth.utility.name} customers"
    elif p.scope == "country":
        who = f"homes in {p.label or v.country_name}"
    else:
        who = f"homes in {geo.state}"
    text = (
        f"For {who}, the average home electricity price was {u.rate_words(p.rate_now, p.currency)} "
        f"in {now}, against {u.rate_short(p.rate_then, p.currency)} in {then}, a change of "
        f"{p.trend_pct:+.1f}%. For a typical home here using about {p.typical_kwh_month:.0f} kWh "
        f"a month, that is about {u.money_abs(change, p.currency)} a month {word}."
    )
    s = truth.price
    if p.scope == "utility" and s is not None:
        s_now, _ = _period(s)
        where = (
            f"Nationally, {s.label or v.country_name}"
            if s.scope == "country"
            else f"Statewide, {geo.state}"
        )
        text += (
            f" {where} averaged {u.rate_short(s.rate_now, s.currency)} in {s_now}, "
            f"{s.trend_pct:+.1f}% over two years."
        )
    return text + (v.no_dc_statement or "")


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
        _engine_claim(
            "protection", t.summary, t.url, t.title, t.quote or "", len(claims) + 1, now_iso
        )
    )
    section["tariff"] = {
        "large_load_tariff": t.status,
        "name": t.name,
        "protects_households": t.protects_households,
        "docket": t.docket,
    }
    # Engine-owned and written only when it is not a tariff: US briefs are unchanged.
    if t.kind != "tariff":
        section["tariff"]["kind"] = t.kind
    stated_aim = t.kind == "connection_policy" and t.protects_households is False
    lead = f"{t.lead} {CONNECTION_POLICY_AIM}" if stated_aim else t.lead
    section["summary"] = f"{lead} {t.summary}"
    section["status"] = "reported"
    section["confidence"] = max(float(section.get("confidence") or 0.0), 0.8)
    section["sources"] = _distinct_sources([c for c in claims if c["section"] == "protection"])
    if t.status == "in_force" and stated_aim:
        card_line = CONNECTION_POLICY_CARD
    elif t.status == "in_force" and t.protects_households:
        card_line = f"Bill shield: {t.name or 'large-load tariff'} in force"[:80]
    elif t.status == "proposed":
        card_line = "Bill shield: large-load tariff proposed, not approved"
    elif t.status == "none_found":
        card_line = "No large-load tariff found for this utility"
    return section, card_line


# --- the strip -------------------------------------------------------------------


def _says_none(line: dict[str, Any]) -> bool:
    """A model line that only reports a gap: nothing published, nothing nearby.
    A line that carries a figure says something, whatever else it says, and
    is never folded."""
    text = line["text"]
    return bool(_SAYS_NONE.search(text)) and not re.search(r"\d", text)


def _ask_words(truth: GroundTruth | None, geo: GeocodeResult, v: Vocab) -> list[str]:
    """Who to ask when operators publish nothing: the county, the utility."""
    out: list[str] = []
    if geo.county:
        out.append(v.county_words(geo.county))
    if truth is not None and truth.utility is not None:
        out.append(truth.utility.name)
    return out


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _quiet_line(
    quiet: list[dict[str, Any]],
    own: list[dict[str, Any]],
    truth: GroundTruth | None,
    geo: GeocodeResult,
    locale: Locale,
) -> dict[str, Any]:
    """One line for every topic the model could only call not public."""
    v = vocab_for(locale)
    words = _QUIET_WORDS.get(locale.country, _QUIET_WORDS["US"])
    topics = [t for t in _QUIET_TOPICS if any(line["topic"] == t for line in quiet)]
    what = _and([words[t] for t in topics])
    grounded_empty = truth is not None and truth.facilities is not None and not truth.facilities
    if grounded_empty:
        text = (
            f"No {v.dc_noun} within {u.radius_words(locale.units)}, so there is nothing to "
            f"report on {what}."
        )
    else:
        ask = _ask_words(truth, geo, v)
        text = f"Not public: {what}. The operators near you do not publish it"
        text += f"; {_and(ask)} {'are' if len(ask) > 1 else 'is'} where to ask." if ask else "."
    return {
        "text": text,
        "topic": "other",
        "status": "unavailable",
        "confidence": max(0.0, min(1.0, min(float(line["confidence"]) for line in quiet))),
        "sources": _distinct_sources(own),
    }


def _strip(
    sections: dict[str, Any],
    house: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    now_iso: str,
    truth: GroundTruth | None,
    locale: Locale = US_LOCALE,
    geo: GeocodeResult | None = None,
) -> list[dict[str, Any]]:
    """The bill sentence first, the engine's noise sentence when it has a
    facility list, then the model's lines, each `reported` with its claims.
    Lines that only say a topic is not public fold into one short line."""
    out: list[dict[str, Any]] = []
    quiet: list[dict[str, Any]] = []
    quiet_claims: list[dict[str, Any]] = []
    bill = bill_house_line(sections, locale=locale)
    if bill:
        out.append(bill)
    engine_noise = noise_house_line(truth, now_iso, locale=locale) if truth is not None else None
    if engine_noise:
        out.append(engine_noise)
    engine_land = land_house_line(truth, now_iso, locale=locale) if truth is not None else None
    if engine_land:
        out.append(engine_land)
    grounded = truth.facilities if truth is not None else None
    grounded_empty = grounded is not None and not grounded
    for line in house:
        # With a facility list the noise line is the engine's, written only
        # where it says something; the model's never stands in for it.
        if line["topic"] == "noise" and (engine_noise or grounded is not None):
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
        if line["topic"] in _QUIET_TOPICS and _says_none(line):
            quiet.append(line)
            quiet_claims.extend(own)
            continue
        out.append(
            {
                "text": line["text"],
                "topic": line["topic"],
                "status": "reported",
                "confidence": max(0.0, min(1.0, float(line["confidence"]))),
                "sources": _distinct_sources(own),
            }
        )
    if quiet and geo is not None:
        out.append(_quiet_line(quiet, quiet_claims, truth, geo, locale))
    out.sort(key=lambda line: _TOPIC_ORDER.get(line["topic"], 99))
    return out


# --- the glance: one entry per concern, for the tiles -----------------------------


def _entry(
    status: str,
    value: str | None,
    sub: str | None,
    text: str | None,
    confidence: float,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": status,
        "value": value,
        "sub": sub,
        "text": text,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "sources": list(sources),
    }


def _glance(
    sections: dict[str, Any],
    strip: list[dict[str, Any]],
    house: list[dict[str, Any]],
    truth: GroundTruth | None,
    headline: dict[str, Any],
    geo: GeocodeResult,
    now_iso: str,
    locale: Locale,
) -> dict[str, Any]:
    """What each tile on the brief page shows: a number where the engine has
    one (bill range, facility count, distance, acres), the model's sentence
    where it wrote one, and Not public with who to ask where nobody publishes.
    Everything here is derived from the sections and the strip: no new claim."""
    v = vocab_for(locale)
    units = locale.units
    radius = u.radius_words(units)
    by_topic = {line["topic"]: line for line in reversed(strip)}
    raw = {line["topic"]: line for line in reversed(house)}
    grounded = truth is not None and truth.facilities is not None
    grounded_empty = grounded and not truth.facilities  # type: ignore[union-attr]
    out: dict[str, Any] = {}

    # The bill: the hero's range, with the strip's own sentence behind it.
    bill = sections.get("your_bill") or {}
    span = headline.get("ai_rent_range_usd_per_month")
    bill_line = by_topic.get("bill")
    if span is not None and bill_line is not None:
        price = bill.get("price") or {}
        cur = str(price.get("currency") or locale.currency)
        lo, hi = float(span[0]), float(span[1])
        same_sign = (lo >= 0) == (hi >= 0)
        value = f"{u.money(lo, cur)} to {u.money_abs(hi, cur) if same_sign else u.money(hi, cur)}"
        now, then = period_words(price)
        when = f"{now[3:]} vs {then[3:]}" if now else "vs two years ago"
        out["bill"] = _entry(
            "modelled",
            value,
            f"a month for a typical home, {when}",
            bill_line["text"],
            bill_line["confidence"],
            bill_line["sources"],
        )
    else:
        out["bill"] = _entry(
            "unavailable",
            None,
            f"No household price series for this {v.utility_word}",
            None,
            0.0,
            [],
        )

    # Electricity: how many are on the grid, and how near the nearest is.
    grid = sections.get("on_your_grid") or {}
    facilities = [f for f in grid.get("facilities") or [] if f.get("status") != "rejected"]
    nearest_km = min((float(f["distance_km"]) for f in facilities), default=None)
    if grid.get("status") == "unavailable":
        out["grid"] = _entry(
            "unavailable", None, "The facility databases did not answer", None, 0.0, []
        )
    else:
        sub = (
            f"within {radius}, nearest {u.dist(nearest_km, units)}"
            if nearest_km is not None
            else f"none within {radius}"
        )
        out["grid"] = _entry(
            grid["status"],
            str(len(facilities)),
            sub,
            grid.get("summary"),
            grid.get("confidence", 0.0),
            grid.get("sources") or [],
        )

    # Noise: the distance, always; the sentence only where it says something.
    if grounded:
        nearest = truth.nearest  # type: ignore[union-attr]
        noise_line = by_topic.get("noise")
        if nearest is None:
            out["noise"] = _entry(
                "measured",
                "None",
                f"nothing within {radius} to hear",
                noise_line["text"] if noise_line else None,
                0.8,
                [],
            )
        else:
            miles = nearest.distance_km * KM_TO_MI
            if noise_line is not None and noise_line["status"] == "measured":
                sub = "came up at a public meeting"
            elif miles < NOISE_SENTENCE_MI:
                sub = "can be heard outdoors, especially at night"
            elif miles < 1.5:
                sub = "unlikely to carry over neighborhood sound"
            else:
                sub = "too far to hear from your house"
            if units != "us":
                sub = sub.replace("neighborhood", "neighbourhood")
            out["noise"] = _entry(
                noise_line["status"] if noise_line else "modelled",
                u.dist(nearest.distance_km, units),
                f"to {nearest.name}, {sub}",
                noise_line["text"] if noise_line else None,
                noise_line["confidence"]
                if noise_line
                else noise_at(nearest.distance_km).confidence,
                noise_line["sources"]
                if noise_line
                else [
                    {
                        "title": nearest.source_title,
                        "url": nearest.source_url,
                        "retrieved_at": now_iso,
                        "quote": nearest.name,
                    }
                ],
            )
    elif by_topic.get("noise"):
        line = by_topic["noise"]
        out["noise"] = _entry(
            line["status"], None, None, line["text"], line["confidence"], line["sources"]
        )

    # Land: what the aerial photos measured, else what the model wrote.
    img = truth.imagery if truth is not None else None
    land_line = by_topic.get("land")
    if img is not None and land_line is not None and land_line["status"] == "measured":
        then, now = img.vintages
        if img.counted:
            value = u.area(img.new_acres, units)
            sub = f"of new roof, {then} to {now} photos"
        else:
            value = None
            sub = f"no new roof in the {then} and {now} photos"
        out["land"] = _entry(
            "measured", value, sub, land_line["text"], land_line["confidence"], land_line["sources"]
        )

    # Water, taxes, air, and land without imagery: the model's line, or Not public.
    ask = _ask_words(truth, geo, v)
    for topic in ("water", "land", "taxes", "air"):
        if topic in out:
            continue
        line = by_topic.get(topic)
        if line is not None and line["status"] != "unavailable":
            out[topic] = _entry(
                line["status"], None, None, line["text"], line["confidence"], line["sources"]
            )
            continue
        quiet = raw.get(topic)
        if grounded_empty:
            # Nothing nearby is a measured fact, not a gap in what is published.
            out[topic] = _entry(
                "measured",
                "None",
                f"no {v.dc_noun} within {radius}",
                None,
                grid.get("confidence", 0.8),
                grid.get("sources") or [],
            )
            continue
        sub = f"Ask {_and(ask)}" if ask else "Not published by the operators near you"
        # The page the model cited for the gap sits on the strip's folded line.
        out[topic] = _entry(
            "unavailable", None, sub, None, float(quiet["confidence"]) if quiet else 0.0, []
        )
    return {t: out[t] for t in GLANCE_TOPICS if t in out}


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
