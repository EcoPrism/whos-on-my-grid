"""Prompts for the five section drafts and the claim verifier.

The rules here are the product's honesty rules in prompt form. Nothing in a
prompt may ask the model to assert causation or to fill a gap with a guess.

Every public function takes the region's `locale` (default the US). The US
prompts are byte-identical to those before regions (tests/test_us_golden.py);
another country gets its own words (app/brief/vocab.py) and units
(app/brief/units.py)."""

from app.brief import units as u
from app.brief.vocab import CONNECTION_POLICY_AIM, US_VOCAB, Vocab, vocab_for
from app.geocode import GeocodeResult
from app.ground.facilities import compass
from app.ground.types import GroundTruth, PriceSeries
from app.regions.locale import US_LOCALE, Locale

KM_TO_MI = u.KM_TO_MI
MAX_FACILITY_LINES = 25


def _section_questions(v: Vocab, units: u.Units) -> dict[str, tuple[str, str]]:
    adj = v.dc_noun.replace(" ", "-")  # "data-center", "data-centre"
    radius = u.radius_words(units)
    hood = "neighborhood" if v.neighbor == "neighbor" else "neighbourhood"
    return {
        "on_your_grid": (
            "On your grid",
            f"Which {adj} facilities are within {radius} of this address, who operates them "
            "(including the operator behind any codename), their status (live or "
            "under_construction), their approximate load in MW with the basis for that number, "
            "and whether they are likely to share a transmission substation with this "
            f"{hood} (an inference from distance and public substation locations; say so, never "
            "state it as fact). Put announced-only campuses in the Coming section, not here.",
        ),
        "coming": (
            "Coming",
            f"Which {adj} campuses within {radius} have been announced, permitted or filed for "
            "but are not yet live: name, codename if filed under one, operator, status "
            "'announced' or 'under_construction', filed MW. Leave `construction` empty: aerial "
            "imagery is not available in this mode, say so in `gap`.",
        ),
        "your_bill": ("Your bill", v.price_question),
        "protection": ("Protection", v.tariff_question),
        "hearing": ("Hearing", v.hearing_bodies),
    }


def _grounded_questions(v: Vocab, units: u.Units, source: str) -> dict[str, tuple[str, str]]:
    adj = v.dc_noun.replace(" ", "-")
    radius = u.radius_words(units)
    return {
        "on_your_grid": (
            "On your grid",
            "The facility list in the facts block is the answer to this section and will be used "
            "as given: do not add, remove, rename or move a facility. Write the summary from it: "
            f"the first sentence says how many are within {radius} and names the nearest with its "
            "distance; then who operates them. For a listed facility you may add `estimated_mw` "
            "with its `mw_basis`, the operator behind a codename, and the `operator` of an entry "
            "whose operator is 'not recorded' when you know who runs those buildings, each backed "
            "by a claim with a real source; return in `facilities` only the entries you annotate "
            "(same `name`, copied exactly), or an empty array. `shares_substation` is an "
            "inference from distance; say so if you set it.",
        ),
        "coming": (
            "Coming",
            "Facilities in the facts block are already on the grid; do not repeat them. List "
            f"{adj} campuses within {radius} that are announced, permitted or filed for but "
            "not in that list, and campuses that were rejected or withdrawn (status 'rejected', "
            "with the vote or decision as a claim). Name, codename if filed under one, operator, "
            "filed MW. Leave `construction` empty: aerial imagery is not available in this mode; "
            "say so in `gap`.",
        ),
        "your_bill": (
            "Your bill",
            f"The price figures in the facts block are measured ({source}) and will be used as "
            "given; repeat them in `price` exactly and do not substitute remembered numbers. "
            f"Write the summary around them for the serving {v.utility_word} named: direction, "
            "the monthly change for a typical home, and what the people who set rates "
            f"({v.regulators}) say about why. `attribution` must be a quote from a regulator, "
            f"market monitor or {v.utility_word}, with its source in claims, or null. Never "
            "attribute the change yourself.",
        ),
    }


