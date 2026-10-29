"""Eurostat nrg_pc_204 (plan 0.4): periods from the cached full series, figures,
labels and quote from the live two-period response. No network: the full series
and the compact response are saved fixtures, served through httpx.MockTransport."""

import json
from pathlib import Path

import httpx
import pytest

from app.ground.eurostat import (
    EUROSTAT_TITLE,
    EurostatPrices,
    compact_url,
    labels,
    latest_pair,
    parse_jsonstat,
    same_semester_back,
    semiannual_series,
    series_url,
    value_quote,
)
from app.scenario.constants import Constant
from tests import fakes_ie

FIXTURES = Path(__file__).parent / "fixtures"
SERIES_TEXT = (FIXTURES / "eurostat_nrg_pc_204_ie.json").read_text(encoding="utf-8")
COMPACT_TEXT = (FIXTURES / "eurostat_compact_ie.json").read_text(encoding="utf-8")
SERIES = json.loads(SERIES_TEXT)
COMPACT = json.loads(COMPACT_TEXT)

PLAN_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_204?geo=IE"
    "&nrg_cons=KWH2500-4999&tax=I_TAX&currency=EUR&unit=KWH&time=2024-S1&time=2026-S1"
)
PLAN_CLAIM = (
    "Eurostat nrg_pc_204, Ireland, Consumption from 2 500 kWh to 4 999 kWh - band DC, All taxes "
    "and levies included: EUR 0.3871 per kWh in 2026-S1 and EUR 0.2590 per kWh in 2024-S1."
)

KWH = Constant(
    id="ie_home_kwh_per_year",
    value=4200.0,
    unit="kWh of electricity per household per year",
    as_of="2017",
    source_title=fakes_ie.CRU_KWH_TITLE,
    source_url=fakes_ie.CRU_KWH_URL,
    quote=fakes_ie.CRU_KWH_QUOTE,
    checked="2026-10-29",
    claim=fakes_ie.CRU_KWH_CLAIM,
)


# --- pure parts -------------------------------------------------------------------


def test_parse_reads_every_valued_semester() -> None:
    s = parse_jsonstat(SERIES)
    assert s["2026-S1"] == (0.3871, None)
    assert s["2024-S1"] == (0.259, None)
    assert "1985-S1" not in s  # listed under positions-with-no-data, no value
    assert len(s) == 77 - 39


def test_parse_rejects_a_second_multi_category_dimension() -> None:
    body = json.loads(COMPACT_TEXT)
    body["size"][body["id"].index("geo")] = 2
    with pytest.raises(ValueError):
        parse_jsonstat(body)


def test_same_semester_back() -> None:
    assert same_semester_back("2026-S1") == "2024-S1"
    assert same_semester_back("2025-S2") == "2023-S2"
    with pytest.raises(ValueError):
        same_semester_back("2026-01")


def test_latest_pair_is_by_label_and_needs_both() -> None:
    assert latest_pair(parse_jsonstat(SERIES)) == ("2024-S1", "2026-S1")
    s = parse_jsonstat(SERIES)
    del s["2024-S1"]
    assert latest_pair(s) is None


def test_urls() -> None:
    assert compact_url("2024-S1", "2026-S1") == PLAN_URL
    assert series_url("IE") == PLAN_URL.split("&time=")[0]


def test_labels_are_the_response_words() -> None:
    words = labels(COMPACT)
    assert words["geo"] == "Ireland"
    assert words["nrg_cons"] == "Consumption from 2 500 kWh to 4 999 kWh - band DC"
    assert words["tax"] == "All taxes and levies included"
    assert "time" not in words


def test_value_quote_is_raw_text() -> None:
    q = value_quote(COMPACT_TEXT)
    assert q == '"value":{"0":0.2590,"1":0.3871}'
    assert q in COMPACT_TEXT
    assert q == fakes_ie.EUROSTAT_QUOTE
    assert value_quote("no value here") == ""


