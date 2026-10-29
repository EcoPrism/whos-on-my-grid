"""Serving utility from HIFLD's Electric Retail Service Territories, point in
polygon. Public ArcGIS feature service, no key. Territories overlap in the
data (a small municipal polygon drawn over a large investor-owned one), so
when several contain the point the retail utility with the most customers
wins and the brief notes the overlap."""

import re
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from app.ground.types import Utility
from app.telemetry import log_event

if TYPE_CHECKING:
    from app.geocode import GeocodeResult

HIFLD_URL = (
    "https://eedgis.pnnl.gov/arcgis/rest/services/Hosted/"
    "Electric_Service_Territories/FeatureServer/0/query"
)
HIFLD_PAGE = "https://atlas.eia.gov/datasets/eia::electric-retail-service-territories/about"
USER_AGENT = "WhosOnMyGrid/0.1 (+https://github.com/EcoPrism/whos-on-my-grid)"

# Territory types that sell power to homes. Federal marketers and wholesale
# agencies also draw polygons over the same ground.
RETAIL_TYPES = {
    "INVESTOR OWNED",
    "MUNICIPAL",
    "COOPERATIVE",
    "POLITICAL SUBDIVISION",
    "STATE",
    "MUNICIPAL MKTG AUTHORITY",
    "REPORTED IN EIA-861",  # synthetic: from the county list when no polygon fits
}

# Dataset spellings a resident would not recognise, with the name on the bill.
_ALIASES: dict[str, str] = {
    "VIRGINIA ELECTRIC & POWER CO": "Dominion Energy Virginia",
    "PUD NO 2 OF GRANT COUNTY": "Grant County PUD",
    "PUGET SOUND ENERGY INC": "Puget Sound Energy",
    "HAWAIIAN ELECTRIC CO INC": "Hawaiian Electric",
    "CITY OF GALLATIN - (TN)": "Gallatin Department of Electricity",
    "TUCSON ELECTRIC POWER CO": "Tucson Electric Power",
    "CITY OF SEATTLE - (WA)": "Seattle City Light",
    "PORTLAND GENERAL ELECTRIC CO": "Portland General Electric",
    "MIDAMERICAN ENERGY CO": "MidAmerican Energy",
    "OHIO POWER CO": "AEP Ohio",
    "SALT RIVER PROJECT": "Salt River Project (SRP)",
    "ARIZONA PUBLIC SERVICE CO": "Arizona Public Service (APS)",
    "ONCOR ELECTRIC DELIVERY COMPANY LLC": "Oncor Electric Delivery",
    "COMMONWEALTH EDISON CO": "ComEd (Commonwealth Edison)",
    "CITY OF SANTA CLARA - (CA)": "Silicon Valley Power (City of Santa Clara)",
    "LOS ANGELES DEPARTMENT OF WATER & POWER": "Los Angeles Department of Water and Power",
    "CONSOLIDATED EDISON CO-NY INC": "Con Edison",
    "OMAHA PUBLIC POWER DISTRICT": "Omaha Public Power District (OPPD)",
    "GEORGIA POWER CO": "Georgia Power",
    "IDAHO POWER CO": "Idaho Power",
    "NORTHWESTERN ENERGY LLC - (MT)": "NorthWestern Energy",
    "NORTHWESTERN ENERGY": "NorthWestern Energy",
    "SAN DIEGO GAS & ELECTRIC CO": "San Diego Gas & Electric (SDG&E)",
    "KEYS ENERGY SERVICES": "Keys Energy Services",
    "CITY OF KEY WEST - (FL)": "Keys Energy Services",
    "UTILITY BOARD OF THE CITY OF KEY WEST, F": "Keys Energy Services",
    "UTILITY BOARD OF THE CITY OF KEY WEST, FL": "Keys Energy Services",
    "BONNEVILLE POWER ADMINISTRATION": "Bonneville Power Administration (wholesale)",
    "DUKE ENERGY CAROLINAS, LLC": "Duke Energy Carolinas",
    "DUKE ENERGY PROGRESS - (NC)": "Duke Energy Progress",
    "ROCKY MOUNTAIN POWER": "Rocky Mountain Power (PacifiCorp)",
    "PACIFIC POWER": "Pacific Power (PacifiCorp)",
}
_SMALL = {"of", "and", "the", "de"}
_KEEP = {"PUD", "LLC", "SRP", "APS", "TVA", "NY", "AEP", "EMC", "REA", "REMC", "US", "USA"}


