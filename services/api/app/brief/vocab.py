"""The words a brief uses for its place: who the reader is, who sets rates, what
a data center is called, how the address is described. One Vocab per country;
US_VOCAB reproduces the strings the engine wrote before regions, so US prompts
and briefs are byte-identical (tests/test_us_golden.py)."""

from collections.abc import Callable
from dataclasses import dataclass

from app.geocode import GeocodeResult
from app.regions.locale import Locale


@dataclass(frozen=True)
class Vocab:
    resident: str  # "a US resident" | "an Irish resident"
    regulators: str  # who sets rates, for the bill question
    sources_hint: str  # the kind of page a claim should cite
    tariff_question: str  # the Protection question
    hearing_bodies: str  # the Hearing question
    air_permits: str  # the strip's air topic
    price_question: str  # the Your bill question, without the facts block
    tariff_label: str  # "Large-load rule on record" | "Connection policy on record"
    address_label: str  # the line before geo.display in a prompt
    dc_noun: str  # "data center" | "data centre"
    dc_plural: str
    no_dc_statement: str | None  # appended to the bill summary; None: not said
    no_dc_headline: str | None  # appended to the strip's bill line; None: not said
    place_line: Callable[[GeocodeResult], str]  # "State: VA. Loudoun County. ZIP 20147."
    county_words: Callable[[str], str]  # "Loudoun County" | "Fingal"
    utility_map_phrase: str  # where the serving utility came from
    utility_word: str  # "utility" | "network operator"
    neighbor: str  # "neighbor" | "neighbour"
    house_sources: str  # the strip's example sources
    house_compare: str  # what the strip compares numbers to
    taxes: str  # the strip's other side
    land: str  # the strip's land topic
    country_name: str  # "the US" | "Ireland": where a national price applies
    outside_map: str | None  # the utility gap when the point is off the region's map


def _us_place(geo: GeocodeResult) -> str:
    county = f"{geo.county} County" if geo.county else "county not known"
    return f"State: {geo.state}. {county}. ZIP {geo.zip}."


def _ie_place(geo: GeocodeResult) -> str:
    county = geo.admin_county or "not known"
    authority = geo.county or "not known"
    key = f"Eircode routing key {geo.postal_code}" if geo.postal_code else "Eircode not known"
    return f"County: {county}. Planning authority: {authority}. {key}."


US_VOCAB = Vocab(
    resident="a US resident",
    regulators="the state commission, the regional market monitor, the utility",
    sources_hint="the utility, the state commission, the county, EIA, PeeringDB, a reputable "
    "newspaper",
    tariff_question=(
        "Does this state or this utility have a large-load tariff or rule that shields residential "
        "customers from paying for data-center grid build-out (for example minimum-demand "
        "charges, minimum contract terms, collateral requirements for customers above a MW "
        "threshold)? In force, proposed, or none found. Name, docket number and whether it "
        "protects households, each with the page that says so. The first word of `summary` is "
        "the answer a resident wants: 'Yes', 'Partly', 'No', 'Not yet' or 'Not known', followed "
        "by what the rule does and what it leaves on household bills."
    ),
    hearing_bodies=(
        "When is the next county board or state commission hearing or vote that concerns "
        "data-center development or its grid cost near this address, which body, what subject, "
        "and what was said at the most recent such meeting, by whom (role, name if public). Only "
        "quote what you can cite to an official minutes or recording page. Dates as YYYY-MM-DD."
    ),
    air_permits="air (permitted diesel backup generators)",
    price_question=(
        "What has this state's average residential electricity price (USD per kWh, as a decimal "
        "such as 0.151) done over the last 24 months, what does that mean per month for a typical "
        "home in this state (use the state's typical household kWh per month), and what do the "
        "people who set rates (the state commission, the regional market monitor, the utility) "
        "say about why. `attribution` must be a quote from a regulator, market monitor or "
        "utility, with its source in claims, or null. Never attribute the change yourself."
    ),
    tariff_label="Large-load rule on record for this utility",
    address_label="Address (street and city only):",
    dc_noun="data center",
    dc_plural="data centers",
    no_dc_statement=(
        " No regulator or utility statement tying the change to data centers was found."
    ),
    no_dc_headline=" No regulator has tied any of that to data centers.",
    place_line=_us_place,
    county_words=lambda name: f"{name} County",
    utility_map_phrase="HIFLD service-territory map",
    utility_word="utility",
    neighbor="neighbor",
    house_sources="water authority, county budget, state air permits, county minutes, a reputable "
    "newspaper",
    house_compare="homes, miles, football fields",
    taxes=(
        "taxes (the other side: the share of local tax revenue data centers pay and what the "
        "county says it does for residential rates)"
    ),
    land="land (acres of field or forest now roof)",
    country_name="the US",
    outside_map=None,
)

