"""Prompts for the five section drafts and the claim verifier.

The rules here are the product's honesty rules in prompt form. Nothing in a
prompt may ask the model to assert causation or to fill a gap with a guess.
"""

from app.geocode import GeocodeResult
from app.ground.facilities import compass
from app.ground.types import GroundTruth

KM_TO_MI = 0.621371
MAX_FACILITY_LINES = 25

SECTION_QUESTIONS = {
    "on_your_grid": (
        "On your grid",
        "Which data-center facilities are within five miles of this address, who operates them "
        "(including the operator behind any codename), their status (live or under_construction), "
        "their approximate load in MW with the basis for that number, and whether they are likely "
        "to share a transmission substation with this neighborhood (an inference from distance "
        "and public substation locations; say so, never state it as fact). Put announced-only "
        "campuses in the Coming section, not here.",
    ),
    "coming": (
        "Coming",
        "Which data-center campuses within five miles have been announced, permitted or filed for "
        "but are not yet live: name, codename if filed under one, operator, status "
        "'announced' or 'under_construction', filed MW. Leave `construction` empty: aerial "
        "imagery is not available in this mode, say so in `gap`.",
    ),
    "your_bill": (
        "Your bill",
        "What has this state's average residential electricity price (USD per kWh, as a decimal "
        "such as 0.151) done over the last 24 months, what does that mean per month for a typical "
        "home in this state (use the state's typical household kWh per month), and what do the "
        "people who set rates (the state commission, the regional market monitor, the utility) "
        "say about why. `attribution` must be a quote from a regulator, market monitor or "
        "utility, with its source in claims, or null. Never attribute the change yourself.",
    ),
    "protection": (
        "Protection",
        "Does this state or this utility have a large-load tariff or rule that shields residential "
        "customers from paying for data-center grid build-out (for example minimum-demand "
        "charges, minimum contract terms, collateral requirements for customers above a MW "
        "threshold)? In force, proposed, or none found. Name, docket number and whether it "
        "protects households, each with the page that says so. The first word of `summary` is "
        "the answer a resident wants: 'Yes', 'Partly', 'No', 'Not yet' or 'Not known', followed "
        "by what the rule does and what it leaves on household bills.",
    ),
    "hearing": (
        "Hearing",
        "When is the next county board or state commission hearing or vote that concerns "
        "data-center development or its grid cost near this address, which body, what subject, "
        "and what was said at the most recent such meeting, by whom (role, name if public). Only "
        "quote what you can cite to an official minutes or recording page. Dates as YYYY-MM-DD.",
    ),
}


# When the engine has measured the facts, the question changes: the model
# writes around the data instead of recalling it.
GROUNDED_QUESTIONS = {
    "on_your_grid": (
        "On your grid",
        "The facility list in the facts block is the answer to this section and will be used as "
        "given: do not add, remove, rename or move a facility. Write the summary from it: the "
        "first sentence says how many are within five miles and names the nearest with its "
        "distance; then who operates them. For a listed facility you may add `estimated_mw` "
        "with its `mw_basis`, the operator behind a codename, and the `operator` of an entry "
        "whose operator is 'not recorded' when you know who runs those buildings, each backed by "
        "a claim with a real source; return in `facilities` only the entries you annotate (same "
        "`name`, copied exactly), or an empty array. `shares_substation` is an inference from "
        "distance; say so if you set it.",
    ),
    "coming": (
        "Coming",
        "Facilities in the facts block are already on the grid; do not repeat them. List "
        "data-center campuses within five miles that are announced, permitted or filed for but "
        "not in that list, and campuses that were rejected or withdrawn (status 'rejected', with "
        "the vote or decision as a claim). Name, codename if filed under one, operator, filed MW. "
        "Leave `construction` empty: aerial imagery is not available in this mode; say so in "
        "`gap`.",
    ),
    "your_bill": (
        "Your bill",
        "The price figures in the facts block are measured (EIA-861M) and will be used as given; "
        "repeat them in `price` exactly and do not substitute remembered numbers. Write the "
        "summary around them for the serving utility named: direction, the monthly change for a "
        "typical home, and what the people who set rates (the state commission, the regional "
        "market monitor, the utility) say about why. `attribution` must be a quote from a "
        "regulator, market monitor or utility, with its source in claims, or null. Never "
        "attribute the change yourself.",
    ),
}


