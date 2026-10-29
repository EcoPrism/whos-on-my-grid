"""Household electricity prices outside the US: Eurostat nrg_pc_204, the
bi-annual price for household consumers, band DC (2 500 to 4 999 kWh a year),
all taxes and levies included, in euro per kWh.

The comparison is the latest semester against the same semester two years
earlier (2026-S1 against 2024-S1), so a seasonal half never meets the other
half. The full series is cached on disk for a month and only chooses the two
periods; the figures, the dimension labels in the claim and the quote all come
from one live two-period request (`compact_url`), which is also the page the
claim cites. If that request fails, the figures come from the cached series and
the quote is empty (the claim still cites the URL).

Free and keyless; JSON-stat 2.0."""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from app.ground.types import PriceSeries
from app.telemetry import log_event

if TYPE_CHECKING:
    from app.scenario.constants import Constant

USER_AGENT = "WhosOnMyGrid/0.1 (+https://github.com/EcoPrism/whos-on-my-grid)"
EUROSTAT_API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_204"
EUROSTAT_TITLE = (
    "Eurostat, Electricity prices for household consumers - bi-annual data (nrg_pc_204)"
)
DATASET = "nrg_pc_204"
CONSUMPTION_BAND = "KWH2500-4999"
TAX = "I_TAX"
CURRENCY = "EUR"
MAX_AGE_S = 30 * 86_400
RETRY_S = 3_600  # after a failed refresh, serve the stale file and try again in an hour
COMPACT_MAX_AGE_S = 3_600  # one live two-period response serves briefs for an hour
YEARS_BACK = 2

_PERIOD = re.compile(r"^(\d{4})-S([12])$")
_VALUE = re.compile(r'"value"\s*:\s*\{[^{}]*\}')
_STATUS_WORDS = {"p": "Provisional", "e": "Estimated"}


def _query(country: str) -> str:
    return (
        f"geo={country.upper()}&nrg_cons={CONSUMPTION_BAND}&tax={TAX}&currency={CURRENCY}&unit=KWH"
    )


def series_url(country: str = "IE") -> str:
    """Every semester for one country: what the disk cache holds."""
    return f"{EUROSTAT_API}?{_query(country)}"


def compact_url(then: str, now: str, *, country: str = "IE") -> str:
    """The two-period response the claim cites (about 3 KB of JSON)."""
    return f"{EUROSTAT_API}?{_query(country)}&time={then}&time={now}"


def same_semester_back(period: str, years: int = YEARS_BACK) -> str:
    """'2026-S1' -> '2024-S1'."""
    m = _PERIOD.match(period)
    if not m:
        raise ValueError(f"not a semester label: {period!r}")
    return f"{int(m.group(1)) - years}-S{m.group(2)}"


def _period_end(period: str) -> tuple[int, int]:
    """'2026-S1' -> (2026, 6); '2026-S2' -> (2026, 12)."""
    m = _PERIOD.match(period)
    if not m:
        raise ValueError(f"not a semester label: {period!r}")
    return int(m.group(1)), 6 if m.group(2) == "1" else 12


def _cell(container: Any, i: int) -> Any:
    """A JSON-stat value or status, stored as a sparse dict or a dense list."""
    if isinstance(container, dict):
        return container.get(str(i))
    if isinstance(container, list):
        return container[i] if i < len(container) else None
    if isinstance(container, str):  # one status for every cell
        return container
    return None


def parse_jsonstat(body: dict[str, Any]) -> dict[str, tuple[float, str | None]]:
    """Period label -> (value, status flag) for a response whose only dimension
    with more than one category is `time`. Periods without a value are left out."""
    ids: list[str] = body["id"]
    sizes: list[int] = body["size"]
    if "time" not in ids:
        raise ValueError("JSON-stat body has no time dimension")
    for dim, n in zip(ids, sizes, strict=True):
        if dim != "time" and n != 1:
            raise ValueError(f"dimension {dim} has {n} categories; one expected")
    index: dict[str, int] = body["dimension"]["time"]["category"]["index"]
    values = body.get("value", {})
    status = body.get("status")
    out: dict[str, tuple[float, str | None]] = {}
    for label, i in index.items():
        v = _cell(values, i)
        if isinstance(v, bool) or not isinstance(v, int | float):
            continue
        s = _cell(status, i)
        out[label] = (float(v), s if isinstance(s, str) and s.strip() else None)
    return out


