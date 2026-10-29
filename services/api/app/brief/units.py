"""Distances, areas, money and rates as a brief writes them, per unit system and
currency. The US branches reproduce the f-strings the engine wrote before
regions (US briefs are byte-identical: tests/test_us_golden.py); the metric
branches are Ireland's. No app imports beyond the locale."""

from app.regions.locale import Units

KM_TO_MI = 0.621371
ACRE_TO_HA = 0.404686
RING_KM = 8  # the ring a brief measures: five miles in the US, 8 km elsewhere
OUTER_KM = 16  # how far the engine looks past the ring: ten miles, 16 km

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


def symbol(currency: str) -> str:
    """'$' for USD, '€' for EUR; an unknown code is written as the code and a space."""
    return _SYMBOLS.get(currency.upper(), f"{currency.upper()} ")


def dist(km: float, units: Units) -> str:
    """'1.2 miles' (US) or '1.9 km'."""
    if units == "us":
        return f"{km * KM_TO_MI:.1f} miles"
    return f"{km:.1f} km"


def dist_whole(km: float, units: Units) -> str:
    """'3 miles' or '5 km': the rejected-campus sentence rounds to whole units."""
    if units == "us":
        return f"{km * KM_TO_MI:.0f} miles"
    return f"{km:.0f} km"


def dist_short(km: float, units: Units) -> str:
    """'1.2 mi' or '1.9 km': the facts block's facility table."""
    if units == "us":
        return f"{km * KM_TO_MI:.1f} mi"
    return f"{km:.1f} km"


def radius_words(units: Units) -> str:
    """The ring, as a distance: 'five miles' or '8 km'."""
    return "five miles" if units == "us" else f"{RING_KM} km"


def ring_words(units: Units) -> str:
    """The ring, as a thing: 'the five-mile ring' or 'the 8 km ring'."""
    return "the five-mile ring" if units == "us" else f"the {RING_KM} km ring"


def outer_words(units: Units) -> str:
    """How far the engine searched past the ring: 'ten miles' or '16 km'."""
    return "ten miles" if units == "us" else f"{OUTER_KM} km"


def card_radius(units: Units) -> str:
    """The share card's short form: '5 miles' or '8 km'."""
    return "5 miles" if units == "us" else f"{RING_KM} km"


def area(acres: float, units: Units) -> str:
    """'12 acres' or '5 hectares'."""
    if units == "us":
        return f"{acres:.0f} acres"
    return f"{acres * ACRE_TO_HA:.0f} hectares"


def money_abs(n: float, currency: str) -> str:
    """'$21' or '€45': whole units, no sign."""
    return f"{symbol(currency)}{abs(n):.0f}"


def money(n: float, currency: str) -> str:
    """'+$21' or '−€3': whole units with the sign the card uses."""
    return f"{'−' if n < 0 else '+'}{money_abs(n, currency)}"


def rate_words(rate: float, currency: str) -> str:
    """A per-kWh price in a summary: '15.1 cents per kWh' (USD) or '€0.387 per kWh'."""
    if currency.upper() == "USD":
        return f"{rate * 100:.1f} cents per kWh"
    return f"{symbol(currency)}{rate:.3f} per kWh"


def rate_short(rate: float, currency: str) -> str:
    """The second figure of a pair: '13.2 cents' (USD) or '€0.259'."""
    if currency.upper() == "USD":
        return f"{rate * 100:.1f} cents"
    return f"{symbol(currency)}{rate:.3f}"