IE_VOCAB = Vocab(
    resident="an Irish resident",
    regulators="the Commission for Regulation of Utilities (CRU), ESB Networks, EirGrid",
    sources_hint="ESB Networks, EirGrid, the CRU, the planning authority, An Coimisiún Pleanála, "
    "Eurostat, the CSO, PeeringDB, a reputable newspaper",
    tariff_question=(
        "Does Ireland have a rule for connecting data centres to the electricity network, and "
        "does its stated purpose include keeping the cost of that build-out off household bills? "
        "In force, proposed, or none found. Name, decision reference and its stated aim, each "
        "with the page that says so. The first word of `summary` is the answer a resident wants: "
        "'Yes', 'Partly', 'No', 'Not yet' or 'Not known', followed by what the rule does and "
        "what it says about household bills."
    ),
    hearing_bodies=(
        "When is the next planning-authority meeting, An Coimisiún Pleanála decision or CRU "
        "consultation that concerns data-centre development or its grid cost near this address, "
        "which body, what subject, and what was said at the most recent such meeting, by whom "
        "(role, name if public). Only quote what you can cite to an official minutes, decision "
        "or recording page. Dates as YYYY-MM-DD."
    ),
    air_permits="air (EPA-licensed diesel or gas backup generators)",
    price_question=(
        "What has Ireland's average household electricity price (EUR per kWh, all taxes "
        "included, as a decimal such as 0.3871) done over the last 24 months, what does that "
        "mean per month for a typical home (use the CRU's typical household consumption), and "
        "what do the people who set rates (the CRU, ESB Networks, EirGrid) say about why. "
        "`attribution` must be a quote from a regulator or network operator, with its source in "
        "claims, or null. Never attribute the change yourself."
    ),
    tariff_label="Connection policy on record",
    address_label="Address (town and Eircode routing key only):",
    dc_noun="data centre",
    dc_plural="data centres",
    no_dc_statement=None,
    no_dc_headline=None,
    place_line=_ie_place,
    county_words=lambda name: name,
    utility_map_phrase="ESB Networks service-area map",
    utility_word="network operator",
    neighbor="neighbour",
    house_sources="Uisce Éireann, the local authority's budget, EPA licences, council minutes, a "
    "reputable newspaper",
    house_compare="homes, kilometres, football pitches",
    taxes=(
        "rates (the other side: the commercial rates data centres pay the local authority and "
        "what the council says it does with them)"
    ),
    land="land (hectares of field or forest now roof)",
    country_name="Ireland",
    outside_map="The point is outside the ESB Networks service map.",
)


# Plan 0.6: a connection policy whose stated purpose is not household costs. The
# protection lead stays "No." (the table's definition of protects_households); this
# sentence after it, and the facts block, say only what the rule states as its aim.
CONNECTION_POLICY_AIM = (
    "Its stated aim is grid constraints, security of supply and renewable targets, not household "
    "costs."
)


def vocab_for(locale: Locale) -> Vocab:
    """The country's words; any country without its own falls back to the US's."""
    return IE_VOCAB if locale.country == "IE" else US_VOCAB