def labels(body: dict[str, Any]) -> dict[str, str]:
    """The response's own words for its single-category dimensions, e.g.
    {"geo": "Ireland", "nrg_cons": "Consumption from 2 500 kWh to 4 999 kWh - band DC",
    "tax": "All taxes and levies included", ...}."""
    out: dict[str, str] = {}
    for dim, spec in (body.get("dimension") or {}).items():
        cat = (spec or {}).get("category") or {}
        names = cat.get("label") or {}
        index = cat.get("index") or {}
        if dim == "time" or len(index) != 1:
            continue
        code = next(iter(index))
        if isinstance(names.get(code), str):
            out[dim] = names[code]
    return out


def value_quote(text: str) -> str:
    """The raw `"value":{...}` substring of a response's text, byte for byte:
    the quote the verifier finds on the cited page. "" when absent."""
    m = _VALUE.search(text or "")
    return m.group(0) if m else ""


def _status_word(*flags: str | None) -> str:
    for flag in ("p", "e"):
        if any(f and flag in f.lower() for f in flags):
            return _STATUS_WORDS[flag]
    return "Final"


def latest_pair(series: dict[str, tuple[float, str | None]]) -> tuple[str, str] | None:
    """(then, now): the newest semester with a value and the same semester two
    years before it, chosen by label. None when either has no value."""
    periods = sorted((p for p in series if _PERIOD.match(p)), key=_period_end)
    if not periods:
        return None
    now = periods[-1]
    then = same_semester_back(now)
    return (then, now) if then in series else None


def semiannual_series(
    series_body: dict[str, Any],
    compact_body: dict[str, Any] | None = None,
    compact_text: str = "",
    *,
    country: str = "IE",
    label: str = "Ireland",
    typical_kwh_month: float | None = None,
    kwh_source: "Constant | None" = None,
) -> PriceSeries | None:
    """The PriceSeries for the newest semester against the same one two years
    back. Periods come from the full series. Rates, labels and the quote come
    from the compact response when it holds both periods; otherwise rates and
    labels come from the full series and the quote is ""."""
    full = parse_jsonstat(series_body)
    pair = latest_pair(full)
    if pair is None:
        return None
    then, now = pair
    source, quote, words = full, "", labels(series_body)
    if compact_body is not None:
        try:
            compact = parse_jsonstat(compact_body)
        except (KeyError, TypeError, ValueError):
            compact = {}
        if then in compact and now in compact:
            source = compact
            quote = value_quote(compact_text)
            words = labels(compact_body) or words
    rate_now, status_now = source[now]
    rate_then, status_then = source[then]
    if rate_then <= 0:
        return None
    place = words.get("geo", label)
    band = words.get("nrg_cons", "Consumption from 2 500 kWh to 4 999 kWh - band DC")
    tax = words.get("tax", "All taxes and levies included")
    claim = (
        f"Eurostat {DATASET}, {place}, {band}, {tax}: {CURRENCY} {rate_now:.4f} per kWh in {now} "
        f"and {CURRENCY} {rate_then:.4f} per kWh in {then}."
    )
    latest = _period_end(now)
    return PriceSeries(
        jurisdiction=country.upper(),
        rate_now=round(rate_now, 4),
        rate_then=round(rate_then, 4),
        trend_pct=round((rate_now - rate_then) / rate_then * 100, 1),
        typical_kwh_month=typical_kwh_month,
        window_months=YEARS_BACK * 12,
        latest=latest,
        source_url=compact_url(then, now, country=country),
        source_title=EUROSTAT_TITLE,
        data_status=_status_word(status_now, status_then),
        scope="country",
        as_of=f"{latest[0]}-{latest[1]:02d}",
        label=label,
        latest_month_rate=None,
        currency=CURRENCY,
        granularity="semiannual",
        claim_text=claim,
        quote=quote,
        period_now=now,
        period_then=then,
        kwh_claim_text=(kwh_source.claim or None) if kwh_source else None,
        kwh_source_url=kwh_source.source_url if kwh_source else None,
        kwh_source_title=kwh_source.source_title if kwh_source else None,
        kwh_quote=kwh_source.quote if kwh_source else None,
    )


