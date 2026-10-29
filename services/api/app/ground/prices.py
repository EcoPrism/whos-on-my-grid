"""Residential electricity prices from EIA.

Two series. The state series comes from Form EIA-861M, the monthly sales and
revenue workbook by state and sector: current to within two months, trailing
twelve months against the twelve ending 24 months earlier. The utility series
comes from the annual Form EIA-861 "Sales to Ultimate Customers" workbook,
one row per utility and state: a year old, but it is the price the people on
this utility actually paid, which for a public utility district next to a
hydro dam is a different number from the state average. Price is revenue
over sales, so every figure is revenue-weighted; typical household usage is
the same table's residential sales divided by residential customers.

Both are free and keyless; files are cached on disk for a month.
"""

import asyncio
import io
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from app.ground.types import PriceSeries
from app.telemetry import log_event

USER_AGENT = "WhosOnMyGrid/0.1 (+https://github.com/EcoPrism/whos-on-my-grid)"
MAX_AGE_S = 30 * 86_400
WINDOW_MONTHS = 24

EIA861M_XLSX = "https://www.eia.gov/electricity/data/eia861m/xls/sales_revenue.xlsx"
EIA861M_PAGE = "https://www.eia.gov/electricity/data/eia861m/"
EIA861M_TITLE = "EIA-861M, Monthly Electric Power Industry Report: sales and revenue by state"
EPM_TABLE_URL = "https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a"
EPM_TABLE_TITLE = "EIA Electric Power Monthly, Table 5.6.A: average residential price by state"

EIA861_PAGE = "https://www.eia.gov/electricity/data/eia861/"
EIA861_TITLE = "EIA-861, Annual Electric Power Industry Report: sales to ultimate customers"
EIA861_ZIP = "https://www.eia.gov/electricity/data/eia861/zip/f861{year}.zip"
EIA861_ARCHIVE_ZIP = "https://www.eia.gov/electricity/data/eia861/archive/zip/f861{year}.zip"

Row = tuple[int, int, float, float, float, str]  # year, month, revenue k$, sales MWh, customers
UtilityRow = tuple[float, float, float, str]  # revenue k$, sales MWh, customers, utility name
Key = tuple[str, str]  # (EIA utility number, state)


class PriceProvider(Protocol):
    async def series(self, jurisdiction: str) -> PriceSeries | None: ...


class UtilityPriceProvider(Protocol):
    async def for_utility(self, eia_id: str, state: str) -> PriceSeries | None: ...


# --- state, monthly (EIA-861M) ----------------------------------------------------


