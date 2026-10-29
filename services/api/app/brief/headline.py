"""The headline number, the plain-language lines the engine writes itself, and
the share card, all derived from the assembled sections. No model call:
nothing here can introduce a causal claim."""

from typing import Any
from urllib.parse import urlparse

from app.brief.draft import DraftResult, SectionFailure
from app.geocode import GeocodeResult
from app.ground.types import GroundTruth
from app.scenario.model import noise_at
from app.schema import SECTION_IDS

Drafts = dict[str, DraftResult | SectionFailure]
Sections = dict[str, dict[str, Any]]

KM_TO_MI = 0.621371


def band_from_rent(rent: float) -> str:
    if rent < 5:
        return "low"
    if rent < 8:
        return "medium"
    if rent < 20:
        return "high"
    return "critical"


def band_from_facilities(live: int) -> str:
    """Without a price series the band can never be critical."""
    if live == 0:
        return "low"
    if live <= 2:
        return "medium"
    return "high"


def cap_band(band: str, facilities: int | None) -> str:
    """A statewide price rise with no facility within five miles is not a data-
    center story at this address: the band says so."""
    order = ["low", "medium", "high", "critical"]
    if facilities is None:
        return band
    ceiling = "medium" if facilities == 0 else "high" if facilities <= 2 else "critical"
    return order[min(order.index(band), order.index(ceiling))]


def monthly_change(price: dict[str, Any]) -> float:
    return round((price["rate_now"] - price["rate_then"]) * price["typical_household_kwh_month"], 1)


# Household usage spreads widely around the state's typical figure; ±20% is the
# range the UI shows instead of a point estimate. fixtures/make_fixtures.py
# uses the same arithmetic.
USAGE_SPREAD = 0.2


def monthly_range(price: dict[str, Any]) -> list[float]:
    diff = price["rate_now"] - price["rate_then"]
    k = price["typical_household_kwh_month"]
    lo, hi = diff * k * (1 - USAGE_SPREAD), diff * k * (1 + USAGE_SPREAD)
    return [float(round(lo)), float(round(hi))]


def _price(sections: Sections) -> dict[str, Any] | None:
    bill = sections.get("your_bill") or {}
    return bill.get("price") if bill.get("status") != "unavailable" else None