class EurostatPrices:
    """A PriceProvider for one country. `series(jurisdiction)` answers only for
    that country (Ground.jurisdiction gives the country outside the US)."""

    name = "eurostat"
    failure_note = (
        "Eurostat's household electricity price series could not be read; "
        "the national bill change is not known."
    )

    def __init__(
        self,
        cache_dir: Path,
        *,
        country: str = "IE",
        label: str = "Ireland",
        typical_kwh_month: float | None = None,
        kwh_source: "Constant | None" = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.country = country.upper()
        self.label = label
        self.typical_kwh_month = typical_kwh_month
        self.kwh_source = kwh_source
        self.timeout = timeout
        self.transport = transport
        self.path = cache_dir / f"eurostat_{DATASET}_{self.country.lower()}.json"
        self._lock = asyncio.Lock()
        self._body: dict[str, Any] | None = None
        # The file's mtime when it was read: the age of the last successful fetch,
        # not of the read. A stale body after a failed refresh is served only
        # until _retry_at, never for another MAX_AGE_S.
        self._body_mtime = 0.0
        self._retry_at = 0.0
        self._compact: dict[str, tuple[float, str]] = {}  # url -> (fetched_at, text)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            transport=self.transport,
        )

    async def _get(self, url: str) -> str:
        async with self._client() as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text

    def _mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    async def _series_body(self) -> dict[str, Any]:
        async with self._lock:
            now = time.time()
            mtime = self._mtime()
            fresh = mtime is not None and now - mtime < MAX_AGE_S
            # The file in memory: fresh, or stale and still backing off.
            in_memory = self._body is not None and mtime == self._body_mtime
            if in_memory and (fresh or now < self._retry_at):
                return self._body
            if not fresh and (self._body is None or now >= self._retry_at):
                try:
                    text = await self._get(series_url(self.country))
                    json.loads(text)  # never cache a body that does not parse
                except (httpx.HTTPError, ValueError) as exc:
                    if mtime is None:
                        raise RuntimeError(f"Eurostat: {exc.__class__.__name__}") from exc
                    log_event("ground_stale", provider="eurostat", reason=exc.__class__.__name__)
                    self._retry_at = now + RETRY_S
                else:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text(text, encoding="utf-8")
                    tmp.replace(self.path)
                    log_event("ground_snapshot", provider="eurostat", bytes=len(text))
            self._body = json.loads(self.path.read_text(encoding="utf-8"))
            self._body_mtime = self._mtime() or 0.0
            return self._body

    async def _compact_text(self, url: str) -> str | None:
        hit = self._compact.get(url)
        if hit and time.time() - hit[0] < COMPACT_MAX_AGE_S:
            return hit[1]
        try:
            text = await self._get(url)
        except httpx.HTTPError as exc:
            log_event("ground_failed", provider="eurostat-compact", reason=exc.__class__.__name__)
            return None
        self._compact[url] = (time.time(), text)
        return text

    async def series(self, jurisdiction: str) -> PriceSeries | None:
        if jurisdiction.upper() != self.country:
            return None
        body = await self._series_body()
        pair = latest_pair(parse_jsonstat(body))
        if pair is None:
            return None
        text = await self._compact_text(compact_url(*pair, country=self.country))
        compact: dict[str, Any] | None = None
        if text is not None:
            try:
                compact = json.loads(text)
            except ValueError:
                compact = None
        return semiannual_series(
            body,
            compact,
            text or "",
            country=self.country,
            label=self.label,
            typical_kwh_month=self.typical_kwh_month,
            kwh_source=self.kwh_source,
        )
