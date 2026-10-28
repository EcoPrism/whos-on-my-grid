"""Ground truth for a brief: what public datasets say about the address
before any model writes a word. Gathered in parallel; a provider that fails
leaves its field None and a sentence in `notes` for the gap text."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.geocode import GeocodeResult
from app.ground.facilities import (
    FacilityDatabase,
    FakeFacilityDatabase,
    GroundError,
    OverpassSource,
    PeeringDBSource,
)
from app.ground.hearings import FakeHearingIndex, HearingIndex
from app.ground.imagery import FakeImageryIndex, ImageryIndex
from app.ground.prices import (
    Eia861mPrices,
    Eia861UtilityPrices,
    FakePrices,
    FakeUtilityPrices,
    PriceProvider,
    UtilityPriceProvider,
)
from app.ground.tariffs import FakeTariffs, TariffEntry, TariffTable
from app.ground.types import (
    FIVE_MILES_KM,
    ConstructionSite,
    Decision,
    GroundFacility,
    GroundTruth,
    HearingQuote,
    HearingResult,
    ImageryItem,
    ImageryResult,
    ImageryVintage,
    PriceSeries,
    Upcoming,
    Utility,
)
from app.ground.utility import (
    RETAIL_TYPES,
    FakeUtility,
    HifldUtility,
    Hint,
    UtilityProvider,
    choose,
)
from app.telemetry import log_event


class Tariffs(Protocol):
    def match(self, state: str, utility_raw_name: str | None) -> TariffEntry | None: ...


@dataclass
class Ground:
    facilities: FacilityDatabase | FakeFacilityDatabase | None = None
    utility: UtilityProvider | None = None
    prices: PriceProvider | None = None
    utility_prices: UtilityPriceProvider | None = None
    tariffs: Tariffs | None = None
    imagery: ImageryIndex | FakeImageryIndex | None = None
    hearings: HearingIndex | FakeHearingIndex | None = None


def get_ground(settings: Settings) -> Ground:
    cache = Path(settings.ground_path)
    endpoints = [e.strip() for e in settings.overpass_endpoints.split(",") if e.strip()]
    t = settings.ground_timeout_seconds
    return Ground(
        facilities=FacilityDatabase(
            [PeeringDBSource(cache, timeout=t), OverpassSource(endpoints, timeout=t)]
        ),
        utility=HifldUtility(url=settings.hifld_url, timeout=t),
        prices=Eia861mPrices(cache, timeout=max(60.0, t)),
        utility_prices=Eia861UtilityPrices(cache, timeout=max(120.0, t)),
        tariffs=TariffTable(),
        imagery=ImageryIndex(settings.perception_path),
        hearings=HearingIndex(settings.hearings_path),
    )


async def _choose_utility(geo: GeocodeResult, ground: Ground) -> Utility | None:
    """HIFLD polygons that contain the point, disambiguated with EIA-861's
    customer counts and county lists when the annual file is available."""
    assert ground.utility is not None
    if not hasattr(ground.utility, "candidates"):
        return await ground.utility.at(geo.lat, geo.lon, geo.state)
    features = await ground.utility.candidates(geo.lat, geo.lon)
    directory = ground.utility_prices
    city = _city(geo)
    retail = [
        f for f in features if str(f.get("TYPE") or f.get("type") or "").upper() in RETAIL_TYPES
    ]
    if not retail and geo.county and directory is not None and hasattr(directory, "in_county"):
        # Only a federal marketer's polygon (or nothing) here: ask EIA-861 which
        # utilities report serving this county instead.
        try:
            features = await directory.in_county(geo.state, geo.county)
        except Exception as exc:  # noqa: BLE001
            log_event("ground_failed", provider="eia861-directory", reason=str(exc)[:160])
        if features:
            log_event("ground_county_fallback", provider="hifld", candidates=len(features))
    if not features:
        return None
    if len(features) == 1 or directory is None or not hasattr(directory, "customers"):
        return choose(features, geo.state, city=city)
    hints: dict[str, Hint] = {}
    for f in features:
        uid = f.get("ID") or f.get("id")
        if uid in (None, ""):
            continue
        uid = str(uid).strip()
        try:
            customers = await directory.customers(uid, geo.state)
            serves = await directory.serves(uid, geo.state, geo.county) if geo.county else None
        except Exception as exc:  # noqa: BLE001 - hints are optional
            log_event("ground_failed", provider="eia861-directory", reason=str(exc)[:160])
            break
        hints[uid] = (customers, serves)
    if len(hints) > 1:
        log_event("ground_overlap", provider="hifld", candidates=len(features), hinted=len(hints))
    return choose(features, geo.state, hints, city=city)


def _city(geo: GeocodeResult) -> str | None:
    """'Filigree Ct, Ashburn, VA 20147' -> 'Ashburn'."""
    parts = [p.strip() for p in geo.display.split(",")]
    return parts[-2] if len(parts) >= 3 else None


async def gather_ground(geo: GeocodeResult, ground: Ground | None) -> GroundTruth:
    truth = GroundTruth(radius_km=FIVE_MILES_KM)
    if ground is None:
        return truth

    async def facilities() -> None:
        if ground.facilities is None:
            return
        try:
            found, notes = await ground.facilities.near(geo.lat, geo.lon, truth.radius_km)
        except GroundError as exc:
            log_event("ground_failed", provider="facilities", reason=str(exc)[:160])
            truth.notes.append(
                "No facility database could be reached; the facility list is not known."
            )
            return
        truth.facilities = found
        truth.notes.extend(notes)

    async def utility_then_its_prices() -> None:
        if ground.utility is not None:
            try:
                truth.utility = await _choose_utility(geo, ground)
            except Exception as exc:  # noqa: BLE001 - a data provider, never fatal
                log_event("ground_failed", provider="hifld", reason=str(exc)[:160])
                truth.notes.append(
                    "The service-territory map could not be reached; the serving utility is "
                    "not known."
                )
        if ground.tariffs is not None:
            truth.tariff = ground.tariffs.match(
                geo.state, truth.utility.raw_name if truth.utility else None
            )
        if ground.utility_prices is None or truth.utility is None or not truth.utility.eia_id:
            return
        try:
            truth.utility_price = await ground.utility_prices.for_utility(
                truth.utility.eia_id, geo.state
            )
        except Exception as exc:  # noqa: BLE001
            log_event("ground_failed", provider="eia861", reason=str(exc)[:160])
            truth.notes.append(
                "EIA's annual utility price file could not be read; the bill change uses the "
                "statewide series."
            )

    async def prices() -> None:
        if ground.prices is None:
            return
        try:
            truth.price = await ground.prices.series(geo.state)
        except Exception as exc:  # noqa: BLE001
            log_event("ground_failed", provider="eia861m", reason=str(exc)[:160])
            truth.notes.append(
                "EIA's monthly price series could not be read; the statewide bill change is "
                "not known."
            )

    await asyncio.gather(facilities(), utility_then_its_prices(), prices())

    # The two indexes are local files: no await, and a broken file is a note,
    # never a failed brief.
    if ground.imagery is not None:
        try:
            truth.imagery = ground.imagery.near(geo.lat, geo.lon, truth.radius_km)
        except Exception as exc:  # noqa: BLE001
            log_event("ground_failed", provider="perception", reason=str(exc)[:160])
            truth.notes.append("The aerial-imagery index could not be read.")
    if ground.hearings is not None:
        try:
            truth.hearing = ground.hearings.for_place(
                geo.state, geo.county, truth.utility.name if truth.utility else None
            )
            truth.decisions = ground.hearings.decisions_for(geo.state, geo.county)
            if truth.hearing is None:
                truth.hearing_note = ground.hearings.coverage_note(geo.state, geo.county)
        except Exception as exc:  # noqa: BLE001
            log_event("ground_failed", provider="hearings", reason=str(exc)[:160])
            truth.notes.append("The hearing index could not be read.")

    log_event(
        "ground",
        facilities=None if truth.facilities is None else len(truth.facilities),
        utility=truth.utility.raw_name if truth.utility else None,
        utility_price=bool(truth.utility_price),
        state_price=bool(truth.price),
        tariff=truth.tariff.status if truth.tariff else None,
        imagery=truth.imagery.area_id if truth.imagery else None,
        construction=len(truth.imagery.sites) if truth.imagery else None,
        hearing=truth.hearing.meeting_id if truth.hearing else None,
        decisions=len(truth.decisions),
        notes=len(truth.notes),
    )
    return truth


__all__ = [
    "FIVE_MILES_KM",
    "ConstructionSite",
    "Decision",
    "FakeFacilityDatabase",
    "FakeHearingIndex",
    "FakeImageryIndex",
    "FakePrices",
    "FakeTariffs",
    "FakeUtility",
    "FakeUtilityPrices",
    "Ground",
    "GroundFacility",
    "GroundTruth",
    "HearingIndex",
    "HearingQuote",
    "HearingResult",
    "ImageryIndex",
    "ImageryItem",
    "ImageryResult",
    "ImageryVintage",
    "PriceSeries",
    "TariffEntry",
    "Upcoming",
    "Utility",
    "gather_ground",
    "get_ground",
]
