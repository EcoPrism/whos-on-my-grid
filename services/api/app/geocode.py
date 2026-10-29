"""Address to coordinates, state, county and ZIP via the US Census Bureau
geocoder. No key, US only. The matched address, normalised, is what the brief
id is hashed from, so two spellings of one address get one brief.

The address itself is never logged and never stored; see brief_id_for().
"""

import asyncio
import hashlib
import io
import json
import re
import time
import zipfile
from collections.abc import Awaitable, Callable
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
            state=state,
            county=county,
            zip=zip_code,
            matched=matched,
        )


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
            state=area.state,
            county=area.county,
            zip=zip5,
            matched=f"zip:{zip5}",
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