SECTION_QUESTIONS = _section_questions(US_VOCAB, "us")

# When the engine has measured the facts, the question changes: the model
# writes around the data instead of recalling it.
GROUNDED_QUESTIONS = _grounded_questions(US_VOCAB, "us", "EIA-861M")


def _questions(
    locale: Locale, grounded: bool, truth: GroundTruth | None
) -> dict[str, tuple[str, str]]:
    if locale.country == "US":
        return GROUNDED_QUESTIONS if grounded else SECTION_QUESTIONS
    v = vocab_for(locale)
    if not grounded:
        return _section_questions(v, locale.units)
    p = truth.best_price if truth is not None else None
    source = _price_source(p) if p is not None else "public data"
    return {**_section_questions(v, locale.units), **_grounded_questions(v, locale.units, source)}


def _price_source(p: PriceSeries) -> str:
    """'Eurostat nrg_pc_204' from the provider's claim, else the source title."""
    if p.claim_text:
        return p.claim_text.split(",", 1)[0]
    return p.source_title


def _usable(p: PriceSeries | None) -> PriceSeries | None:
    """A price series the brief can turn into a monthly change: it needs the
    typical consumption. Without it the bill is not measured."""
    return p if p is not None and p.typical_kwh_month is not None else None


def ground_block(
    truth: GroundTruth | None, geo: GeocodeResult, *, locale: Locale = US_LOCALE
) -> str:
    """What the engine measured, for the model to write around."""
    if truth is None:
        return ""
    if locale.country != "US":
        return _ground_block_intl(truth, geo, locale)
    lines = ["Facts from the engine (public datasets, already checked; do not contradict them):"]
    if truth.utility:
        lines.append(
            f"- Serving utility at this point: {truth.utility.name} "
            f"({truth.utility.kind.lower()}; HIFLD service-territory map)."
        )
    else:
        lines.append("- Serving utility: not known.")
    if truth.facilities is None:
        lines.append("- Facility database: could not be reached for this brief.")
    elif not truth.facilities:
        lines.append(
            "- Facilities within five miles (PeeringDB + OpenStreetMap): none listed. Small "
            "server rooms inside offices are not in either database."
        )
    else:
        lines.append(
            f"- Facilities within five miles (PeeringDB + OpenStreetMap), nearest first, "
            f"{len(truth.facilities)} in all:"
        )
        for i, f in enumerate(truth.facilities[:MAX_FACILITY_LINES], start=1):
            lines.append(
                f"  {i}. {f.name} | {f.operator} | {f.status.replace('_', ' ')} | "
                f"{f.distance_km * KM_TO_MI:.1f} mi | {f.buildings} building"
                f"{'s' if f.buildings != 1 else ''} | {f.source_url}"
            )
        if len(truth.facilities) > MAX_FACILITY_LINES:
            lines.append(f"  ... and {len(truth.facilities) - MAX_FACILITY_LINES} more.")
    if truth.beyond_ring is not None:
        b = truth.beyond_ring
        lines.append(
            f"- Nearest campus with a known operator beyond the five-mile ring (searched to "
            f"ten miles): {b.name} | {b.operator} | {b.distance_km * KM_TO_MI:.1f} mi to the "
            f"{compass(geo.lat, geo.lon, b.lat, b.lon)} | {b.buildings} building"
            f"{'s' if b.buildings != 1 else ''} | {b.source_url}. Say it is beyond the ring; "
            f"never count it among the facilities within five miles."
        )
    if truth.utility_price:
        p = truth.utility_price
        change = (p.rate_now - p.rate_then) * p.typical_kwh_month
        lines.append(
            f"- Residential price for THIS utility ({p.label}), EIA-861 annual: "
            f"{p.rate_then * 100:.2f} cents/kWh in {p.latest[0] - p.window_months // 12} -> "
            f"{p.rate_now * 100:.2f} cents/kWh in {p.latest[0]}, {p.trend_pct:+.1f}%. Typical "
            f"home on this utility: {p.typical_kwh_month:.0f} kWh a month, so about "
            f"${change:+.0f} a month. This is the series used in `price`: rate_then "
            f"{p.rate_then}, rate_now {p.rate_now}, window {p.window_months} months."
        )
    if truth.price:
        p = truth.price
        change = (p.rate_now - p.rate_then) * p.typical_kwh_month
        used = (
            "This is the series used in `price`: " if not truth.utility_price else "Context only: "
        )
        lines.append(
            f"- Residential price, {geo.state} statewide, EIA-861M monthly "
            f"({p.data_status.lower()} data): {p.rate_then * 100:.2f} cents/kWh (twelve months "
            f"ending 24 months before {p.latest[0]}-{p.latest[1]:02d}) -> "
            f"{p.rate_now * 100:.2f} cents/kWh (twelve months "
            f"to {p.latest[0]}-{p.latest[1]:02d}), {p.trend_pct:+.1f}%. Typical home statewide: "
            f"{p.typical_kwh_month:.0f} kWh a month, so about ${change:+.0f} a month. {used}"
            f"rate_then {p.rate_then}, rate_now {p.rate_now}, window 24 months."
        )
    if truth.tariff:
        t = truth.tariff
        lines.append(
            f"- Large-load rule on record for this utility: {t.lead} {t.name or 'none'} "
            f"({t.status.replace('_', ' ')}{', docket ' + t.docket if t.docket else ''}): "
            f"{t.summary} Source: {t.url}"
        )
    _imagery_lines(lines, truth, "us", US_VOCAB)
    _record_lines(lines, truth)
    return "\n".join(lines) + "\n\n"