def parse_workbook(path: Path) -> dict[str, list[Row]]:
    """State -> rows newest first, from the Monthly-States sheet."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Monthly-States"]
        out: dict[str, list[Row]] = {}
        for r in ws.iter_rows(min_row=4, values_only=True):
            if len(r) < 8 or not isinstance(r[0], int | float) or not isinstance(r[2], str):
                continue
            year, month, state, status, revenue, sales, customers = (
                int(r[0]), int(r[1]), r[2].strip().upper(), str(r[3] or ""), r[4], r[5], r[6],
            )  # fmt: skip
            if not all(isinstance(v, int | float) for v in (revenue, sales, customers)):
                continue
            if sales <= 0 or customers <= 0:
                continue
            out.setdefault(state, []).append(
                (year, month, float(revenue), float(sales), float(customers), status)
            )
    finally:
        wb.close()
    for rows in out.values():
        rows.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return out


def _months_back(year: int, month: int, n: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) - n
    return idx // 12, idx % 12 + 1


def series_from_rows(state: str, rows: list[Row]) -> PriceSeries | None:
    """Trailing twelve months against the twelve ending 24 months earlier.
    Needs both windows complete."""
    if not rows:
        return None
    by_month = {(r[0], r[1]): r for r in rows}
    latest = rows[0][:2]

    def window(end: tuple[int, int]) -> list[Row] | None:
        picked = []
        for back in range(12):
            key = _months_back(end[0], end[1], back)
            if key not in by_month:
                return None
            picked.append(by_month[key])
        return picked

    now = window(latest)
    then = window(_months_back(latest[0], latest[1], WINDOW_MONTHS))
    if not now or not then:
        return None
    rate_now = sum(r[2] for r in now) / sum(r[3] for r in now)  # k$ / MWh == $/kWh
    rate_then = sum(r[2] for r in then) / sum(r[3] for r in then)
    typical = sum(r[3] * 1000 / r[4] for r in now) / len(now)
    latest_row = rows[0]
    return PriceSeries(
        jurisdiction=state,
        rate_now=round(rate_now, 4),
        rate_then=round(rate_then, 4),
        trend_pct=round((rate_now - rate_then) / rate_then * 100, 1),
        typical_kwh_month=float(round(typical)),
        window_months=WINDOW_MONTHS,
        latest=(latest[0], latest[1]),
        source_url=EIA861M_PAGE,
        source_title=EIA861M_TITLE,
        data_status=latest_row[5] or "Preliminary",
        scope="state",
        as_of=f"{latest[0]}-{latest[1]:02d}",
        label=f"{state} statewide",
        latest_month_rate=round(latest_row[2] / latest_row[3], 4),
        currency="USD",
        granularity="monthly",
    )


async def _download(url: str, path: Path, timeout: float) -> bytes:
    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.content
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


def _fresh(path: Path) -> bool:
    return path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_S


class Eia861mPrices:
    def __init__(self, cache_dir: Path, *, url: str = EIA861M_XLSX, timeout: float = 60.0) -> None:
        self.path = cache_dir / "eia861m_sales_revenue.xlsx"
        self.url = url
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._rows: dict[str, list[Row]] | None = None
        self._loaded_at = 0.0

    async def _table(self) -> dict[str, list[Row]]:
        async with self._lock:
            fresh = _fresh(self.path)
            if self._rows is not None and (fresh or time.time() - self._loaded_at < MAX_AGE_S):
                return self._rows
            if not fresh:
                try:
                    data = await _download(self.url, self.path, self.timeout)
                    log_event("ground_snapshot", provider="eia861m", bytes=len(data))
                except httpx.HTTPError as exc:
                    if not self.path.exists():
                        raise RuntimeError(f"EIA-861M: {exc.__class__.__name__}") from exc
                    log_event("ground_stale", provider="eia861m", reason=exc.__class__.__name__)
            self._rows = await asyncio.to_thread(parse_workbook, self.path)
            self._loaded_at = time.time()
            return self._rows

    async def series(self, jurisdiction: str) -> PriceSeries | None:
        table = await self._table()
        return series_from_rows(jurisdiction.upper(), table.get(jurisdiction.upper(), []))


# --- utility, annual (EIA-861) ------------------------------------------------------


def parse_utility_workbook(path: Path) -> dict[tuple[str, str], UtilityRow]:
    """(utility number, state) -> residential revenue, sales, customers, name.
    Bundled service only: a delivery-only wire company's revenue is not the
    price its customers pay for power."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["States"]
        out: dict[tuple[str, str], list[float | str]] = {}
        for r in ws.iter_rows(min_row=4, values_only=True):
            if len(r) < 12 or not isinstance(r[1], int | float) or r[4] != "Bundled":
                continue
            revenue, sales, customers = r[9], r[10], r[11]
            if not all(isinstance(v, int | float) for v in (revenue, sales, customers)):
                continue
            key = (str(int(r[1])), str(r[6] or "").strip().upper())
            acc = out.setdefault(key, [0.0, 0.0, 0.0, str(r[2] or "")])
            acc[0] += float(revenue)
            acc[1] += float(sales)
            acc[2] += float(customers)
    finally:
        wb.close()
    return {
        k: (float(v[0]), float(v[1]), float(v[2]), str(v[3]))
        for k, v in out.items()
        if v[1] > 0 and v[2] > 0
    }


def parse_customers_workbook(path: Path) -> dict[Key, int]:
    """(utility number, state) -> residential customers, the larger of bundled
    and delivery service. Works on Sales_Ult_Cust (sheet States) and on
    Delivery_Companies, which has the same columns: a wires-only company in a
    competitive market (Oncor, say) appears only in the latter, and HIFLD has
    no count for it at all."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["States"] if "States" in wb.sheetnames else wb[wb.sheetnames[0]]
        acc: dict[tuple[str, str, str], float] = {}
        for r in ws.iter_rows(min_row=4, values_only=True):
            if (
                len(r) < 12
                or not isinstance(r[1], int | float)
                or not isinstance(r[11], int | float)
            ):
                continue
            key = (str(int(r[1])), str(r[6] or "").strip().upper(), str(r[4] or ""))
            acc[key] = acc.get(key, 0.0) + float(r[11])
    finally:
        wb.close()
    out: dict[Key, int] = {}
    for (uid, state, _service), n in acc.items():
        out[(uid, state)] = max(out.get((uid, state), 0), int(n))
    return {k: v for k, v in out.items() if v > 0}


def parse_ba_workbook(path: Path) -> dict[Key, str]:
    """(utility number, state) -> the balancing authority code the utility
    reports (column "BA Code"), from Sales_Ult_Cust or Delivery_Companies."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["States"] if "States" in wb.sheetnames else wb[wb.sheetnames[0]]
        out: dict[Key, str] = {}
        for r in ws.iter_rows(min_row=4, values_only=True):
            if len(r) < 9 or not isinstance(r[1], int | float) or not r[8]:
                continue
            key = (str(int(r[1])), str(r[6] or "").strip().upper())
            out.setdefault(key, str(r[8]).strip().upper())
    finally:
        wb.close()
    return out


