"""Households in a ZIP from the Census Bureau's American Community Survey,
5-year estimates, table B11001 (Household Type), total households
(B11001_001E) for the ZIP Code Tabulation Area.

The whole national ZCTA table is fetched once, cached under data/ground/acs/
and refreshed when a newer ACS year is published. Nothing is fetched or
written per ZIP, so a ZIP is never logged and never on disk.

The table comes from api.census.gov when a key is set and from
data.census.gov's table API otherwise; api.census.gov no longer answers
without a key. Either way the cited page is the data.census.gov table API for
the one ZCTA: keyless, fetchable, and it carries the count verbatim.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.telemetry import log_event

USER_AGENT = "WhosOnMyGrid/0.1 (+https://github.com/EcoPrism/whos-on-my-grid)"
TABLE = "B11001"
VARIABLE = "B11001_001E"
CENSUS_API_URL = "https://api.census.gov/data/{year}/acs/acs5"
DATA_CENSUS_API_URL = "https://data.census.gov/api/access/data/table"
# Every ZCTA in the nation, in data.census.gov's geography syntax.
ALL_ZCTAS = "010XX00US$8600000"
ZCTA_PREFIX = "860Z200US"
MAX_AGE_S = 30 * 86_400
RETRY_AFTER_S = 900.0  # after a failed cold fetch, how long to answer None at once
_ZIP5 = re.compile(r"^\d{5}$")


@dataclass(frozen=True)
class Households:
    count: int
    source_url: str  # the ACS table B11001_001E for the ZCTA, keyless
    source_title: str
    as_of: str  # "ACS 5-year 2024"
    quote: str = ""  # the count as the source page writes it


def households(zip5: str, count: int, year: int) -> Households:
    return Households(
        count=count,
        source_url=f"{DATA_CENSUS_API_URL}?id=ACSDT5Y{year}.{TABLE}&g={ZCTA_PREFIX}{zip5}",
        source_title=(
            f"U.S. Census Bureau, American Community Survey 5-year {year}, "
            f"table {TABLE} Household Type, ZCTA5 {zip5}"
        ),
        as_of=f"ACS 5-year {year}",
        quote=str(count),
    )


class HouseholdsSource(Protocol):
    async def for_zcta(self, zip5: str) -> Households | None: ...


def _count(value: Any) -> int | None:
    """ACS writes estimates as strings and marks missing ones with large
    negative sentinels; only a non-negative whole number is a count."""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def parse_data_census(payload: dict[str, Any]) -> dict[str, int]:
    """ZCTA -> households from a data.census.gov table API response."""
    rows = (payload.get("response") or {}).get("data") or []
    if len(rows) < 2:
        return {}
    head = rows[0]
    try:
        i_geo, i_val = head.index("GEO_ID"), head.index(VARIABLE)
    except ValueError:
        return {}
    out: dict[str, int] = {}
    for row in rows[1:]:
        geo = str(row[i_geo] or "")
        n = _count(row[i_val])
        if geo.startswith(ZCTA_PREFIX) and n is not None:
            out[geo[len(ZCTA_PREFIX) :]] = n
    return out


def parse_census_api(payload: list[list[Any]]) -> dict[str, int]:
    """ZCTA -> households from an api.census.gov response (a header row, then
    one row per ZCTA)."""
    if not isinstance(payload, list) or len(payload) < 2:
        return {}
    head = payload[0]
    try:
        i_zip, i_val = head.index("zip code tabulation area"), head.index(VARIABLE)
    except ValueError:
        return {}
    out: dict[str, int] = {}
    for row in payload[1:]:
        n = _count(row[i_val])
        if n is not None:
            out[str(row[i_zip])] = n
    return out


class AcsHouseholds:
    def __init__(
        self,
        cache_dir: Path,
        *,
        api_key: str = "",
        years: list[int] | None = None,
        timeout: float = 120.0,
        max_age_s: float = MAX_AGE_S,
        retry_after_s: float = RETRY_AFTER_S,
    ) -> None:
        self.path = cache_dir / "acs" / "b11001_zcta.json"
        self.api_key = api_key
        now = time.gmtime().tm_year
        self.years = years or [now - 1, now - 2, now - 3]
        self.timeout = timeout
        self.max_age_s = max_age_s
        self._lock = asyncio.Lock()
        self._year: int | None = None
        self._counts: dict[str, int] | None = None
        self._loaded_at = 0.0
        # When neither API answered and nothing is cached: skip refetching until
        # the cool-down passes, so an outage does not hold every request.
        self.retry_after_s = retry_after_s
        self._failed_at = 0.0

    async def _get_json(self, url: str, params: dict[str, str]) -> Any:
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"User-Agent": USER_AGENT}
        ) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()

    async def _fetch_year(self, year: int) -> dict[str, int]:
        """The national ZCTA table for one ACS year; empty when that year is
        not published or neither API answers."""
        if self.api_key:
            try:
                data = await self._get_json(
                    CENSUS_API_URL.format(year=year),
                    {
                        "get": VARIABLE,
                        "for": "zip code tabulation area:*",
                        "key": self.api_key,
                    },
                )
                counts = parse_census_api(data)
                if counts:
                    return counts
            except (httpx.HTTPError, ValueError) as exc:
                log_event("ground_fallback", provider="acs_api", reason=exc.__class__.__name__)
        try:
            data = await self._get_json(
                DATA_CENSUS_API_URL, {"id": f"ACSDT5Y{year}.{TABLE}", "g": ALL_ZCTAS}
            )
        except (httpx.HTTPError, ValueError):
            return {}
        return parse_data_census(data) if isinstance(data, dict) else {}

    def _read_cache(self) -> tuple[int, dict[str, int], float] | None:
        if not self.path.exists():
            return None
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
            counts = {str(k): int(v) for k, v in saved["households"].items()}
            return int(saved["year"]), counts, float(saved.get("fetched_at", 0))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def _write_cache(self, year: int, counts: dict[str, int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"fetched_at": time.time(), "year": year, "households": counts},
                f,
                separators=(",", ":"),
            )
        tmp.replace(self.path)

    async def _snapshot(self) -> tuple[int, dict[str, int]] | None:
        async with self._lock:
            fresh = time.time() - self._loaded_at < self.max_age_s
            if self._counts is not None and self._year is not None and fresh:
                return self._year, self._counts
            if self._counts is None and time.time() - self._failed_at < self.retry_after_s:
                return None
            cached = self._read_cache()
            if cached and time.time() - cached[2] < self.max_age_s:
                self._year, self._counts, self._loaded_at = cached[0], cached[1], time.time()
                return self._year, self._counts
            # Stale or missing: look for a year newer than the one held.
            have = cached[0] if cached else 0
            for year in sorted(self.years, reverse=True):
                if year <= have:
                    break
                counts = await self._fetch_year(year)
                if counts:
                    self._write_cache(year, counts)
                    log_event("ground_snapshot", provider="acs", year=year, zctas=len(counts))
                    self._year, self._counts, self._loaded_at = year, counts, time.time()
                    return year, counts
            if cached:
                # Nothing newer published: keep the held year, checked again later.
                self._write_cache(cached[0], cached[1])
                self._year, self._counts, self._loaded_at = cached[0], cached[1], time.time()
                return self._year, self._counts
            log_event("ground_unavailable", provider="acs")
            self._failed_at = time.time()
            return None

    async def for_zcta(self, zip5: str) -> Households | None:
        """None when the input is not five digits, the ZCTA has no household
        estimate, or the ACS cannot be reached. Never an error."""
        zip5 = (zip5 or "").strip()
        if not _ZIP5.match(zip5):
            return None
        snap = await self._snapshot()
        if snap is None:
            return None
        year, counts = snap
        n = counts.get(zip5)
        if not n:
            return None
        return households(zip5, n, year)


class FakeHouseholds:
    """Returns `count` households for any ZIP, or None when scripted so."""

    def __init__(self, count: int | None = 25_000, *, year: int = 2024) -> None:
        self.count = count
        self.year = year
        self.calls = 0

    async def for_zcta(self, zip5: str) -> Households | None:
        self.calls += 1
        if self.count is None:
            return None
        return households(zip5, self.count, self.year)