def test_series_from_the_compact_response_matches_the_plan() -> None:
    p = semiannual_series(
        SERIES,
        COMPACT,
        COMPACT_TEXT,
        typical_kwh_month=350.0,
        kwh_source=KWH,
    )
    assert p is not None
    assert p.claim_text == PLAN_CLAIM == fakes_ie.EUROSTAT_CLAIM
    assert p.quote == fakes_ie.EUROSTAT_QUOTE
    assert p.source_url == PLAN_URL
    assert p.source_title == EUROSTAT_TITLE
    assert (p.rate_now, p.rate_then, p.trend_pct) == (0.3871, 0.259, 49.5)
    assert (p.period_now, p.period_then) == ("2026-S1", "2024-S1")
    assert p.latest == (2026, 6) and p.as_of == "2026-06"
    assert p.window_months == 24 and p.granularity == "semiannual"
    assert p.scope == "country" and p.jurisdiction == "IE" and p.label == "Ireland"
    assert p.currency == "EUR" and p.latest_month_rate is None
    assert p.data_status == "Final"
    assert p.typical_kwh_month == 350.0
    assert p.kwh_claim_text == fakes_ie.CRU_KWH_CLAIM
    assert p.kwh_source_url == "https://www.cru.ie/publications/25651/"
    assert p.kwh_source_title == fakes_ie.CRU_KWH_TITLE
    assert p.kwh_quote == fakes_ie.CRU_KWH_QUOTE
    # The fake the brief tests use is this same series.
    assert p == fakes_ie.PRICE_IE


def test_compact_figures_win_over_a_revised_cache() -> None:
    """A synthetic revision: the compact response says 0.3901 where the cached
    series says 0.3871. Claim, figures and quote all follow the compact one."""
    text = COMPACT_TEXT.replace('"1":0.3871', '"1":0.3901')
    p = semiannual_series(SERIES, json.loads(text), text)
    assert p is not None
    assert p.rate_now == 0.3901
    assert "EUR 0.3901 per kWh in 2026-S1" in p.claim_text
    assert p.quote == '"value":{"0":0.2590,"1":0.3901}'
    assert p.trend_pct == round((0.3901 - 0.259) / 0.259 * 100, 1)


def test_compact_labels_win_over_the_cache() -> None:
    body = json.loads(COMPACT_TEXT)
    body["dimension"]["tax"]["category"]["label"]["I_TAX"] = "All taxes and levies (relabelled)"
    p = semiannual_series(SERIES, body, COMPACT_TEXT)
    assert p is not None and "All taxes and levies (relabelled):" in p.claim_text


def test_without_compact_figures_come_from_the_cache_and_quote_is_empty() -> None:
    p = semiannual_series(SERIES, None, "")
    assert p is not None
    assert p.quote == ""
    assert p.claim_text == PLAN_CLAIM
    assert p.source_url == PLAN_URL
    # A compact body missing a period is no better than none.
    body = json.loads(COMPACT_TEXT)
    del body["value"]["0"]
    p2 = semiannual_series(SERIES, body, COMPACT_TEXT)
    assert p2 is not None and p2.quote == "" and p2.rate_then == 0.259


def test_status_flags() -> None:
    body = json.loads(COMPACT_TEXT)
    body["status"] = {"1": "p"}
    assert semiannual_series(SERIES, body, COMPACT_TEXT).data_status == "Provisional"
    body["status"] = {"0": "e"}
    assert semiannual_series(SERIES, body, COMPACT_TEXT).data_status == "Estimated"


def test_missing_constant_leaves_typical_none() -> None:
    p = semiannual_series(SERIES, COMPACT, COMPACT_TEXT)
    assert p is not None
    assert p.typical_kwh_month is None
    assert p.kwh_claim_text is None and p.kwh_source_url is None and p.kwh_quote is None


def test_then_period_missing_gives_none() -> None:
    body = json.loads(SERIES_TEXT)
    del body["value"]["72"]  # 2024-S1
    assert semiannual_series(body, COMPACT, COMPACT_TEXT) is None


# --- the provider -------------------------------------------------------------------