def parse_territory_workbook(path: Path) -> tuple[dict[Key, set[str]], dict[Key, str]]:
    """(utility number, state) -> counties the utility reports serving, and the
    utility's name as the form spells it."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Counties_States"]
        out: dict[Key, set[str]] = {}
        names: dict[Key, str] = {}
        for r in ws.iter_rows(min_row=2, values_only=True):
            if len(r) < 6 or not isinstance(r[1], int | float) or not r[5]:
                continue
            key = (str(int(r[1])), str(r[4] or "").strip().upper())
            out.setdefault(key, set()).add(county_key(str(r[5])))
            names.setdefault(key, str(r[2] or ""))
    finally:
        wb.close()
    return out, names


def county_key(name: str) -> str:
    n = name.strip().upper()
    for suffix in (" COUNTY", " PARISH", " BOROUGH", " CENSUS AREA", " MUNICIPIO"):
        n = n.removesuffix(suffix)
    return n.replace(".", "").replace("'", "")


def utility_series_from_rows(
    eia_id: str,
    state: str,
    now: UtilityRow | None,
    then: UtilityRow | None,
    year_now: int,
    year_then: int,
) -> PriceSeries | None:
    if not now or not then:
        return None
    rate_now = now[0] / now[1]
    rate_then = then[0] / then[1]
    typical = now[1] * 1000 / now[2] / 12
    return PriceSeries(
        jurisdiction=state,
        rate_now=round(rate_now, 4),
        rate_then=round(rate_then, 4),
        trend_pct=round((rate_now - rate_then) / rate_then * 100, 1),
        typical_kwh_month=float(round(typical)),
        window_months=(year_now - year_then) * 12,
        latest=(year_now, 12),
        source_url=EIA861_PAGE,
        source_title=EIA861_TITLE,
        data_status="Final",
        scope="utility",
        as_of=f"{year_now}-12",
        label=now[3],
        eia_id=eia_id,
        currency="USD",
        granularity="annual",
    )


class Eia861UtilityPrices:
    """Latest annual file against the one two years earlier. The latest year is
    found by trying the current data year first."""

    def __init__(self, cache_dir: Path, *, timeout: float = 120.0) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._tables: dict[int, dict[tuple[str, str], UtilityRow]] = {}
        self._years: tuple[int, int] | None = None
        self._customers: dict[Key, int] | None = None
        self._territory: dict[Key, set[str]] | None = None
        self._names: dict[Key, str] = {}
        self._ba: dict[Key, str] = {}

    async def _workbook(self, year: int, member: str = "Sales_Ult_Cust") -> Path | None:
        path = self.cache_dir / f"eia861_{member.lower()}_{year}.xlsx"
        if path.exists():
            return path
        for url in (EIA861_ZIP.format(year=year), EIA861_ARCHIVE_ZIP.format(year=year)):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
                ) as client:
                    r = await client.get(url)
                    r.raise_for_status()
                    data = r.content
            except httpx.HTTPError:
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    # Keep every sheet this provider reads, so one download serves all.
                    found = None
                    for wanted in ("Sales_Ult_Cust", "Service_Territory", "Delivery_Companies"):
                        name = f"{wanted}_{year}.xlsx"
                        if name not in z.namelist():
                            continue
                        out = self.cache_dir / f"eia861_{wanted.lower()}_{year}.xlsx"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        tmp = out.with_suffix(".tmp")
                        tmp.write_bytes(z.read(name))
                        tmp.replace(out)
                        if wanted == member:
                            found = out
            except zipfile.BadZipFile:
                continue  # a redirect to an HTML page, not the archive
            if found is None:
                continue
            log_event("ground_snapshot", provider="eia861", year=year, bytes=len(data))
            return found
        return None

    async def _directory(self) -> tuple[dict[Key, int], dict[Key, set[str]]]:
        if self._customers is None or self._territory is None:
            years = await self._years_available()
            if years is None:
                raise RuntimeError("EIA-861: no annual file could be downloaded")
            sales = await self._workbook(years[0])
            territory = await self._workbook(years[0], "Service_Territory")
            if sales is None or territory is None:
                raise RuntimeError("EIA-861: directory sheets missing")
            customers = await asyncio.to_thread(parse_customers_workbook, sales)
            ba = await asyncio.to_thread(parse_ba_workbook, sales)
            delivery = await self._workbook(years[0], "Delivery_Companies")
            if delivery is not None:
                for key, n in (await asyncio.to_thread(parse_customers_workbook, delivery)).items():
                    customers[key] = max(customers.get(key, 0), n)
                for key, code in (await asyncio.to_thread(parse_ba_workbook, delivery)).items():
                    ba.setdefault(key, code)
            self._ba = ba
            self._customers = customers
            self._territory, self._names = await asyncio.to_thread(
                parse_territory_workbook, territory
            )
        return self._customers, self._territory

    async def customers(self, eia_id: str, state: str) -> int | None:
        async with self._lock:
            customers, _ = await self._directory()
        return customers.get((eia_id, state.upper()))

    async def ba_code(self, eia_id: str, state: str) -> str | None:
        async with self._lock:
            await self._directory()
        return self._ba.get((eia_id, state.upper()))

    async def in_county(self, state: str, county: str) -> list[dict[str, object]]:
        """Utilities that report serving this county, as HIFLD-shaped records,
        for when no retail polygon contains the point."""
        async with self._lock:
            customers, territory = await self._directory()
        want = county_key(county)
        out = []
        for (uid, st), counties in territory.items():
            if st != state.upper() or want not in counties:
                continue
            out.append(
                {
                    "NAME": self._names.get((uid, st), uid).upper(),
                    "TYPE": "REPORTED IN EIA-861",
                    "CUSTOMERS": customers.get((uid, st), -1),
                    "ID": uid,
                }
            )
        return out

    async def serves(self, eia_id: str, state: str, county: str) -> bool | None:
        """True/False when the utility reports its counties; None when it is
        not in the territory table at all."""
        async with self._lock:
            _, territory = await self._directory()
        counties = territory.get((eia_id, state.upper()))
        if counties is None:
            return None
        return county_key(county) in counties

    async def _years_available(self) -> tuple[int, int] | None:
        if self._years:
            return self._years
        this_year = datetime.now(UTC).year
        for latest in (this_year - 1, this_year - 2):
            now_path = await self._workbook(latest)
            if now_path is None:
                continue
            then_path = await self._workbook(latest - 2)
            if then_path is None:
                continue
            self._years = (latest, latest - 2)
            return self._years
        return None

    async def _table(self, year: int) -> dict[tuple[str, str], UtilityRow]:
        if year not in self._tables:
            path = await self._workbook(year)
            if path is None:
                raise RuntimeError(f"EIA-861 {year}: not available")
            self._tables[year] = await asyncio.to_thread(parse_utility_workbook, path)
        return self._tables[year]

    async def for_utility(self, eia_id: str, state: str) -> PriceSeries | None:
        async with self._lock:
            years = await self._years_available()
            if years is None:
                raise RuntimeError("EIA-861: no annual file could be downloaded")
            year_now, year_then = years
            now = (await self._table(year_now)).get((eia_id, state.upper()))
            then = (await self._table(year_then)).get((eia_id, state.upper()))
        return utility_series_from_rows(eia_id, state.upper(), now, then, year_now, year_then)


# --- fakes --------------------------------------------------------------------------


class FakePrices:
    def __init__(self, series: PriceSeries | None = None, *, fail: bool = False) -> None:
        self._series = series
        self.fail = fail

    async def series(self, jurisdiction: str) -> PriceSeries | None:
        if self.fail:
            raise RuntimeError("fake")
        return self._series


class FakeUtilityPrices:
    def __init__(
        self,
        series: PriceSeries | None = None,
        *,
        fail: bool = False,
        customers: dict[str, int] | None = None,
        counties: dict[str, set[str]] | None = None,
        names: dict[str, str] | None = None,
        ba_codes: dict[str, str] | None = None,
    ) -> None:
        self._series = series
        self._ba = ba_codes or {}
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self._customers = customers or {}
        self._counties = counties
        self._names = names or {}

    async def customers(self, eia_id: str, state: str) -> int | None:
        return self._customers.get(eia_id)

    async def ba_code(self, eia_id: str, state: str) -> str | None:
        return self._ba.get(eia_id)

    async def serves(self, eia_id: str, state: str, county: str) -> bool | None:
        if self._counties is None or eia_id not in self._counties:
            return None
        return county.upper() in self._counties[eia_id]

    async def in_county(self, state: str, county: str) -> list[dict[str, object]]:
        if not self._counties:
            return []
        return [
            {
                "NAME": self._names.get(uid, uid).upper(),
                "TYPE": "REPORTED IN EIA-861",
                "CUSTOMERS": self._customers.get(uid, -1),
                "ID": uid,
            }
            for uid, counties in self._counties.items()
            if county.upper() in counties
        ]

    async def for_utility(self, eia_id: str, state: str) -> PriceSeries | None:
        self.calls.append((eia_id, state))
        if self.fail:
            raise RuntimeError("fake")
        return self._series
