"""Address to coordinates, state, county and ZIP via the US Census Bureau
geocoder (no key, US only), and for Ireland via OpenStreetMap Nominatim
(NominatimGeocoder). The matched address, normalised, is what the brief id is
hashed from, so two spellings of one address get one brief.

The address itself is never logged and never stored; see brief_id_for().
"""

import asyncio
import hashlib
import io
import json
import re
import time
import zipfile
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from app.config import get_settings
from app.telemetry import log_event

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
# The geographies endpoint (which adds the county) fails on its own at times while
# the plain locations endpoint keeps answering. Then the county comes from the FCC.
CENSUS_LOCATIONS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
FCC_AREA_URL = "https://geo.fcc.gov/api/census/area"
# The ZCTA gazetteer: one row per ZIP Code Tabulation Area with its internal
# point. Published yearly; the newest year that answers is used.
GAZETTEER_ZCTA_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "{year}_Gazetteer/{year}_Gaz_zcta_national.zip"
)
USER_AGENT = "WhosOnMyGrid/0.1 (+https://github.com/EcoPrism/whos-on-my-grid)"
_ZIP5 = re.compile(r"^\d{5}$")
_COUNTY_SUFFIX = re.compile(
    r"\s+(County|Parish|Borough|Census Area|Municipality|Municipio|City and Borough)$", re.I
)


class GeocodeUnavailable(Exception):
    """The geocoder could not be reached or answered with an error."""


@dataclass(frozen=True)
class GeocodeResult:
    display: str  # street and city, no house number: what the UI shows
    lat: float
    lon: float
    region_code: str  # first-level division; US: the two-letter state
    county: str | None
    postal_code: str  # US: the five-digit ZIP
    matched: str  # the geocoder's canonical one-line address, used for the id
    country: str = "US"  # ISO 3166-1 alpha-2
    # IE: the traditional county ("Dublin"), where `county` is the planning
    # authority ("Fingal"). US: None.
    admin_county: str | None = None

    @property
    def state(self) -> str:
        """US spelling of region_code; the prompts and brief text read it."""
        return self.region_code

    @property
    def zip(self) -> str:
        """US spelling of postal_code."""
        return self.postal_code


class Geocoder(Protocol):
    async def geocode(self, address: str) -> GeocodeResult | None: ...


