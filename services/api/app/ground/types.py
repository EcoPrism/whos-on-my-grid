"""What the engine knows before any model is asked: facilities within the ring,
the serving utility, the state's residential price series. Each comes from a
public dataset with a URL a reader (and the verifier) can open."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ground.tariffs import TariffEntry

FIVE_MILES_KM = 8.047


@dataclass(frozen=True)
class GroundFacility:
    name: str
    operator: str
    operator_known: bool
    status: str  # live | under_construction
    lat: float
    lon: float
    distance_km: float
    source_url: str
    source_title: str
    buildings: int = 1
    providers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Utility:
    name: str  # display name
    raw_name: str  # as the dataset spells it
    kind: str  # INVESTOR OWNED, MUNICIPAL, COOPERATIVE, ...
    customers: int | None
    holding: str | None
    source_url: str
    candidates: int = 1  # polygons that contained the point; >1 means overlap
    eia_id: str | None = None  # EIA utility number, the join key to EIA-861
    website: str | None = None


@dataclass(frozen=True)
class PriceSeries:
    state: str
    rate_now: float  # USD per kWh, trailing twelve months
    rate_then: float  # USD per kWh, the twelve months ending 24 months earlier
    trend_pct: float
    typical_kwh_month: float  # residential sales / customers, trailing twelve months
    window_months: int
    latest: tuple[int, int]  # (year, month) of the newest data point
    source_url: str
    source_title: str
    data_status: str  # Preliminary | Final
    scope: str = "state"  # state | utility
    as_of: str | None = None  # YYYY-MM the "now" window ends
    label: str = ""  # "WA statewide" or the utility's name in the dataset
    latest_month_rate: float | None = None  # USD/kWh for the newest month alone (EPM table)
    eia_id: str | None = None


@dataclass
class GroundTruth:
    facilities: list[GroundFacility] | None = None  # None: no facility source answered
    utility: Utility | None = None
    price: PriceSeries | None = None  # statewide, monthly
    utility_price: PriceSeries | None = None  # this utility, annual
    tariff: "TariffEntry | None" = None
    notes: list[str] = field(default_factory=list)  # provider failures, for gap text
    radius_km: float = FIVE_MILES_KM

    @property
    def live(self) -> list[GroundFacility]:
        return [f for f in self.facilities or [] if f.status == "live"]

    @property
    def building(self) -> list[GroundFacility]:
        return [f for f in self.facilities or [] if f.status == "under_construction"]

    @property
    def nearest(self) -> GroundFacility | None:
        return min(self.facilities or [], key=lambda f: f.distance_km, default=None)

    @property
    def best_price(self) -> PriceSeries | None:
        """The utility's own figure when we have it, else the state's."""
        return self.utility_price or self.price