def _transport(
    calls: list[str], *, series: int = 200, compact: int = 200, compact_text: str = COMPACT_TEXT
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        assert request.headers["User-Agent"].startswith("WhosOnMyGrid/")
        if "time=" in url:
            return httpx.Response(compact, text=compact_text if compact == 200 else "")
        return httpx.Response(series, text=SERIES_TEXT if series == 200 else "")

    return httpx.MockTransport(handler)


async def test_provider_fetches_caches_and_cites(tmp_path: Path) -> None:
    calls: list[str] = []
    prov = EurostatPrices(
        tmp_path, typical_kwh_month=350.0, kwh_source=KWH, transport=_transport(calls)
    )
    p = await prov.series("IE")
    assert p is not None and p.claim_text == PLAN_CLAIM and p.quote == fakes_ie.EUROSTAT_QUOTE
    assert (tmp_path / "eurostat_nrg_pc_204_ie.json").read_text(encoding="utf-8") == SERIES_TEXT
    assert calls == [series_url("IE"), PLAN_URL]
    # A second brief reuses the series and the compact response.
    await prov.series("ie")
    assert len(calls) == 2


async def test_provider_uses_a_fresh_disk_cache(tmp_path: Path) -> None:
    (tmp_path / "eurostat_nrg_pc_204_ie.json").write_text(SERIES_TEXT, encoding="utf-8")
    calls: list[str] = []
    p = await EurostatPrices(tmp_path, transport=_transport(calls)).series("IE")
    assert p is not None
    assert calls == [PLAN_URL]


async def test_provider_compact_failure_keeps_cached_figures(tmp_path: Path) -> None:
    (tmp_path / "eurostat_nrg_pc_204_ie.json").write_text(SERIES_TEXT, encoding="utf-8")
    p = await EurostatPrices(tmp_path, transport=_transport([], compact=503)).series("IE")
    assert p is not None
    assert p.quote == ""
    assert (p.rate_now, p.rate_then) == (0.3871, 0.259)
    assert p.source_url == PLAN_URL


async def test_provider_without_series_raises(tmp_path: Path) -> None:
    prov = EurostatPrices(tmp_path, transport=_transport([], series=503))
    with pytest.raises(RuntimeError) as exc:
        await prov.series("IE")
    assert str(exc.value) == "Eurostat: HTTPStatusError"  # no URL in the message


async def test_failed_refresh_retries_after_a_backoff_not_a_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale file and one Eurostat failure: the stale body is served, but the
    next try comes after RETRY_S, not after another MAX_AGE_S."""
    import os
    import time

    from app.ground import eurostat as es

    path = tmp_path / "eurostat_nrg_pc_204_ie.json"
    path.write_text(SERIES_TEXT, encoding="utf-8")
    old = time.time() - es.MAX_AGE_S - 60
    os.utime(path, (old, old))
    status = {"series": 503}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "time=" in url:
            return httpx.Response(200, text=COMPACT_TEXT)
        code = status["series"]
        return httpx.Response(code, text=SERIES_TEXT if code == 200 else "")

    prov = EurostatPrices(tmp_path, transport=httpx.MockTransport(handler))
    assert await prov.series("IE") is not None  # stale, served
    series_calls = lambda: [c for c in calls if "time=" not in c]  # noqa: E731
    assert len(series_calls()) == 1
    status["series"] = 200
    assert await prov.series("IE") is not None  # inside the backoff: no new try
    assert len(series_calls()) == 1
    now = time.time()
    monkeypatch.setattr(es.time, "time", lambda: now + es.RETRY_S + 1)
    assert await prov.series("IE") is not None  # past the backoff: refetched
    assert len(series_calls()) == 2
    assert path.stat().st_mtime > old + es.MAX_AGE_S  # the file was rewritten
    assert await prov.series("IE") is not None  # fresh now: no further fetch
    assert len(series_calls()) == 2


async def test_provider_answers_only_its_country(tmp_path: Path) -> None:
    calls: list[str] = []
    assert await EurostatPrices(tmp_path, transport=_transport(calls)).series("VA") is None
    assert calls == []


def test_provider_names_its_failure() -> None:
    assert EurostatPrices.name == "eurostat"
    assert "Eurostat" in EurostatPrices.failure_note