def _ground_block_intl(truth: GroundTruth, geo: GeocodeResult, locale: Locale) -> str:
    """The facts block outside the US: the same facts, in the region's units,
    currency and words, with the price series as its provider names it."""
    v = vocab_for(locale)
    units = locale.units
    radius = u.radius_words(units)
    lines = ["Facts from the engine (public datasets, already checked; do not contradict them):"]
    if truth.utility:
        lines.append(
            f"- Serving {v.utility_word} at this point: {truth.utility.name} "
            f"({truth.utility.kind}; {v.utility_map_phrase})."
        )
    else:
        lines.append(f"- Serving {v.utility_word}: not known.")
    if truth.facilities is None:
        lines.append("- Facility database: could not be reached for this brief.")
    elif not truth.facilities:
        lines.append(
            f"- Facilities within {radius} (PeeringDB + OpenStreetMap): none listed. Small "
            "server rooms inside offices are not in either database."
        )
    else:
        lines.append(
            f"- Facilities within {radius} (PeeringDB + OpenStreetMap), nearest first, "
            f"{len(truth.facilities)} in all:"
        )
        for i, f in enumerate(truth.facilities[:MAX_FACILITY_LINES], start=1):
            lines.append(
                f"  {i}. {f.name} | {f.operator} | {f.status.replace('_', ' ')} | "
                f"{u.dist_short(f.distance_km, units)} | {f.buildings} building"
                f"{'s' if f.buildings != 1 else ''} | {f.source_url}"
            )
        if len(truth.facilities) > MAX_FACILITY_LINES:
            lines.append(f"  ... and {len(truth.facilities) - MAX_FACILITY_LINES} more.")
    if truth.beyond_ring is not None:
        b = truth.beyond_ring
        lines.append(
            f"- Nearest campus with a known operator beyond {u.ring_words(units)} (searched to "
            f"{u.outer_words(units)}): {b.name} | {b.operator} | "
            f"{u.dist_short(b.distance_km, units)} to the "
            f"{compass(geo.lat, geo.lon, b.lat, b.lon)} | {b.buildings} building"
            f"{'s' if b.buildings != 1 else ''} | {b.source_url}. Say it is beyond the ring; "
            f"never count it among the facilities within {radius}."
        )
    p = _usable(truth.best_price)
    if p is not None:
        cur = p.currency.upper()
        change = (p.rate_now - p.rate_then) * p.typical_kwh_month
        then = p.period_then or "24 months earlier"
        now = p.period_now or f"{p.latest[0]}-{p.latest[1]:02d}"
        lines.append(
            f"- Household price, {p.label or geo.country}, {_price_source(p)} "
            f"({p.granularity}, {p.data_status.lower()} data): {cur} {p.rate_then:.4f} per kWh in "
            f"{then} -> {cur} {p.rate_now:.4f} per kWh in {now}, {p.trend_pct:+.1f}%. Typical "
            f"home: {p.typical_kwh_month:.0f} kWh a month, so about {cur} {change:+.0f} a month. "
            f"This is the series used in `price`: currency {cur}, rate_then {p.rate_then}, "
            f"rate_now {p.rate_now}, window {p.window_months} months."
        )
    elif truth.best_price is not None:
        lines.append(
            "- Household price: the series was read but no typical household consumption is on "
            "record, so the monthly change is not computed."
        )
    if truth.tariff:
        t = truth.tariff
        ref = f", reference {t.docket}" if t.docket else ""
        aim = (
            f" {CONNECTION_POLICY_AIM}"
            if t.kind == "connection_policy" and t.protects_households is False
            else ""
        )
        lines.append(
            f"- {v.tariff_label}: {t.name or 'none'} ({t.status.replace('_', ' ')}{ref}): "
            f"{t.summary}{aim} Source: {t.url}"
        )
    _imagery_lines(lines, truth, units, v)
    _record_lines(lines, truth)
    return "\n".join(lines) + "\n\n"


