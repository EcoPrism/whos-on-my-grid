"""What the engine knows before any model is asked: facilities within the ring,
the serving utility, the state's residential price series. Each comes from a
public dataset with a URL a reader (and the verifier) can open."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.ground.tariffs import TariffEntry

FIVE_MILES_KM = 8.047
BEYOND_RING_KM = 16.09  # ten miles: how far the engine looks for a campus past the ring


@dataclass(frozen=True)
class OperatorSource:
    """The page that names a site's operator when the map does not
    (data/regions/<id>/facilities.json). The claim and quote are what the verifier checks."""

    url: str
    title: str
    quote: str
    claim: str


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
    operator_source: OperatorSource | None = None  # set when the operator is curated
    # The name is the PeeringDB org_name standing in for a hidden record name; the
    # engine claim then names only the organization, which the page does show.
    name_from_org: bool = False


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
    ba_code: str | None = None  # EIA-861 balancing authority (PJM, MISO, TVA, ...)
    # Outside the US the map is a curated file that names its own page. None keeps
    # the US HIFLD text: title HIFLD_TITLE, quote raw_name, the HIFLD claim sentence.
    source_title: str | None = None
    quote: str | None = None
    claim_text: str | None = None


@dataclass(frozen=True)
class PriceSeries:
    jurisdiction: str  # the series' area: a US state code, or a country code (IE)
    rate_now: float  # USD per kWh, trailing twelve months
    rate_then: float  # USD per kWh, the twelve months ending 24 months earlier
    trend_pct: float
    # US: residential sales / customers, trailing twelve months. IE: a cited constant / 12;
    # None when the constant is absent (the bill line is then not measured).
    typical_kwh_month: float | None
    window_months: int
    latest: tuple[int, int]  # (year, month) of the newest data point
    source_url: str
    source_title: str
    data_status: str  # Preliminary | Final
    scope: str = "state"  # state | utility | country
    as_of: str | None = None  # YYYY-MM the "now" window ends
    label: str = ""  # "WA statewide" or the utility's name in the dataset
    latest_month_rate: float | None = None  # USD/kWh for the newest month alone (EPM table)
    eia_id: str | None = None
    currency: str = "USD"  # ISO 4217; the rates above are in it per kWh
    granularity: Literal["monthly", "semiannual", "annual"] = "monthly"  # the source's period
    # Set by a provider that writes its own claim (Eurostat); None keeps the US text.
    claim_text: str | None = None
    quote: str | None = None  # verbatim from source_url
    period_now: str | None = None  # the source's own period labels: "2026-S1"
    period_then: str | None = None
    # The typical-consumption figure's own citation, when it is not the price source's.
    kwh_claim_text: str | None = None
    kwh_source_url: str | None = None
    kwh_source_title: str | None = None
    kwh_quote: str | None = None


# --- perception: what SAM 3.1 measured on two imagery vintages -----------------


@dataclass(frozen=True)
class ImageryItem:
    """One NAIP record a claim can cite: the STAC item or the FPAC catalog row."""

    id: str
    date: str  # YYYY-MM-DD acquisition date
    url: str
    title: str


@dataclass(frozen=True)
class ImageryVintage:
    year: int
    source: str  # "USDA NAIP via Microsoft Planetary Computer" ...
    items: tuple[ImageryItem, ...]


@dataclass(frozen=True)
class ConstructionSite:
    id: str
    label: str
    kind: str  # new | expansion
    lat: float
    lon: float
    distance_km: float
    footprint_acres_then: float
    footprint_acres_now: float
    in_database: bool  # grew out of a facility the database lists
    near_cluster: bool  # within 1.5 km of a listed data center
    facility: str | None  # the listed facility it belongs to or adjoins
    polygon: tuple[tuple[float, float], ...]  # (lat, lon) ring
    confidence: float = 0.8

    @property
    def counted(self) -> bool:
        """A roof the brief counts as data-center construction: an expansion of
        a listed facility or a new roof beside one. Other large roofs are shown
        but not counted; a warehouse is not a data center."""
        return self.in_database or self.near_cluster


@dataclass(frozen=True)
class ImageryResult:
    area_id: str
    area_name: str
    model: str  # sam-3.1
    then: ImageryVintage
    now: ImageryVintage
    sites: tuple[ConstructionSite, ...]  # within the ring, nearest first
    indexed_at: str

    @property
    def vintages(self) -> tuple[int, int]:
        return (self.then.year, self.now.year)

    @property
    def counted(self) -> list[ConstructionSite]:
        return [s for s in self.sites if s.counted]

    @property
    def new_acres(self) -> float:
        return round(sum(s.footprint_acres_now - s.footprint_acres_then for s in self.counted), 1)


# --- hearings: what Muse Voice Transcribe heard in the official recording -------


@dataclass(frozen=True)
class HearingQuote:
    text: str  # verbatim transcript text
    start_s: float
    role: str  # chair | supervisor | ... | unknown
    name: str | None
    source: str  # transcribe | captions


@dataclass(frozen=True)
class Upcoming:
    date: str  # YYYY-MM-DD
    subject: str
    url: str


@dataclass(frozen=True)
class Decision:
    """What a body did to a campus, on the record: the engine's answer to
    'rejected or withdrawn' that no facility database holds."""

    project: str
    codename: str | None
    operator: str | None
    status: str  # rejected | approved | announced
    date: str
    body: str
    text: str  # one sentence a claim can carry
    source_url: str
    source_title: str
    quote: str
    lat: float | None = None
    lon: float | None = None
    estimated_mw: float | None = None
    # Who decided, when it is not `body` (an appeal board granting what the
    # council refused). None: the body decided, as for every US row.
    decided_by: str | None = None


@dataclass(frozen=True)
class HearingResult:
    body_id: str
    body: str
    meeting_id: str
    date: str
    subject: str
    page_url: str
    page_title: str
    quotes: tuple[HearingQuote, ...]
    model: str | None  # the transcription model, None when quotes come from captions
    agreement: float | None  # transcript vs captions, when both exist
    upcoming: Upcoming | None
    coverage: str  # "items 7 and 8, 1 h 20 min" for the gap text


@dataclass
class GroundTruth:
    facilities: list[GroundFacility] | None = None  # None: no facility source answered
    utility: Utility | None = None
    price: PriceSeries | None = None  # statewide, monthly
    utility_price: PriceSeries | None = None  # this utility, annual
    tariff: "TariffEntry | None" = None
    imagery: ImageryResult | None = None  # None: no indexed imagery covers the address
    hearing: HearingResult | None = None  # None: county not indexed
    hearing_note: str | None = None  # why not, when the county is in the index
    decisions: list[Decision] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # provider failures, for gap text
    radius_km: float = FIVE_MILES_KM
    beyond_ring: GroundFacility | None = None  # nearest known campus past the ring

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
