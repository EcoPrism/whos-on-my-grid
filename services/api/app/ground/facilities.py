"""The facility database: PeeringDB (colocation sites, US snapshot) and
OpenStreetMap (every building tagged as a data center, which is where the
hyperscale campuses are). Existence, location and distance come from here and
only from here; a model never adds or removes a facility.

Both sources are free and keyless. The PeeringDB snapshot is cached on disk
for a week; OpenStreetMap is queried per brief through Overpass, on the first
mirror that answers.
"""

import asyncio
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.ground.types import FIVE_MILES_KM, GroundFacility
from app.telemetry import log_event

USER_AGENT = "WhosOnMyGrid/0.1 (+https://github.com/EcoPrism/whos-on-my-grid)"

PEERINGDB_URL = (
    "https://www.peeringdb.com/api/fac?country=US&status=ok&limit=5000"
    "&fields=id,name,org_name,address1,city,state,latitude,longitude"
)
PEERINGDB_MAX_AGE_S = 7 * 86_400

OVERPASS_ENDPOINTS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_QUERY = """[out:json][timeout:40];
(
  nwr["telecom"="data_center"](around:{r},{lat},{lon});
  nwr["building"="data_center"](around:{r},{lat},{lon});
  nwr["construction"="data_center"](around:{r},{lat},{lon});
  nwr["industrial"="data_center"](around:{r},{lat},{lon});
);
out center tags;"""

MAX_FACILITIES = 60


