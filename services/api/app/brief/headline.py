"""The headline number and the share card, derived from the section drafts.
No model call: nothing here can introduce a causal claim."""

from typing import Any
from urllib.parse import urlparse

from app.brief.draft import DraftResult, SectionFailure
from app.geocode import GeocodeResult
from app.schema import SECTION_IDS

Drafts = dict[str, DraftResult | SectionFailure]


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


def _ok(d: DraftResult | SectionFailure | None) -> DraftResult | None:
    return d if isinstance(d, DraftResult) else None


def _reported(drafts: Drafts) -> list[DraftResult]:
    """The drafts that succeeded, in section order."""
    return [d for sid in SECTION_IDS if (d := _ok(drafts.get(sid)))]


def derive_headline(drafts: Drafts, geo: GeocodeResult) -> dict[str, Any]:
    bill = _ok(drafts.get("your_bill"))
    price = bill.extra.get("price") if bill else None
    rent = monthly_change(price) if price else None

    grid = _ok(drafts.get("on_your_grid"))
    live = 0
    if grid:
        facilities = grid.extra.get("facilities") or []
        live = sum(1 for f in facilities if f.get("status") == "live")

    band = band_from_rent(rent) if rent is not None else band_from_facilities(live)

    lead = grid.summary if grid else next((d.summary for d in _reported(drafts)), "")
    one = _first_sentence(lead)
    if rent is not None:
        word = "more" if rent >= 0 else "less"
        bill_line = f"A typical home in {geo.state} pays about ${abs(rent):.0f} {word} a month"
        one = f"{one} {bill_line} than two years ago.".strip()

    return {
        "ai_rent_usd_per_month": rent,
        "ai_rent_range_usd_per_month": monthly_range(price) if price else None,
        "percentile": None,
        "band": band,
        "one_liner": one or "Not enough public information to summarize this address yet.",
    }


def bill_house_line(drafts: Drafts) -> dict[str, Any] | None:
    """The first sentence of the strip, from the price block alone. Modeled:
    the state's average price times a typical home's usage. No model writes it."""
    bill = _ok(drafts.get("your_bill"))
    price = bill.extra.get("price") if bill else None
    if not bill or not price:
        return None
    rent = monthly_change(price)
    lo, hi = monthly_range(price)
    word = "higher" if rent >= 0 else "lower"
    text = (
        f"Your power bill is about ${abs(rent):.0f} a month {word} than two years ago, "
        f"somewhere between ${abs(lo):.0f} and ${abs(hi):.0f} depending on how much "
        "electricity you use."
    )
    if price.get("attribution"):
        text += " The people who set the rates say part of that is data-center load."
    else:
        text += " No regulator has tied any of that to data centers."
    return {
        "text": text,
        "topic": "bill",
        "status": "modelled",
        "confidence": max(0.0, min(1.0, bill.confidence)),
        "sources": [],  # the assembler fills these from the bill section
    }


def derive_card(
    drafts: Drafts, geo: GeocodeResult, claims: list[dict[str, Any]], *, verified: bool = True
) -> dict[str, Any]:
    parts = [p.strip() for p in geo.display.split(",")]
    city = parts[-2] if len(parts) >= 2 else parts[0]
    lines = [d.card_line.strip()[:80] for d in _reported(drafts) if d.card_line]
    lines = lines[:4] or ["Not enough public information yet"]
    hosts: list[str] = []
    for c in claims:
        h = urlparse(c["source"]["url"]).netloc.lower().removeprefix("www.")
        if h and h not in hosts:
            hosts.append(h)
    sources = ", ".join(hosts[:4]) if hosts else "none cited"
    checked = "checked by Muse Spark Open" if verified else "claims not yet checked"
    return {
        "title": f"Who's on my grid: {city}, {geo.state}",
        "lines": lines,
        "footer": f"Sources: {sources}. Drafted by Muse Spark, {checked}. "
        "Not verified against ground-truth data.",
    }


def _first_sentence(text: str) -> str:
    text = text.strip()
    for i, ch in enumerate(text):
        if ch in ".!?" and (i + 1 == len(text) or text[i + 1] == " "):
            return text[: i + 1]
    return text