_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalise(address: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", address.lower())).strip()


def brief_id_for(matched: str, country: str = "US") -> str:
    """sha256 of the normalised address, first 16 hex chars. This is the only
    thing derived from the address that is ever written to disk or a log.
    Outside the US the country prefixes the key, so the same street line in two
    countries gets two ids; US ids are what they always were."""
    key = normalise(matched)
    if country.upper() != "US":
        key = f"{country.lower()}|{key}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


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


async def _get_json(url: str, params: dict[str, str], timeout: float) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


@dataclass(frozen=True)
class FccArea:
    state: str  # two-letter code, '' when the API gave none
    county: str | None  # BASENAME style: 'Loudoun'
    county_name: str | None  # as the FCC spells it: 'Loudoun County'


async def fcc_area(
    get_json: Callable[[str, dict[str, str], float], Awaitable[dict]],
    lat: float,
    lon: float,
    timeout: float,
) -> FccArea:
    """State and county for a point from the FCC area API, keyless. Raises
    httpx.HTTPError or ValueError when the API cannot be reached or read."""
    data = await get_json(
        FCC_AREA_URL, {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "json"}, timeout
    )
    try:
        first = (data.get("results") or [{}])[0]
        full = (first.get("county_name") or "").strip()
        state = (first.get("state_code") or "").strip().upper()
    except (IndexError, AttributeError) as exc:
        raise ValueError("unexpected FCC area payload") from exc
    county = _COUNTY_SUFFIX.sub("", full)
    return FccArea(state=state, county=county or None, county_name=full or None)


class CensusGeocoder:
    async def _get_json(self, url: str, params: dict[str, str], timeout: float) -> dict:
        return await _get_json(url, params, timeout)

    async def _county_from_fcc(self, lat: float, lon: float, timeout: float) -> str | None:
        """County name in the Census BASENAME style ('Catawba'), from the
        FCC area API, keyless. None when it cannot be had; never an error."""
        try:
            area = await fcc_area(self._get_json, lat, lon, timeout)
        except (httpx.HTTPError, ValueError):
            return None
        return area.county

    async def geocode(self, address: str) -> GeocodeResult | None:
        params = {
            "address": address,
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "format": "json",
        }
        timeout = get_settings().geocode_timeout_seconds
        with_county = True
        try:
            data = await self._get_json(CENSUS_URL, params, timeout)
        except (httpx.HTTPError, ValueError) as exc:
            log_event("geocode_fallback", reason=exc.__class__.__name__)
            with_county = False
            try:
                data = await self._get_json(
                    CENSUS_LOCATIONS_URL,
                    {k: v for k, v in params.items() if k != "vintage"},
                    timeout,
                )
            except (httpx.HTTPError, ValueError) as exc2:
                raise GeocodeUnavailable(exc2.__class__.__name__) from exc2

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
        lat, lon = float(m["coordinates"]["y"]), float(m["coordinates"]["x"])
        if county is None and not with_county:
            county = await self._county_from_fcc(lat, lon, timeout)
        return GeocodeResult(
            display=display_from(matched, state, zip_code),
            lat=lat,
            lon=lon,
            region_code=state,
            county=county,
            postal_code=zip_code,
            matched=matched,
            country="US",
        )


# --- Ireland: OpenStreetMap Nominatim ------------------------------------------------

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
# A full Eircode: routing key (letter + 2 digits, or D6W) and a 4-character unique id.
EIRCODE = re.compile(r"^(?:[AC-FHKNPRTV-Y]\d{2}|D6W)\s?[0-9AC-FHKNPRTV-Y]{4}$", re.IGNORECASE)
_EIRCODE_IN_TEXT = re.compile(
    r"\b((?:[AC-FHKNPRTV-Y]\d{2}|D6W))\s?[0-9AC-FHKNPRTV-Y]{4}\b", re.IGNORECASE
)
_ROUTING_KEY = re.compile(r"^(?:[AC-FHKNPRTV-Y]\d{2}|D6W)$", re.IGNORECASE)
_DUBLIN_DISTRICT = re.compile(r"^\s*Dublin\s+(\d{1,2})\s*(W)?\s*$", re.IGNORECASE)
# Nominatim answers in the local language unless asked (accept-language=en is sent);
# these catch the city names that still come back in Irish.
_CITY_EN = {
    "Cathair na Gaillimhe": "Galway",
    "Corcaigh": "Cork",
    "Luimneach": "Limerick",
    "Baile Átha Cliath": "Dublin",
}
# Dublin's three county councils, which Nominatim gives as `municipality`.
_DUBLIN_COUNCILS = {
    "fingal": "Fingal",
    "south dublin": "South Dublin",
    "dún laoghaire-rathdown": "Dún Laoghaire-Rathdown",
    "dun laoghaire-rathdown": "Dún Laoghaire-Rathdown",
}
_POSTAL_TYPES = ("postal_district", "postcode", "postal_code")
_COUNTY_PREFIX = re.compile(r"^(?:County|Co\.?)\s+", re.IGNORECASE)


def snap(x: float | str) -> float:
    """Three decimals, about 110 m north-south: the only precision an Irish
    point carries past the geocoder (plan 0.2)."""
    return round(float(x), 3)


def routing_key(postcode: str | None, postal_district: str | None = None) -> str:
    """'D15 T1FD' -> 'D15'; 'D15' -> 'D15'; postal district 'Dublin 15' -> 'D15',
    'Dublin 6W' -> 'D6W'; else ''. A full Eircode never leaves this function."""
    pc = (postcode or "").strip()
    if EIRCODE.match(pc):
        return pc[:3].upper()
    if _ROUTING_KEY.match(pc):
        return pc.upper()
    for text in (postal_district, pc):
        m = _DUBLIN_DISTRICT.match(text or "")
        if m:
            n, w = int(m.group(1)), (m.group(2) or "").upper()
            return "D6W" if (n, w) == (6, "W") else f"D{n:02d}"
    return ""


def _strip_county(name: str | None) -> str | None:
    if not name:
        return None
    return _COUNTY_PREFIX.sub("", name.strip()) or None


def ie_result(
    address: dict, lat: float | str, lon: float | str, *, fallback_key: str = ""
) -> GeocodeResult | None:
    """A Nominatim `address` block (accept-language=en) to an Irish result, per
    plan 0.2. The point is snapped to 3 decimals here, before anything sees it.
    `display` is built from place components only, never a house number, a full
    Eircode or the name of the matched POI."""
    a = {k: v.strip() for k, v in address.items() if isinstance(v, str)}
    if a.get("country_code", "").lower() != "ie":
        return None
    city = _CITY_EN.get(a.get("city", ""), a.get("city", ""))
    admin = _strip_county(a.get("county"))
    muni = _DUBLIN_COUNCILS.get(a.get("municipality", "").lower())
    if muni:
        authority: str | None = muni
    elif admin == "Dublin" and city == "Dublin":
        authority = "Dublin City"
    elif city in ("Cork", "Galway"):
        authority = f"{city} City"
    else:
        authority = admin
    key = routing_key(a.get("postcode"), a.get("postal_district")) or fallback_key
    place = next(
        (v for v in (a.get("town"), a.get("village"), city, a.get("suburb"), a.get("road")) if v),
        "",
    )
    shown_authority = authority
    if authority and (authority == admin or (place and authority.startswith(place))):
        shown_authority = None
    display = ", ".join(
        b for b in (place, shown_authority, f"Co. {admin}" if admin else "", key) if b
    )
    slat, slon = snap(lat), snap(lon)
    street = " ".join(b for b in (a.get("house_number"), a.get("road")) if b)
    matched = ", ".join(
        b
        for b in (street, place if place != a.get("road") else "", f"Co. {admin}" if admin else "")
        if b
    )
    postcode = a.get("postcode") or key
    if matched and postcode:
        matched = f"{matched}, {postcode}"
    if matched and not EIRCODE.match(a.get("postcode", "")):
        # Without a full Eircode the text names a town or a road, not a place: two
        # road-less hits in one town (a centre, the town node) would share a brief
        # id. The snapped point keeps them apart and is no finer than the brief's own.
        matched = f"{matched}, {slat:.3f},{slon:.3f}"
    return GeocodeResult(
        display=display or f"{slat:.3f}, {slon:.3f}",
        lat=slat,
        lon=slon,
        region_code=a.get("ISO3166-2-lvl6", "").upper(),
        county=authority,
        postal_code=key,
        matched=matched or f"{slat:.3f},{slon:.3f}",
        country="IE",
        admin_county=admin,
    )


class _Throttle:
    """At most one request per `interval` seconds through one throttle. The
    lock is made on first use in the running loop (an asyncio.Lock is bound to
    one), so a process-wide throttle survives test loops."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.clock = clock
        self.sleep = sleep
        self.last: float | None = None
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock, self._loop = asyncio.Lock(), loop
        return self._lock

    async def wait(self, interval: float) -> None:
        async with self._get_lock():
            if self.last is not None:
                gap = interval - (self.clock() - self.last)
                if gap > 0:
                    await self.sleep(gap)
            self.last = self.clock()


# One throttle per Nominatim base URL in this process: the public instance's
# policy is one request a second from the whole application.
_THROTTLES: dict[str, _Throttle] = {}


def _throttle_for(base_url: str) -> _Throttle:
    return _THROTTLES.setdefault(base_url, _Throttle())


class NominatimGeocoder:
    """Ireland. OpenStreetMap Nominatim search, English names, Irish results only.

    - Rate: one request per `min_interval` seconds per base URL, process-wide.
    - Cache: an in-memory LRU of `cache_size` answers keyed by the normalised
      text; never written to disk.
    - A full Eircode that finds nothing is retried once as its routing key.
    - A hit without county or ISO code gets one /reverse at zoom 10.
    - Transport errors, timeouts and HTTP errors raise GeocodeUnavailable with
      the exception's class name only: an httpx message holds the URL, and the
      URL holds the address or the point."""

    def __init__(
        self,
        base_url: str = NOMINATIM_URL,
        *,
        email: str = "",
        min_interval: float = 1.0,
        timeout: float | None = None,
        cache_size: int = 512,
        transport: httpx.AsyncBaseTransport | None = None,
        throttle: _Throttle | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.min_interval = min_interval
        self.timeout = timeout
        self.cache_size = cache_size
        self.transport = transport
        self.throttle = throttle or _throttle_for(self.base_url)
        self._cache: OrderedDict[str, GeocodeResult | None] = OrderedDict()

    def _params(self, extra: dict[str, str]) -> dict[str, str]:
        p = {**extra, "format": "jsonv2", "addressdetails": "1", "accept-language": "en"}
        if self.email:
            p["email"] = self.email
        return p

    async def _get(self, path: str, params: dict[str, str]) -> object:
        await self.throttle.wait(self.min_interval)
        timeout = self.timeout or get_settings().geocode_timeout_seconds
        try:
            async with httpx.AsyncClient(
                timeout=timeout, headers={"User-Agent": USER_AGENT}, transport=self.transport
            ) as client:
                r = await client.get(f"{self.base_url}/{path}", params=self._params(params))
                r.raise_for_status()
                return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            name = exc.__class__.__name__
            log_event("geocode_unavailable", provider="nominatim", reason=name)
            raise GeocodeUnavailable(name) from None

    async def _search(self, q: str) -> list[dict]:
        data = await self._get("search", {"q": q, "countrycodes": "ie", "limit": "1"})
        return [h for h in data if isinstance(h, dict)] if isinstance(data, list) else []

    async def _reverse(self, lat: str, lon: str) -> dict:
        data = await self._get("reverse", {"lat": lat, "lon": lon, "zoom": "10"})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _acceptable(hit: dict, *, postal_only: bool = False) -> bool:
        kind = str(hit.get("type") or hit.get("addresstype") or "")
        if kind in _POSTAL_TYPES:
            return True
        if postal_only:
            return False
        try:
            return int(hit.get("place_rank") or 0) >= 16
        except (TypeError, ValueError):
            return False

    async def _lookup(self, address: str) -> GeocodeResult | None:
        hits = await self._search(address)
        fallback_key = ""
        postal_only = False
        eircode = _EIRCODE_IN_TEXT.search(address)
        if not hits and eircode:
            fallback_key = eircode.group(1).upper()
            retry = _WS.sub(" ", _EIRCODE_IN_TEXT.sub(fallback_key, address, count=1)).strip()
            postal_only = normalise(retry) == fallback_key.lower()
            hits = await self._search(retry)
        if not hits or not self._acceptable(hits[0], postal_only=postal_only):
            return None
        hit = hits[0]
        addr = hit.get("address") if isinstance(hit.get("address"), dict) else {}
        if str(addr.get("country_code", "")).lower() != "ie":
            return None
        if not (addr.get("ISO3166-2-lvl6") and addr.get("county")):
            rev = await self._reverse(str(hit.get("lat")), str(hit.get("lon")))
            rev_addr = rev.get("address") if isinstance(rev.get("address"), dict) else {}
            if str(rev_addr.get("country_code", "ie")).lower() == "ie":
                addr = {**rev_addr, **addr}
        try:
            return ie_result(addr, hit["lat"], hit["lon"], fallback_key=fallback_key)
        except (KeyError, TypeError, ValueError):
            return None

    async def geocode(self, address: str) -> GeocodeResult | None:
        key = normalise(address)
        if not key:
            return None
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result = await self._lookup(address)
        self._cache[key] = result
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return result


def parse_gazetteer(text: str) -> dict[str, tuple[float, float]]:
    """ZCTA -> (lat, lon) from the gazetteer text. Tab-delimited up to 2024,
    pipe-delimited from 2025; the header names the columns either way."""
    lines = text.splitlines()
    if not lines:
        return {}
    sep = "|" if "|" in lines[0] else "\t"
    head = [h.strip() for h in lines[0].split(sep)]
    try:
        i_id, i_lat, i_lon = head.index("GEOID"), head.index("INTPTLAT"), head.index("INTPTLONG")
    except ValueError:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(sep)]
        if len(cols) <= max(i_id, i_lat, i_lon):
            continue
        try:
            out[cols[i_id]] = (float(cols[i_lat]), float(cols[i_lon]))
        except ValueError:
            continue
    return out


class ZctaCentroids:
    """ZIP to a point, state and county, keyless. The point is the internal
    point of the ZIP's Census ZCTA from the gazetteer, downloaded once to the
    ground cache and loaded on first use. State and county come from the FCC
    area API the brief geocoder already falls back to.

    A ZIP is personal data like an address: it is never logged and never
    written to disk. The cache holds the whole national file, nothing per ZIP."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        years: list[int] | None = None,
        timeout: float = 60.0,
        fcc_timeout: float | None = None,
        retry_after_s: float = 300.0,
    ) -> None:
        self.path = cache_dir / "gazetteer_zcta.json"
        now = time.gmtime().tm_year
        self.years = years or [now, now - 1, now - 2, now - 3]
        self.timeout = timeout
        self.fcc_timeout = fcc_timeout
        self._lock = asyncio.Lock()
        self._points: dict[str, tuple[float, float]] | None = None
        # A failed download is remembered for a cool-down, so an outage fails
        # each request at once instead of re-downloading behind the lock.
        self.retry_after_s = retry_after_s
        self._failed_at = 0.0
        self._failure = ""

    async def _get_json(self, url: str, params: dict[str, str], timeout: float) -> dict:
        return await _get_json(url, params, timeout)

    async def _get_bytes(self, url: str) -> bytes:
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content

    async def _download(self) -> tuple[int, str, dict[str, tuple[float, float]]]:
        last: Exception | None = None
        for year in self.years:
            url = GAZETTEER_ZCTA_URL.format(year=year)
            try:
                raw = await self._get_bytes(url)
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
                    text = zf.read(name).decode("utf-8-sig", errors="replace")
            except (httpx.HTTPError, zipfile.BadZipFile, StopIteration, KeyError) as exc:
                last = exc
                continue
            points = parse_gazetteer(text)
            if points:
                return year, url, points
        reason = last.__class__.__name__ if last else "empty"
        raise GeocodeUnavailable(f"ZCTA gazetteer: {reason}")

    async def _load(self) -> dict[str, tuple[float, float]]:
        async with self._lock:
            if self._points is not None:
                return self._points
            if self.path.exists():
                try:
                    with open(self.path, encoding="utf-8") as f:
                        saved = json.load(f)
                    points = {k: (float(v[0]), float(v[1])) for k, v in saved["zctas"].items()}
                    if points:
                        self._points = points
                        return points
                except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
                    pass
            if time.time() - self._failed_at < self.retry_after_s:
                raise GeocodeUnavailable(self._failure)
            try:
                year, url, points = await self._download()
            except GeocodeUnavailable as exc:
                self._failed_at, self._failure = time.time(), str(exc)
                raise
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "fetched_at": time.time(),
                        "year": year,
                        "source_url": url,
                        "zctas": {k: [v[0], v[1]] for k, v in points.items()},
                    },
                    f,
                    separators=(",", ":"),
                )
            tmp.replace(self.path)
            log_event("ground_snapshot", provider="census_gazetteer", year=year, zctas=len(points))
            self._points = points
            return points

    async def locate(self, zip5: str) -> GeocodeResult | None:
        """None when the input is not five digits, is not a ZCTA, or the FCC
        places it in no state. GeocodeUnavailable when the gazetteer or the
        FCC cannot be reached."""
        zip5 = (zip5 or "").strip()
        if not _ZIP5.match(zip5):
            return None
        point = (await self._load()).get(zip5)
        if point is None:
            return None
        lat, lon = point
        timeout = self.fcc_timeout or get_settings().geocode_timeout_seconds
        try:
            area = await fcc_area(self._get_json, lat, lon, timeout)
        except (httpx.HTTPError, ValueError) as exc:
            raise GeocodeUnavailable(f"FCC area: {exc.__class__.__name__}") from exc
        if not area.state:
            return None
        bits = [f"ZIP {zip5}", *([area.county_name] if area.county_name else []), area.state]
        return GeocodeResult(
            display=", ".join(bits),
            lat=lat,
            lon=lon,
            region_code=area.state,
            county=area.county,
            postal_code=zip5,
            matched=f"zip:{zip5}",
            country="US",
        )


class FakeZctaCentroids:
    """Returns the scripted result for any ZIP, or None when scripted so."""

    def __init__(self, result: GeocodeResult | None = None, *, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.calls = 0

    async def locate(self, zip5: str) -> GeocodeResult | None:
        self.calls += 1
        if self.fail:
            raise GeocodeUnavailable("fake")
        return self.result


class FakeGeocoder:
    """Returns the scripted result for any address, or None when scripted so.
    With `by_address`, answers from that table instead, keyed by the
    normalised text (None for anything not in it)."""

    def __init__(
        self,
        result: GeocodeResult | None = None,
        *,
        fail: bool = False,
        by_address: Mapping[str, GeocodeResult] | None = None,
    ) -> None:
        self.result = result
        self.fail = fail
        self.by_address = (
            {normalise(k): v for k, v in by_address.items()} if by_address is not None else None
        )
        self.calls = 0

    async def geocode(self, address: str) -> GeocodeResult | None:
        self.calls += 1
        if self.fail:
            raise GeocodeUnavailable("fake")
        if self.by_address is not None:
            return self.by_address.get(normalise(address))
        return self.result