def _imagery_lines(lines: list[str], truth: GroundTruth, units: u.Units, v: Vocab) -> None:
    if not truth.imagery:
        return
    img = truth.imagery
    then, now = img.vintages
    counted = img.counted
    radius = u.radius_words(units)
    if units == "us":
        size = f"about {img.new_acres:.0f} acres"
    else:
        size = f"about {u.area(img.new_acres, units)}"
    lines.append(
        f"- Aerial imagery, SAM 3.1 on USDA NAIP {then} vs {now}: {len(counted)} new or "
        f"expanded large roof{'s' if len(counted) != 1 else ''} beside listed {v.dc_plural} "
        f"within {radius}, {size}"
        + (
            f" (nearest {counted[0].label}, {u.dist_short(counted[0].distance_km, units)})."
            if counted
            else "."
        )
        + " The Coming section already carries these; do not repeat or re-measure them."
    )


def _record_lines(lines: list[str], truth: GroundTruth) -> None:
    for d in truth.decisions:
        lines.append(
            f"- On the public record: {d.project}"
            + (f" ({d.codename})" if d.codename and d.codename != d.project else "")
            + f" was {d.status} by {d.decided_by or 'the ' + d.body} on {d.date}. Already listed "
            "in Coming; do not add "
            "it again, and never present it as coming."
        )
    if truth.hearing:
        h = truth.hearing
        lines.append(
            f"- Last indexed hearing: {h.body}, {h.date}, {h.subject}. The Hearing section is "
            "written from the transcript of the recording."
        )
    if truth.notes:
        lines.append("- Provider notes: " + " ".join(truth.notes))