def display_name(raw: str, state: str | None = None) -> str:
    key = raw.strip().upper()
    if key in _ALIASES:
        return _ALIASES[key]
    if key == "PACIFICORP":
        return (
            "Rocky Mountain Power (PacifiCorp)"
            if state in ("UT", "ID", "WY")
            else "Pacific Power (PacifiCorp)"
        )
    # "CITY OF BOZEMAN - (MT)" -> "City of Bozeman"
    core = key.split(" - (")[0].strip()
    words = []
    for w in core.split():
        if w in _KEEP:
            words.append(w)
        elif w.lower() in _SMALL and words:
            words.append(w.lower())
        elif w in ("CO", "INC", "CORP", "LLC", "CO-NY"):
            continue
        else:
            words.append(w.capitalize())
    return " ".join(words) or raw


class UtilityProvider(Protocol):
    """The serving utility for a geocoded address. Each region's provider owns
    its own disambiguation; the US one is HIFLD plus EIA-861."""

    async def locate(self, geo: "GeocodeResult") -> Utility | None: ...


class UtilityDirectory(Protocol):
    """EIA-861: how many customers a utility has and which counties it reports."""

    async def customers(self, eia_id: str, state: str) -> int | None: ...

    async def serves(self, eia_id: str, state: str, county: str) -> bool | None: ...

    async def in_county(self, state: str, county: str) -> list[dict[str, Any]]: ...


Hint = tuple[int | None, bool | None]  # (customers, serves this county)


class HifldUtility:
    def __init__(
        self,
        *,
        url: str = HIFLD_URL,
        timeout: float = 25.0,
        directory: UtilityDirectory | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.directory = directory

    async def locate(self, geo: "GeocodeResult") -> Utility | None:
        return await disambiguate(geo, await self.candidates(geo.lat, geo.lon), self.directory)

    async def candidates(self, lat: float, lon: float) -> list[dict[str, Any]]:
        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",  # mirrors differ in field case; choose() normalises
            "returnGeometry": "false",
            "f": "json",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"User-Agent": USER_AGENT}
        ) as client:
            r = await client.get(self.url, params=params)
            r.raise_for_status()
            body = r.json()
        if "error" in body:
            raise RuntimeError(f"HIFLD: {body['error'].get('message', 'error')}")
        return [f.get("attributes", {}) for f in body.get("features") or []]


def _customers(a: dict[str, Any]) -> int:
    c = a.get("CUSTOMERS") or a.get("customers")
    return int(c) if isinstance(c, int | float) and c > 0 else -1


def _id(a: dict[str, Any]) -> str | None:
    v = a.get("ID")
    return str(v).strip() if v not in (None, "") else None