def ground_block(truth: GroundTruth | None, geo: GeocodeResult) -> str:
    """What the engine measured, for the model to write around."""
    if truth is None:
        return ""
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
    if truth.imagery:
        img = truth.imagery
        then, now = img.vintages
        counted = img.counted
        lines.append(
            f"- Aerial imagery, SAM 3.1 on USDA NAIP {then} vs {now}: {len(counted)} new or "
            f"expanded large roof{'s' if len(counted) != 1 else ''} beside listed data centers "
            "within five "
            f"miles, about {img.new_acres:.0f} acres"
            + (
                f" (nearest {counted[0].label}, {counted[0].distance_km * KM_TO_MI:.1f} mi)."
                if counted
                else "."
            )
            + " The Coming section already carries these; do not repeat or re-measure them."
        )
    for d in truth.decisions:
        lines.append(
            f"- On the public record: {d.project}"
            + (f" ({d.codename})" if d.codename and d.codename != d.project else "")
            + f" was {d.status} by the {d.body} on {d.date}. Already listed in Coming; do not add "
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
    return "\n".join(lines) + "\n\n"


def system_prompt(now_iso: str) -> str:
    return (
        "You are drafting one section of a public-interest brief that tells a US resident what "
        "data-center load is doing to their local electricity grid and bill. You draft from your "
        "own knowledge; you have no search tool.\n\n"
        "Rules:\n"
        "1. Never state or imply that a data center caused a change in anyone's bill. Only quote "
        "who attributes what, and cite them.\n"
        "2. Say 'not known' rather than guess. Put what you could not find out, and why, "
        "in `gap`.\n"
        "3. Every claim needs a real, publicly reachable URL you are confident exists: the "
        "utility, the state commission, the county, EIA, PeeringDB, a reputable newspaper. Give "
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
        "output.\n"
        "Output only the JSON object."
    )


def section_prompt(section_id: str, geo: GeocodeResult, truth: GroundTruth | None = None) -> str:
    grounded = truth is not None and section_id in GROUNDED_QUESTIONS
    if grounded and section_id == "your_bill" and truth.best_price is None:  # type: ignore[union-attr]
        grounded = False
    if grounded and section_id in ("on_your_grid", "coming") and truth.facilities is None:  # type: ignore[union-attr]
        grounded = False
    title, question = (GROUNDED_QUESTIONS if grounded else SECTION_QUESTIONS)[section_id]
    if section_id == "coming" and truth is not None and truth.imagery is not None:
        question = question.replace(
            "Leave `construction` empty: aerial imagery is not available in this mode; say so in "
            "`gap`.",
            "Leave `construction` empty: the engine fills it from the imagery measurement in "
            "the facts block.",
        )
    county = f"{geo.county} County" if geo.county else "county not known"
    utility = (
        f"Serving utility: {truth.utility.name} (from the HIFLD service-territory map).\n"
        if truth is not None and truth.utility
        else "Serving utility: not known (say which one you believe serves this address if you "
        "are confident, as a claim with a source).\n"
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


def house_system_prompt(now_iso: str) -> str:
    return (
        "You are writing the 'What this means at your house' strip of a public-interest brief: "
        "two or three plain-language sentences a resident would screenshot and send to a "
        "neighbor. You draft from your own knowledge; you have no search tool.\n\n"
        "Rules:\n"
        "1. Do not write about the electricity bill. That sentence is computed separately from "
        "the price data, and you must never attribute a bill change to anything.\n"
        "2. Pick the topics that matter most at this address, in the order people feel them: "
        "water (permitted withdrawals, drinking vs reclaimed), noise (distance to the nearest "
        "building, what residents have said on the record), land (acres of field or forest now "
        "roof), air (permitted diesel backup generators), taxes (the other side: the share of "
        "local tax revenue data centers pay and what the county says it does for residential "
        "rates). Include the tax side whenever you can cite it; the brief must not read as a "
        "leaflet.\n"
        "3. Plain words, no jargon, no acronyms. Compare every number to something a person "
        "knows: homes, miles, football fields.\n"
        "4. Say 'not public' or 'not known' rather than guess. Noise is modeled from distance "
        "unless there is a measurement; keep its confidence low.\n"
        "5. Every number needs a claim with a real, publicly reachable URL (water authority, "
        "county budget, state air permits, county minutes, a reputable newspaper). An "
        "independent model will fetch each URL and check it; invented sources are shown to the "
        "reader as such.\n"
        "6. Never invent an operator, a permit, a figure or a quote.\n"
        f"7. Today's date is {now_iso[:10]}. Treat what you remember as possibly out of date.\n"
        "Output only the JSON object."
    )


def house_prompt(
    geo: GeocodeResult, summaries: dict[str, str], truth: GroundTruth | None = None
) -> str:
    county = f"{geo.county} County" if geo.county else "county not known"
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
    return (
        f"{ground_block(truth, geo)}"
        f"Address (street and city only): {geo.display}\n"
        f"State: {geo.state}. {county}. ZIP {geo.zip}.\n\n"
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