def system_prompt(now_iso: str, *, locale: Locale = US_LOCALE) -> str:
    v = vocab_for(locale)
    return (
        f"You are drafting one section of a public-interest brief that tells {v.resident} what "
        f"{v.dc_noun.replace(' ', '-')} load is doing to their local electricity grid and bill. "
        "You draft from your own knowledge; you have no search tool.\n\n"
        "Rules:\n"
        f"1. Never state or imply that a {v.dc_noun} caused a change in anyone's bill. Only quote "
        "who attributes what, and cite them.\n"
        "2. Say 'not known' rather than guess. Put what you could not find out, and why, "
        "in `gap`.\n"
        "3. Every claim needs a real, publicly reachable URL you are confident exists: "
        f"{v.sources_hint}. Give "
        "a verbatim quote from that page when you can recall one; otherwise leave `quote` empty "
        "and lower the claim's confidence.\n"
        "4. Never invent an operator, a facility, a docket number, a date or a person. If you "
        "are not sure something exists, leave it out and say so in `gap`.\n"
        "5. A second, independent model will fetch every URL you cite and check your quote and "
        "claim against the page. An invented source will be shown to the reader as contradicted "
        "or unverifiable, with your name on it.\n"
        "6. `confidence` (0 to 1) is your own honest estimate for the section as a whole.\n"
        "7. `summary` is two or three plain-English sentences a resident can read. No jargon, no "
        "hedging filler, no causal claims.\n"
        f"8. Today's date is {now_iso[:10]}. Treat anything you remember as possibly out of date "
        "and say so where it matters.\n"
        "9. Keep it short. At most 8 claims, each under 200 characters, each a different fact. "
        "The summary is two or three sentences. Never copy the facts block back into the "
        "output.\n" + _units_rule(locale) + "Output only the JSON object."
    )


def _units_rule(locale: Locale) -> str:
    if locale.country == "US":
        return ""
    v = vocab_for(locale)
    return (
        f"10. Write for {v.resident}: distances in kilometres, areas in hectares, money in "
        f"{locale.currency}, Irish and British spelling ('{v.dc_noun}'), and the place as the "
        "address line names it (town, planning authority, county).\n"
    )


def section_prompt(
    section_id: str,
    geo: GeocodeResult,
    truth: GroundTruth | None = None,
    *,
    locale: Locale = US_LOCALE,
) -> str:
    grounded = truth is not None and section_id in GROUNDED_QUESTIONS
    if grounded and section_id == "your_bill" and _usable(truth.best_price) is None:  # type: ignore[union-attr]
        grounded = False
    if grounded and section_id in ("on_your_grid", "coming") and truth.facilities is None:  # type: ignore[union-attr]
        grounded = False
    title, question = _questions(locale, grounded, truth)[section_id]
    if section_id == "coming" and truth is not None and truth.imagery is not None:
        question = question.replace(
            "Leave `construction` empty: aerial imagery is not available in this mode; say so in "
            "`gap`.",
            "Leave `construction` empty: the engine fills it from the imagery measurement in "
            "the facts block.",
        )
    if locale.country == "US":
        county = f"{geo.county} County" if geo.county else "county not known"
        utility = (
            f"Serving utility: {truth.utility.name} (from the HIFLD service-territory map).\n"
            if truth is not None and truth.utility
            else "Serving utility: not known (say which one you believe serves this address if "
            "you are confident, as a claim with a source).\n"
        )
        return (
            f"Section: {title}\n"
            f"Question this section answers: {question}\n\n"
            f"{ground_block(truth, geo)}"
            f"Address (street and city only): {geo.display}\n"
            f"Coordinates: {geo.lat:.4f}, {geo.lon:.4f}\n"
            f"State: {geo.state}. {county}. ZIP {geo.zip}.\n"
            f"{utility}"
            "Radius of concern: five miles (8 km). Distances in km.\n\n"
            "Fill the section object. Every statement in `summary` and every number in the "
            "structured data must appear as a claim with its source."
        )
    v = vocab_for(locale)
    utility = (
        f"Serving {v.utility_word}: {truth.utility.name} (from the {v.utility_map_phrase}).\n"
        if truth is not None and truth.utility
        else f"Serving {v.utility_word}: not known (say which one you believe serves this "
        "address if you are confident, as a claim with a source).\n"
    )
    return (
        f"Section: {title}\n"
        f"Question this section answers: {question}\n\n"
        f"{ground_block(truth, geo, locale=locale)}"
        f"{v.address_label} {geo.display}\n"
        f"Coordinates (rounded): {geo.lat:.3f}, {geo.lon:.3f}\n"
        f"{v.place_line(geo)}\n"
        f"{utility}"
        f"Radius of concern: {u.radius_words(locale.units)}. Distances in km. Money in "
        f"{locale.currency}.\n\n"
        "Fill the section object. Every statement in `summary` and every number in the "
        "structured data must appear as a claim with its source."
    )