def choose(
    features: list[dict[str, Any]],
    state: str | None = None,
    hints: dict[str, Hint] | None = None,
    city: str | None = None,
) -> Utility | None:
    """Territory polygons overlap in the data, so containment alone is not an
    answer. Keep retail sellers; drop any that EIA-861 says do not serve this
    county when another does; a utility named for the address's city (a
    municipal light department, a city utility board) beats the investor-owned
    polygon drawn over it; then the one with the most customers, EIA's count
    first (HIFLD has none for many large utilities)."""
    if not features:
        return None
    norm = [{k.upper(): v for k, v in f.items()} for f in features]
    retail = [f for f in norm if (f.get("TYPE") or "").upper() in RETAIL_TYPES]
    pool = retail or norm
    hints = hints or {}
    if hints:
        served = [f for f in pool if _id(f) and hints.get(_id(f), (None, None))[1] is True]
        unknown = [f for f in pool if not _id(f) or hints.get(_id(f), (None, None))[1] is None]
        pool = served or unknown or pool
    if city and len(pool) > 1:
        pattern = re.compile(r"\b" + re.escape(city.strip().upper()) + r"\b")
        named = [f for f in pool if pattern.search(str(f.get("NAME") or "").upper())]
        pool = named or pool

    def size(a: dict[str, Any]) -> int:
        hinted = hints.get(_id(a) or "", (None, None))[0]
        return hinted if hinted else _customers(a)

    best = max(pool, key=size)
    raw = str(best.get("NAME") or "").strip()
    if not raw:
        return None
    if len(pool) > 1:
        log_event("ground_overlap", provider="hifld", candidates=len(pool))
    customers = size(best)
    return Utility(
        name=display_name(raw, state),
        raw_name=raw,
        kind=str(best.get("TYPE") or "NOT AVAILABLE").upper(),
        customers=customers if customers > 0 else None,
        holding=(str(best.get("HOLDING_CO")).strip() or None) if best.get("HOLDING_CO") else None,
        source_url=HIFLD_PAGE,
        candidates=len(pool),
        eia_id=str(best["ID"]).strip() if best.get("ID") not in (None, "") else None,
        website=(str(best.get("WEBSITE")).strip() or None) if best.get("WEBSITE") else None,
    )


async def disambiguate(
    geo: "GeocodeResult",
    features: list[dict[str, Any]],
    directory: UtilityDirectory | None,
) -> Utility | None:
    """HIFLD polygons that contain the point, disambiguated with EIA-861's
    customer counts and county lists when the annual file is available."""
    city = _city(geo)
    retail = [
        f for f in features if str(f.get("TYPE") or f.get("type") or "").upper() in RETAIL_TYPES
    ]
    if not retail and geo.county and directory is not None and hasattr(directory, "in_county"):
        # Only a federal marketer's polygon (or nothing) here: ask EIA-861 which
        # utilities report serving this county instead.
        try:
            features = await directory.in_county(geo.region_code, geo.county)
        except Exception as exc:  # noqa: BLE001
            log_event("ground_failed", provider="eia861-directory", reason=str(exc)[:160])
        if features:
            log_event("ground_county_fallback", provider="hifld", candidates=len(features))
    if not features:
        return None
    if len(features) == 1 or directory is None or not hasattr(directory, "customers"):
        return choose(features, geo.region_code, city=city)
    hints: dict[str, Hint] = {}
    for f in features:
        uid = f.get("ID") or f.get("id")
        if uid in (None, ""):
            continue
        uid = str(uid).strip()
        try:
            customers = await directory.customers(uid, geo.region_code)
            serves = (
                await directory.serves(uid, geo.region_code, geo.county) if geo.county else None
            )
        except Exception as exc:  # noqa: BLE001 - hints are optional
            log_event("ground_failed", provider="eia861-directory", reason=str(exc)[:160])
            break
        hints[uid] = (customers, serves)
    if len(hints) > 1:
        log_event("ground_overlap", provider="hifld", candidates=len(features), hinted=len(hints))
    return choose(features, geo.region_code, hints, city=city)


def _city(geo: "GeocodeResult") -> str | None:
    """'Filigree Ct, Ashburn, VA 20147' -> 'Ashburn'."""
    parts = [p.strip() for p in geo.display.split(",")]
    return parts[-2] if len(parts) >= 3 else None


class FakeUtility:
    """Scripted HIFLD features; locate() runs them through the same
    disambiguation as the real provider, so claims cite HIFLD_PAGE."""

    def __init__(
        self,
        utility: Utility | None = None,
        *,
        fail: bool = False,
        features: list[dict[str, Any]] | None = None,
        directory: UtilityDirectory | None = None,
    ) -> None:
        self.utility = utility
        self.fail = fail
        self.features = features
        self.directory = directory

    async def locate(self, geo: "GeocodeResult") -> Utility | None:
        return await disambiguate(geo, await self.candidates(geo.lat, geo.lon), self.directory)

    async def candidates(self, lat: float, lon: float) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError("fake")
        if self.features is None and self.utility is not None:
            u = self.utility
            return [{"NAME": u.raw_name, "TYPE": u.kind, "CUSTOMERS": u.customers, "ID": u.eia_id}]
        return list(self.features or [])
