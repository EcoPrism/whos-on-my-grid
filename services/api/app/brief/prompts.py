"""Prompts for the five section drafts and the claim verifier.

The rules here are the product's honesty rules in prompt form. Nothing in a
prompt may ask the model to assert causation or to fill a gap with a guess.
"""

from app.geocode import GeocodeResult

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
        "Output only the JSON object."
    )


def section_prompt(section_id: str, geo: GeocodeResult) -> str:
    title, question = SECTION_QUESTIONS[section_id]
    county = f"{geo.county} County" if geo.county else "county not known"
    return (
        f"Section: {title}\n"
        f"Question this section answers: {question}\n\n"
        f"Address (street and city only): {geo.display}\n"
        f"Coordinates: {geo.lat:.4f}, {geo.lon:.4f}\n"
        f"State: {geo.state}. {county}. ZIP {geo.zip}.\n"
        "Serving utility: not known (say which one you believe serves this address if you are "
        "confident, as a claim with a source).\n"
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


def house_prompt(geo: GeocodeResult, summaries: dict[str, str]) -> str:
    county = f"{geo.county} County" if geo.county else "county not known"
    ctx = "\n".join(
        f"- {SECTION_QUESTIONS[sid][0]}: {text}" for sid, text in summaries.items() if text
    )
    return (
        f"Address (street and city only): {geo.display}\n"
        f"State: {geo.state}. {county}. ZIP {geo.zip}.\n\n"
        "What the five sections of the brief already say:\n"
        f"{ctx or '- (no section could be drafted)'}\n\n"
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