def house_system_prompt(now_iso: str, *, locale: Locale = US_LOCALE) -> str:
    v = vocab_for(locale)
    return (
        "You are writing the 'What this means at your house' strip of a public-interest brief: "
        "two or three plain-language sentences a resident would screenshot and send to a "
        f"{v.neighbor}. You draft from your own knowledge; you have no search tool.\n\n"
        "Rules:\n"
        "1. Do not write about the electricity bill. That sentence is computed separately from "
        "the price data, and you must never attribute a bill change to anything.\n"
        "2. Pick the topics that matter most at this address, in the order people feel them: "
        "water (permitted withdrawals, drinking vs reclaimed), noise (distance to the nearest "
        "building, what residents have said on the record), "
        f"{v.land}, {v.air_permits}, {v.taxes}. Include the tax side whenever you can cite it; "
        "the brief must not read as a leaflet.\n"
        "3. Plain words, no jargon, no acronyms. Compare every number to something a person "
        f"knows: {v.house_compare}.\n"
        "4. Say 'not public' or 'not known' rather than guess, in one short line with the page "
        "that shows the gap; do not pad it. Noise is modeled from distance unless there is a "
        "measurement; keep its confidence low.\n"
        "5. Every number needs a claim with a real, publicly reachable URL "
        f"({v.house_sources}). An "
        "independent model will fetch each URL and check it; invented sources are shown to the "
        "reader as such.\n"
        "6. Never invent an operator, a permit, a figure or a quote.\n"
        f"7. Today's date is {now_iso[:10]}. Treat what you remember as possibly out of date.\n"
        + _units_rule(locale).replace("10. ", "8. ")
        + "Output only the JSON object."
    )


def house_prompt(
    geo: GeocodeResult,
    summaries: dict[str, str],
    truth: GroundTruth | None = None,
    *,
    locale: Locale = US_LOCALE,
) -> str:
    ctx = "\n".join(
        f"- {SECTION_QUESTIONS[sid][0]}: {text}" for sid, text in summaries.items() if text
    )
    anchor = ""
    if truth is not None and truth.facilities is not None:
        anchor = (
            "Anchor every water, air, land and tax line to the facilities in the facts block, by "
            "name (for example 'the three facilities near you do not publish water use'). The "
            "noise line is written by the engine from distance; do not write one. If the facts "
            "block lists no facility, write only lines that say there is none to report.\n\n"
        )
    v = vocab_for(locale)
    return (
        f"{ground_block(truth, geo, locale=locale)}"
        f"{v.address_label} {geo.display}\n"
        f"{v.place_line(geo)}\n\n"
        "What the five sections of the brief already say:\n"
        f"{ctx or '- (no section could be drafted)'}\n\n"
        f"{anchor}"
        "Write the strip: two or three lines, each with its topic, your confidence and its claims."
    )


def verifier_system_prompt() -> str:
    return (
        "You are an independent fact checker. You are given one claim drafted by another model, "
        "the quote that model attributed to a source, and the text of that source page as "
        "fetched just now. Decide:\n"
        "- supported: the page supports the claim. The quote need not be exact, but the meaning "
        "must be there.\n"
        "- contradicted: the page says otherwise, or the quote is attributed to it but says "
        "something materially different.\n"
        "- unverifiable: the page does not address the claim, is the wrong page, or is too "
        "thin to tell.\n"
        "Judge only from the page text. Do not use your own knowledge to fill gaps. Give a "
        "one-sentence note a reader can understand. Output only the JSON object."
    )


def verifier_prompt(
    claim_text: str, quote: str, url: str, found_verbatim: bool, page_text: str
) -> str:
    return (
        f"Claim: {claim_text}\n"
        f"Attributed quote: {quote or '(none given)'}\n"
        f"Source URL: {url}\n"
        f"Quote found verbatim on the page: {'yes' if found_verbatim else 'no'}\n\n"
        f"Page text (may be truncated):\n---\n{page_text}\n---"
    )
