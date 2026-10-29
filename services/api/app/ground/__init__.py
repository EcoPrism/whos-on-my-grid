"""Ground truth for a brief: what public datasets say about the address
before any model writes a word. Gathered in parallel; a provider that fails
leaves its field None and a sentence in `notes` for the gap text."""

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from app.config import REPO_ROOT, Settings
from app.geocode import GeocodeResult
from app.ground.facilities import (
    FacilityDatabase,
    FakeFacilityDatabase,
    GroundError,
    OverpassSource,
    PeeringDBSource,
    load_overrides,
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
from app.ground.utility import FakeUtility, HifldUtility, UtilityProvider
from app.telemetry import log_event

# The US region's curated data: tariff table, operator overrides, scenario
# constants and the step-4 indexes.
US_DATA_DIR = REPO_ROOT / "data" / "regions" / "us"


class Tariffs(Protocol):
    def match(self, jurisdiction: str, utility_raw_name: str | None) -> TariffEntry | None: ...


@dataclass
class Ground:
    facilities: FacilityDatabase | FakeFacilityDatabase | None = None
    utility: UtilityProvider | None = None
    prices: PriceProvider | None = None
    utility_prices: UtilityPriceProvider | None = None
    tariffs: Tariffs | None = None
    imagery: ImageryIndex | FakeImageryIndex | None = None
    hearings: HearingIndex | FakeHearingIndex | None = None


def get_ground(settings: Settings, data_dir: Path = US_DATA_DIR) -> Ground:
    """The US ground layer. Curated files come from `data_dir`; the imagery and
    hearing indexes from settings (GRID_PERCEPTION_DIR, GRID_HEARINGS_DIR), whose
    defaults are the same region's directories."""
    cache = Path(settings.ground_path)
    endpoints = [e.strip() for e in settings.overpass_endpoints.split(",") if e.strip()]
    t = settings.ground_timeout_seconds
    # EIA-861 is both the utility's price and the directory that settles
    # overlapping territories, so one instance serves both.
    up = Eia861UtilityPrices(cache, timeout=max(120.0, t))
    return Ground(
        facilities=FacilityDatabase(
            [PeeringDBSource(cache, timeout=t), OverpassSource(endpoints, timeout=t)],
            overrides=load_overrides(data_dir / "facilities.json"),
        ),
        utility=HifldUtility(url=settings.hifld_url, timeout=t, directory=up),
        prices=Eia861mPrices(cache, timeout=max(60.0, t)),
        utility_prices=up,
        tariffs=TariffTable(data_dir / "tariffs.json"),
        imagery=ImageryIndex(settings.perception_path),
        hearings=HearingIndex(settings.hearings_path),
    )


async def gather_ground(geo: GeocodeResult, ground: Ground | None) -> GroundTruth:
    truth = GroundTruth(radius_km=FIVE_MILES_KM)
    if ground is None:
        return truth

    async def facilities() -> None:
        if ground.facilities is None:
            return
        try:
            looked = await ground.facilities.lookup(geo.lat, geo.lon, truth.radius_km)
            found, notes = looked.facilities, looked.notes
            truth.beyond_ring = looked.beyond
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
                truth.utility = await ground.utility.locate(geo)
            except Exception as exc:  # noqa: BLE001 - a data provider, never fatal
                log_event("ground_failed", provider="hifld", reason=str(exc)[:160])
                truth.notes.append(
                    "The service-territory map could not be reached; the serving utility is "
                    "not known."
                )
        directory = ground.utility_prices
        u = truth.utility
        if u is not None and u.eia_id and u.ba_code is None and hasattr(directory, "ba_code"):
            try:
                code = await directory.ba_code(u.eia_id, geo.region_code)  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001 - optional, used by the what-if bill line
                log_event("ground_failed", provider="eia861-directory", reason=str(exc)[:160])
            else:
                if code:
                    truth.utility = replace(u, ba_code=code)
        if ground.tariffs is not None:
            truth.tariff = ground.tariffs.match(
                geo.region_code, truth.utility.raw_name if truth.utility else None
            )
        if ground.utility_prices is None or truth.utility is None or not truth.utility.eia_id:
            return
        try:
            truth.utility_price = await ground.utility_prices.for_utility(
                truth.utility.eia_id, geo.region_code
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
            truth.price = await ground.prices.series(geo.region_code)
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
                geo.region_code, geo.county, truth.utility.name if truth.utility else None
            )
            truth.decisions = ground.hearings.decisions_for(geo.region_code, geo.county)
            if truth.hearing is None:
                truth.hearing_note = ground.hearings.coverage_note(geo.region_code, geo.county)
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
    "US_DATA_DIR",
]