def period_words(price: dict[str, Any]) -> tuple[str, str]:
    """('in 2024', 'in 2022') for annual utility data; ('', 'two years ago')
    for a series that runs to the present."""
    as_of = price.get("as_of") or ""
    if as_of.endswith("-12") and len(as_of) == 7:
        year = int(as_of[:4])
        then = year - max(1, int(price.get("window_months", 24)) // 12)
        return f"in {year}", f"in {then}"
    return "", "two years ago"


def facility_count(sections: Sections) -> tuple[int, int]:
    """(total on the grid, live) from the assembled On your grid section."""
    facilities = (sections.get("on_your_grid") or {}).get("facilities") or []
    return len(facilities), sum(1 for f in facilities if f.get("status") == "live")


def grid_sentence(sections: Sections, geo: GeocodeResult, truth: GroundTruth) -> str:
    """The first sentence of the hero when the facility list is the engine's."""
    total, live = facility_count(sections)
    served = f", served by {truth.utility.name}" if truth.utility else ""
    if total == 0:
        return (
            "No data-center facility within five miles of this address is listed in "
            f"PeeringDB or OpenStreetMap{served}."
        )
    building = total - live
    what = "data center" if total == 1 else "data centers"
    tail = f" ({building} under construction)" if building else ""
    return f"{total} {what} within five miles are on your local grid{served}{tail}."


def derive_headline(
    sections: Sections, geo: GeocodeResult, truth: GroundTruth | None = None
) -> dict[str, Any]:
    price = _price(sections)
    rent = monthly_change(price) if price else None
    total, live = facility_count(sections)
    grounded = truth is not None and truth.facilities is not None

    band = band_from_rent(rent) if rent is not None else band_from_facilities(live)
    if grounded:
        band = cap_band(band, total)

    if grounded:
        one = grid_sentence(sections, geo, truth)  # type: ignore[arg-type]
    else:
        lead = next(
            (
                sections[sid]["summary"]
                for sid in SECTION_IDS
                if sections.get(sid, {}).get("status") != "unavailable"
            ),
            "",
        )
        one = _first_sentence(lead)
    if rent is not None and price is not None:
        word = "more" if rent >= 0 else "less"
        now, then = period_words(price)
        who = (
            f"A typical {truth.utility.name} home"
            if truth is not None and truth.utility and truth.utility_price
            else f"A typical home in {geo.state}"
        )
        verb = "paid" if now else "pays"
        one = (
            f"{one} {who} {verb} about ${abs(rent):.0f} {word} a month"
            f"{' ' + now if now else ''} than {then}."
        ).strip()

    return {
        "ai_rent_usd_per_month": rent,
        "ai_rent_range_usd_per_month": monthly_range(price) if price else None,
        "percentile": None,
        "band": band,
        "one_liner": one or "Not enough public information to summarize this address yet.",
    }


def bill_house_line(sections: Sections) -> dict[str, Any] | None:
    """The first sentence of the strip, from the price block alone. Modeled:
    the state's average price times a typical home's usage. No model writes it."""
    price = _price(sections)
    if not price:
        return None
    bill = sections["your_bill"]
    rent = monthly_change(price)
    lo, hi = monthly_range(price)
    word = "higher" if rent >= 0 else "lower"
    now, then = period_words(price)
    text = (
        f"Your power bill {'was' if now else 'is'} about ${abs(rent):.0f} a month {word}"
        f"{' ' + now if now else ''} than {then}, somewhere between ${abs(lo):.0f} and "
        f"${abs(hi):.0f} depending on how much electricity you use."
    )
    if price.get("attribution"):
        text += " The people who set the rates say part of that is data-center load."
    else:
        text += " No regulator has tied any of that to data centers."
    return {
        "text": text,
        "topic": "bill",
        "status": "modelled",
        "confidence": max(0.0, min(1.0, float(bill.get("confidence", 0.0)))),
        "sources": list(bill.get("sources") or []),
    }


def noise_house_line(truth: GroundTruth, now_iso: str) -> dict[str, Any] | None:
    """Noise, modeled from distance to the nearest building in the facility
    database. Low confidence by design: nobody has measured it."""
    if truth.facilities is None:
        return None
    nearest = truth.nearest
    if nearest is None:
        return {
            "text": "No data-center building within five miles of your house is listed in "
            "PeeringDB or OpenStreetMap, so there is nothing nearby to hear.",
            "topic": "noise",
            "status": "measured",
            "confidence": 0.8,
            "sources": [],
        }
    miles = nearest.distance_km * KM_TO_MI
    heard = noise_at(nearest.distance_km)
    text = (
        f"The nearest data-center building, {nearest.name}, is {miles:.1f} miles from your house."
        f" {heard.basis}"
    )
    return {
        "text": text,
        "topic": "noise",
        "status": "modelled",
        "confidence": heard.confidence,
        "sources": [
            {
                "title": nearest.source_title,
                "url": nearest.source_url,
                "retrieved_at": now_iso,
                "quote": nearest.name,
            }
        ],
    }


FOOTBALL_FIELD_ACRES = 1.32


def land_house_line(truth: GroundTruth, now_iso: str) -> dict[str, Any] | None:
    """Land, measured: what SAM 3.1 found between two imagery vintages. Only
    roofs beside listed data centers count; the sentence says what it saw."""
    img = truth.imagery
    if img is None:
        return None
    then, now = img.vintages
    sources = [
        {"title": item.title, "url": item.url, "retrieved_at": now_iso, "quote": item.id}
        for vintage in (img.then, img.now)
        for item in vintage.items
    ][:2]
    counted = img.counted
    if not counted:
        return {
            "text": f"Comparing the {then} and {now} aerial photos, no new large data-center roof "
            "appeared within five miles of your house.",
            "topic": "land",
            "status": "measured",
            "confidence": 0.7,
            "sources": sources,
        }
    acres = img.new_acres
    fields = acres / FOOTBALL_FIELD_ACRES
    nearest = counted[0]
    text = (
        f"Comparing the {then} and {now} aerial photos, about {acres:.0f} acres of new data-center "
        f"roof went up within five miles of your house, roughly {fields:.0f} football fields. "
        f"The closest, {nearest.label}, is {nearest.distance_km * KM_TO_MI:.1f} miles away."
    )
    return {
        "text": text,
        "topic": "land",
        "status": "measured",
        "confidence": 0.7,
        "sources": sources,
    }


def disclosure_line(
    brief_id: str,
    generated_at: str,
    public_base_url: str = "",
    *,
    verified: bool = True,
    grounded: bool = True,
) -> str:
    """What made the brief, in words that survive a screenshot: the footer band
    of the share card, in the DOM and in the PNG alike. Worded like the card's
    footer: a brief made without the verifier or without ground truth claims
    neither. The card renders it anew from the id, the date and the base, so a
    stored line with no host never reaches the pixels."""
    base = public_base_url.rstrip("/")
    drafted = (
        "Facts measured from public data; sentences drafted by Muse Spark"
        if grounded
        else "Sentences drafted by Muse Spark without ground-truth data"
    )
    checked = "checked by Muse Spark Open" if verified else "not yet checked"
    return f"AI-assisted brief. {drafted} and {checked}. {base}/b/{brief_id} · {generated_at[:10]}"


def derive_card(
    card_lines: list[str],
    geo: GeocodeResult,
    claims: list[dict[str, Any]],
    *,
    verified: bool = True,
    grounded: bool = False,
    brief_id: str = "",
    generated_at: str = "",
    public_base_url: str = "",
) -> dict[str, Any]:
    parts = [p.strip() for p in geo.display.split(",")]
    city = parts[-2] if len(parts) >= 2 else parts[0]
    lines = [line.strip()[:80] for line in card_lines if line and line.strip()]
    lines = lines[:4] or ["Not enough public information yet"]
    hosts: list[str] = []
    for c in claims:
        h = urlparse(c["source"]["url"]).netloc.lower().removeprefix("www.")
        if h and h not in hosts:
            hosts.append(h)
    sources = ", ".join(hosts[:4]) if hosts else "none cited"
    checked = "checked by Muse Spark Open" if verified else "claims not yet checked"
    drafted = (
        "Facilities, utility and prices from public data; sentences by Muse Spark"
        if grounded
        else "Drafted by Muse Spark"
    )
    tail = "" if grounded else " Not verified against ground-truth data."
    return {
        "title": f"Who's on my grid: {city}, {geo.state}",
        "lines": lines,
        "footer": f"Sources: {sources}. {drafted}, {checked}.{tail}",
        "disclosure": disclosure_line(
            brief_id, generated_at, public_base_url, verified=verified, grounded=grounded
        ),
    }


def _first_sentence(text: str) -> str:
    text = text.strip()
    for i, ch in enumerate(text):
        if ch in ".!?" and (i + 1 == len(text) or text[i + 1] == " "):
            return text[: i + 1]
    return text
