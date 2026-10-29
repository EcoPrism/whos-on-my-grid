"""A region's locale: country, currency, units and language. Kept apart from
the registry and free of app imports, so the brief assembler can read it
without pulling in geocoders and ground providers."""

from dataclasses import dataclass
from typing import Literal

Units = Literal["us", "metric"]


@dataclass(frozen=True)
class Locale:
    country: str  # ISO 3166-1 alpha-2
    currency: str  # ISO 4217: USD, EUR, GBP, INR
    units: Units
    language: str  # BCP 47, for prompts and hearing transcription


US_LOCALE = Locale(country="US", currency="USD", units="us", language="en-US")
IE_LOCALE = Locale(country="IE", currency="EUR", units="metric", language="en-IE")