class GroundError(Exception):
    """No facility source answered."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class RawSite:
    provider: str  # peeringdb | osm
    key: str  # fac/123 | way/456
    name: str | None
    operator: str | None
    status: str  # live | under_construction
    lat: float
    lon: float
    url: str
    is_building: bool = True


class FacilitySource(Protocol):
    name: str

    async def near(self, lat: float, lon: float, radius_km: float) -> list[RawSite]: ...


# --- PeeringDB ---------------------------------------------------------------


class PeeringDBSource:
    name = "PeeringDB"

    def __init__(self, cache_dir: Path, *, url: str = PEERINGDB_URL, timeout: float = 25.0) -> None:
        self.path = cache_dir / "peeringdb_fac.json"
        self.url = url
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._data: list[dict[str, Any]] | None = None
        self._loaded_at = 0.0

    async def _snapshot(self) -> list[dict[str, Any]]:
        async with self._lock:
            if self._data is not None and time.time() - self._loaded_at < PEERINGDB_MAX_AGE_S:
                return self._data
            stale: list[dict[str, Any]] | None = None
            if self.path.exists():
                with open(self.path, encoding="utf-8") as f:
                    saved = json.load(f)
                stale = saved.get("data") or []
                if time.time() - float(saved.get("fetched_at", 0)) < PEERINGDB_MAX_AGE_S:
                    self._data, self._loaded_at = stale, time.time()
                    return stale
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, headers={"User-Agent": USER_AGENT}
                ) as client:
                    r = await client.get(self.url)
                    r.raise_for_status()
                    data = r.json().get("data") or []
            except (httpx.HTTPError, ValueError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                reason = f"{exc.__class__.__name__}{f' {status}' if status else ''}"
                if stale is not None:
                    log_event("ground_stale", provider="peeringdb", reason=reason)
                    self._data, self._loaded_at = stale, time.time()
                    return stale
                raise GroundError(f"PeeringDB: {reason}") from exc
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": time.time(), "data": data}, f)
            tmp.replace(self.path)
            log_event("ground_snapshot", provider="peeringdb", facilities=len(data))
            self._data, self._loaded_at = data, time.time()
            return data

    async def near(self, lat: float, lon: float, radius_km: float) -> list[RawSite]:
        out = []
        for f in await self._snapshot():
            flat, flon = f.get("latitude"), f.get("longitude")
            if not isinstance(flat, int | float) or not isinstance(flon, int | float):
                continue
            if haversine_km(lat, lon, flat, flon) > radius_km:
                continue
            out.append(
                RawSite(
                    provider="peeringdb",
                    key=f"fac/{f['id']}",
                    name=f.get("name") or None,
                    operator=f.get("org_name") or None,
                    status="live",
                    lat=float(flat),
                    lon=float(flon),
                    url=f"https://www.peeringdb.com/fac/{f['id']}",
                )
            )
        return out


# --- OpenStreetMap -----------------------------------------------------------


class OverpassSource:
    name = "OpenStreetMap"

    def __init__(self, endpoints: list[str] | None = None, *, timeout: float = 45.0) -> None:
        self.endpoints = endpoints or OVERPASS_ENDPOINTS
        self.timeout = timeout

    async def near(self, lat: float, lon: float, radius_km: float) -> list[RawSite]:
        query = OVERPASS_QUERY.format(r=int(radius_km * 1000), lat=f"{lat:.5f}", lon=f"{lon:.5f}")
        last = "no endpoint configured"
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"User-Agent": USER_AGENT}
        ) as client:
            for ep in self.endpoints:
                try:
                    r = await client.post(ep, data={"data": query})
                    r.raise_for_status()
                    elements = r.json().get("elements") or []
                except (httpx.HTTPError, ValueError) as exc:
                    last = f"{ep}: {exc.__class__.__name__}"
                    log_event("ground_endpoint_failed", provider="osm", reason=last[:120])
                    continue
                return [s for s in (_osm_site(e) for e in elements) if s is not None]
        raise GroundError(f"OpenStreetMap: {last}")


def _osm_site(e: dict[str, Any]) -> RawSite | None:
    tags = e.get("tags") or {}
    center = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
    if not isinstance(center.get("lat"), int | float):
        return None
    building = tags.get("building")
    status = "live"
    if tags.get("construction") == "data_center" or building == "construction":
        status = "under_construction"
    is_building = building is not None or e["type"] == "node"
    return RawSite(
        provider="osm",
        key=f"{e['type']}/{e['id']}",
        name=tags.get("name") or None,
        operator=tags.get("operator") or tags.get("owner") or tags.get("brand") or None,
        status=status,
        lat=float(center["lat"]),
        lon=float(center["lon"]),
        url=f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
        is_building=is_building,
    )


# --- merge -------------------------------------------------------------------

# Spellings of one operator across the two datasets.
_ALIASES = {
    "facebook": "meta",
    "meta platforms": "meta",
    "amazon web services": "amazon",
    "amazon data services": "amazon",
    "aws": "amazon",
    "microsoft corporation": "microsoft",
    "google llc": "google",
    "stack infrastructure": "stack",
    "digital realty trust": "digital realty",
    "equinix inc": "equinix",
    "ntt data": "ntt",
    "ntt global data centers": "ntt",
}
_SUFFIX = re.compile(r"\b(inc|llc|corp|corporation|co|ltd|limited|lp|plc)\b\.?")
_PUNCT = re.compile(r"[^a-z0-9 ]+")

UNKNOWN_OPERATOR = "Operator not recorded in OpenStreetMap"

# Operators whose name at the front of a facility name identifies them, for
# records tagged with a name but no operator ("Vantage WA11").
_OPERATOR_VOCAB = [
    "Equinix", "Digital Realty", "Vantage", "Sabey", "Microsoft", "Meta", "Facebook", "Google",
    "Amazon", "AWS", "NTT", "RagingWire", "CyrusOne", "STACK", "QTS", "CloudHQ", "Aligned",
    "Compass", "Iron Mountain", "CoreSite", "Flexential", "H5", "EdgeCore", "Novva", "Switch",
    "Cologix", "DataBank", "Lumen", "Level 3", "Centersquare", "PowerHouse", "Yahoo", "Apple",
    "Oracle", "Vantage", "Stream", "T5", "Cyxtera", "Evoque", "Lightedge", "Colocation Northwest",
    "Centeris", "Intergate", "Westin", "Zayo", "Telx", "365", "Expedient", "TierPoint",
]  # fmt: skip


_VOCAB_ALIASES = {"Facebook": "Meta", "AWS": "Amazon", "RagingWire": "NTT", "Intergate": "Sabey"}


def operator_from_name(name: str | None) -> str | None:
    if not name:
        return None
    low = name.lower()
    for op in _OPERATOR_VOCAB:
        if low.startswith(op.lower()):
            return _VOCAB_ALIASES.get(op, op)
    return None


def norm_operator(name: str | None) -> str | None:
    if not name:
        return None
    n = _PUNCT.sub(" ", name.lower().replace("&", " and "))
    n = _SUFFIX.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return _ALIASES.get(n, n) or None


def _link(a: RawSite, b: RawSite) -> bool:
    """Two records describe one site or one campus."""
    d = haversine_km(a.lat, a.lon, b.lat, b.lon)
    oa = norm_operator(a.operator or operator_from_name(a.name))
    ob = norm_operator(b.operator or operator_from_name(b.name))
    if oa and ob:
        return (oa == ob and d < 0.6) or d < 0.05
    if d < 0.15:
        return True
    if not oa and not ob:
        return d < 0.3
    return d < 0.2


def build_facilities(
    sites: list[RawSite], lat: float, lon: float, radius_km: float = FIVE_MILES_KM
) -> list[GroundFacility]:
    """Single-linkage clustering of raw records into facilities, then distance
    from the address, nearest first."""
    n = len(sites)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _link(sites[i], sites[j]):
                parent[find(i)] = find(j)

    groups: dict[int, list[RawSite]] = {}
    for i, s in enumerate(sites):
        groups.setdefault(find(i), []).append(s)

    out = []
    for members in groups.values():
        f = _facility(members, lat, lon)
        if f.distance_km <= radius_km:
            out.append(f)
    out.sort(key=lambda f: f.distance_km)
    return disambiguate(out[:MAX_FACILITIES], lat, lon)


_COMPASS = (
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
)


def compass(lat: float, lon: float, to_lat: float, to_lon: float) -> str:
    """Eight-point direction from the address to a point."""
    dlon = math.radians(to_lon - lon)
    p1, p2 = math.radians(lat), math.radians(to_lat)
    x = math.sin(dlon) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
    return _COMPASS[int((bearing + 22.5) // 45) % 8]


def disambiguate(facilities: list[GroundFacility], lat: float, lon: float) -> list[GroundFacility]:
    """Two clusters of the same operator get the same generated name
    ("Amazon Web Services (2 buildings)"). Names are keys downstream, in the
    assembler's merge and the page, so repeated names get the direction from
    the address, then the distance if that still collides."""
    counts = Counter(f.name for f in facilities)
    out: list[GroundFacility] = []
    seen: set[str] = set()
    for f in facilities:
        name = f.name
        if counts[name] > 1:
            name = f"{f.name}, {compass(lat, lon, f.lat, f.lon)}"
        if name in seen:
            name = f"{name}, {f.distance_km * 0.621371:.1f} mi"
        n = 2
        while name in seen:
            name = f"{f.name} #{n}"
            n += 1
        seen.add(name)
        out.append(replace(f, name=name) if name != f.name else f)
    return out


def _facility(members: list[RawSite], lat: float, lon: float) -> GroundFacility:
    pdb = [m for m in members if m.provider == "peeringdb"]
    named = [m for m in members if m.name]
    operators = Counter(m.operator or operator_from_name(m.name) for m in members)
    operators.pop(None, None)
    operator = operators.most_common(1)[0][0] if operators else None
    buildings = sum(1 for m in members if m.provider == "osm" and m.is_building) or 1

    if pdb:
        # The directory record is authoritative for its own site.
        anchor = pdb[0]
        name = anchor.name or anchor.operator or "Colocation facility"
        operator = anchor.operator or operator
    elif named:
        anchor = named[0]
        names = Counter(m.name for m in named)
        top, count = names.most_common(1)[0]
        name = top
        if len(members) > 1 and len(names) > 1 and operator:
            name = f"{operator} ({buildings} buildings)"
        elif len(names) > 1 and count == 1:
            name = f"{top} and {len(names) - 1} more"
    else:
        anchor = members[0]
        name = (
            f"{operator} ({buildings} buildings)"
            if operator and buildings > 1
            else (operator or "Unnamed data-center building")
        )
        if not operator and buildings > 1:
            name = f"{buildings} unnamed data-center buildings"

    clat = sum(m.lat for m in members) / len(members)
    clon = sum(m.lon for m in members) / len(members)
    status = "live" if any(m.status == "live" for m in members) else "under_construction"
    source_title = (
        f"PeeringDB facility {anchor.key.split('/')[-1]}"
        if anchor.provider == "peeringdb"
        else f"OpenStreetMap {anchor.key.replace('/', ' ')}"
    )
    return GroundFacility(
        name=name,
        operator=operator or UNKNOWN_OPERATOR,
        operator_known=operator is not None,
        status=status,
        lat=round(clat, 6),
        lon=round(clon, 6),
        distance_km=round(haversine_km(lat, lon, clat, clon), 2),
        source_url=anchor.url,
        source_title=source_title,
        buildings=buildings,
        providers=tuple(sorted({m.provider for m in members})),
    )


# --- database ----------------------------------------------------------------


class FacilityDatabase:
    """All sources asked in parallel; one failing is a note, all failing is an
    error the caller turns into an `unavailable` section."""

    def __init__(self, sources: list[FacilitySource]) -> None:
        self.sources = sources

    async def near(
        self, lat: float, lon: float, radius_km: float = FIVE_MILES_KM
    ) -> tuple[list[GroundFacility], list[str]]:
        results = await asyncio.gather(
            *(s.near(lat, lon, radius_km) for s in self.sources), return_exceptions=True
        )
        sites: list[RawSite] = []
        notes: list[str] = []
        ok = 0
        for src, res in zip(self.sources, results, strict=True):
            if isinstance(res, BaseException):
                log_event("ground_failed", provider=src.name, reason=str(res)[:160])
                notes.append(f"{src.name} could not be reached, so its facilities are missing.")
                continue
            ok += 1
            sites.extend(res)
        if not ok:
            raise GroundError("; ".join(notes))
        return build_facilities(sites, lat, lon, radius_km), notes


class FakeFacilityDatabase:
    def __init__(
        self,
        facilities: list[GroundFacility] | None = None,
        *,
        fail: bool = False,
        notes: list[str] | None = None,
    ) -> None:
        self.facilities = facilities or []
        self.fail = fail
        self.notes = notes or []
        self.calls = 0

    async def near(
        self, lat: float, lon: float, radius_km: float = FIVE_MILES_KM
    ) -> tuple[list[GroundFacility], list[str]]:
        self.calls += 1
        if self.fail:
            raise GroundError("fake")
        return list(self.facilities), list(self.notes)
