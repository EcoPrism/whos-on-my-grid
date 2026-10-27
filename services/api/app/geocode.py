"""Address to coordinates, state, county and ZIP via the US Census Bureau
geocoder. No key, US only. The matched address, normalised, is what the brief
id is hashed from, so two spellings of one address get one brief.

The address itself is never logged and never stored; see brief_id_for().
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import get_settings

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"


class GeocodeUnavailable(Exception):
    """The geocoder could not be reached or answered with an error."""


@dataclass(frozen=True)
class GeocodeResult:
    display: str  # street and city, no house number: what the UI shows
    lat: float
    lon: float
    state: str
    county: str | None
    zip: str
    matched: str  # the geocoder's canonical one-line address, used for the id


class Geocoder(Protocol):
    async def geocode(self, address: str) -> GeocodeResult | None: ...


_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalise(address: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", address.lower())).strip()


def brief_id_for(matched: str) -> str:
    """sha256 of the normalised address, first 16 hex chars. This is the only
    thing derived from the address that is ever written to disk or a log."""
    return hashlib.sha256(normalise(matched).encode("utf-8")).hexdigest()[:16]


_HOUSE_NUMBER = re.compile(r"^\s*\d+[A-Za-z]?(?:-\d+)?\s+")


def display_from(matched: str, state: str, zip_code: str) -> str:
    """'21715 FILIGREE CT, ASHBURN, VA, 20147' -> 'Filigree Ct, Ashburn, VA 20147'."""
    parts = [p.strip() for p in matched.split(",")]
    street = _HOUSE_NUMBER.sub("", parts[0]) if parts else ""
    city = parts[1] if len(parts) > 1 else ""
    street = " ".join(w.capitalize() for w in street.lower().split())
    city = " ".join(w.capitalize() for w in city.lower().split())
    bits = [b for b in (street, city) if b]
    return f"{', '.join(bits)}, {state} {zip_code}".strip(", ")


class CensusGeocoder:
    async def geocode(self, address: str) -> GeocodeResult | None:
        params = {
            "address": address,
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "format": "json",
        }
        timeout = get_settings().geocode_timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(CENSUS_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GeocodeUnavailable(exc.__class__.__name__) from exc

        matches = data.get("result", {}).get("addressMatches") or []
        if not matches:
            return None
        m = matches[0]
        comp = m.get("addressComponents", {})
        state = (comp.get("state") or "").upper()
        zip_code = comp.get("zip") or ""
        counties = m.get("geographies", {}).get("Counties") or []
        county = counties[0].get("BASENAME") if counties else None
        matched = m.get("matchedAddress", "")
        if not (state and matched):
            return None
        return GeocodeResult(
            display=display_from(matched, state, zip_code),
            lat=float(m["coordinates"]["y"]),
            lon=float(m["coordinates"]["x"]),
            state=state,
            county=county,
            zip=zip_code,
            matched=matched,
        )


class FakeGeocoder:
    """Returns the scripted result for any address, or None when scripted so."""

    def __init__(self, result: GeocodeResult | None = None, *, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.calls = 0

    async def geocode(self, address: str) -> GeocodeResult | None:
        self.calls += 1
        if self.fail:
            raise GeocodeUnavailable("fake")
        return self.result
