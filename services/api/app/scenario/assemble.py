"""Scenario JSON (schema/scenario.schema.json) from the inputs, the ZIP's
ground truth and the cited constants. The baseline is the engine's measured
data, as in a brief; every strip line is `modelled`, shows its working, and
cites the constants it rests on plus the ground source it leans on. Each
constant also becomes one engine claim the verifier checks against its page,
so the arithmetic is checkable without a model drafting anything."""

from typing import Any
from urllib.parse import urlparse

from app.brief.assemble import ENGINE_CLAIM_FACILITIES, _engine_claim, _facility, _facility_claim
from app.card.spec import fmt_range, scenario_disclosure_line
from app.geocode import GeocodeResult
from app.ground.census import Households
from app.ground.facilities import haversine_km
from app.ground.types import GroundTruth
from app.scenario import model
from app.scenario.constants import Constant, Constants
from app.scenario.inputs import ScenarioInputs

DISCLOSURE = "Hypothetical. Modelled, not measured."
SECTION = "scenario"
UTILITY_SOURCE_TITLE = "Electric Retail Service Territories (HIFLD, via EIA Atlas)"
MAX_LINES = 7
CARD_LINES = 4


def _sources(constants: tuple[Constant, ...], now_iso: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for c in constants:
        if c.source_url in seen:
            continue
        seen.add(c.source_url)
        out.append(c.source(now_iso))
    return out


def _line(
    text: str,
    topic: str,
    confidence: float,
    constants: tuple[Constant, ...],
    now_iso: str,
    basis: list[str],
    ground: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources = _sources(constants, now_iso)
    urls = {s["url"] for s in sources}
    for g in ground or []:
        if g["url"] not in urls:
            urls.add(g["url"])
            sources.append(g)
    return {
        "text": text,
        "topic": topic,
        "status": "modelled",
        "confidence": max(0.0, min(1.0, confidence)),
        "sources": sources,
        "basis": "; ".join(b for b in basis if b) + ".",
    }


def _constant_claim_text(c: Constant) -> str:
    """Only what the cited page shows: the figure and its unit. The arithmetic
    on top of it is the engine's and lives in the line's basis."""
    when = f" ({c.as_of})" if c.as_of else ""
    return f"{c.source_title} gives {model.fmt(c.value)} {c.unit}{when}."


def _f(r: model.Result) -> float:
    """A scalar result's value."""
    assert isinstance(r.value, int | float)
    return float(r.value)


def _pair(r: model.Result) -> tuple[float, float]:
    assert isinstance(r.value, tuple)
    return r.value


def _count_words(n: int) -> str:
    return f"{n} data center{'s' if n != 1 else ''}"


def assemble_scenario(
    inputs: ScenarioInputs,
    geo: GeocodeResult,
    truth: GroundTruth | None,
    households: Households | None,
    c: Constants,
    *,
    scenario_id: str,
    now_iso: str,
    public_base_url: str = "",
    verified: bool = True,
) -> dict[str, Any]:
    truth = truth or GroundTruth()
    mw = inputs.mw
    campus = inputs.pin or (geo.lat, geo.lon)
    claims: list[dict[str, Any]] = []
    used: list[Constant] = []

    def use(*results: model.Result | model.BillOutcome | None) -> tuple[Constant, ...]:
        out: list[Constant] = []
        for r in results:
            if r is None:
                continue
            for k in r.constants:
                out.append(k)
                if k not in used:
                    used.append(k)
        return tuple(out)

    # --- baseline: the engine's measured ground truth, as in a brief ---------
    engine = truth.facilities or []
    facilities = [_facility(f, None) for f in engine]
    for f in engine[:ENGINE_CLAIM_FACILITIES]:
        if f.name:
            claims.append(
                _engine_claim(
                    SECTION, _facility_claim(f), f.source_url, f.source_title, f.name, 0, now_iso
                )
            )
    u = truth.utility
    utility_source = (
        {
            "title": UTILITY_SOURCE_TITLE,
            "url": u.source_url,
            "retrieved_at": now_iso,
            "quote": u.raw_name,
        }  # fmt: skip
        if u is not None
        else None
    )
    if u is not None:
        claims.append(
            _engine_claim(
                SECTION,
                f"The electric retail service territory at this ZIP's centre is {u.raw_name} "
                f"({u.kind.lower()}) in the HIFLD / EIA service-territory map.",
                u.source_url,
                UTILITY_SOURCE_TITLE,
                u.raw_name,
                0,
                now_iso,
            )
        )
    p = truth.best_price
    price: dict[str, Any] | None = None
    if p is not None:
        price = {
            "currency": "USD",
            "rate_now": p.rate_now,
            "rate_then": p.rate_then,
            "trend_pct": p.trend_pct,
            "window_months": p.window_months,
            "typical_household_kwh_month": p.typical_kwh_month,
            "attribution": None,
        }
        if p.as_of:
            price["as_of"] = p.as_of
    t = truth.tariff
    tariff_source = (
        {"title": t.title, "url": t.url, "retrieved_at": now_iso} if t is not None else None
    )
    hh_source = (
        {
            "title": households.source_title,
            "url": households.source_url,
            "retrieved_at": now_iso,
            **({"quote": households.quote} if households.quote else {}),
        }
        if households is not None
        else None
    )
    place_words = f"ZIP {inputs.zip}"

    # --- impact: the engine's arithmetic ---------------------------------------
    gwh = model.annual_gwh(mw, c)
    homes = model.homes_equivalent(_f(gwh), c) if gwh else None
    share = model.share_of_utility_homes(_f(homes), u) if homes else None
    water = model.water_gal_per_day(mw, inputs.cooling, c)
    water_homes = model.water_homes_equivalent(_f(water), c) if water else None
    acres = model.land_acres(mw, c)
    fields = model.football_fields(_f(acres), c) if acres else None
    bill = model.bill_outcome(t, u, mw, c)
    taxes = model.taxes_usd_per_year(mw, c)
    jobs = model.jobs(mw, c)
    months = model.construction_months(c)
    distance_km = round(haversine_km(campus[0], campus[1], geo.lat, geo.lon), 2)
    noise = model.noise_at(distance_km, where="the centre of the ZIP")

    impact: dict[str, Any] = {
        "power": {
            "gwh_per_year": gwh.value,
            "homes_equivalent": homes.value if homes else None,
            "share_of_utility_homes": share.value if share else None,
            "basis": "; ".join(r.basis for r in (gwh, homes, share) if r) + ".",
        }
        if gwh
        else None,
        "water": {
            "gal_per_day": water.value,
            "homes_equivalent": water_homes.value if water_homes else None,
            "basis": "; ".join(r.basis for r in (water, water_homes) if r) + ".",
        }
        if water
        else None,
        "land": {
            "acres": acres.value,
            "football_fields": fields.value if fields else None,
            "basis": "; ".join(r.basis for r in (acres, fields) if r) + ".",
        }
        if acres
        else None,
        "bill": {
            "kind": bill.kind,
            "range_usd_per_month": list(bill.range_usd_per_month)
            if bill.range_usd_per_month
            else None,
            "basis": bill.basis,
        },
        "taxes": {"range_usd_per_year": list(_pair(taxes)), "basis": taxes.basis + "."}
        if taxes
        else None,
        "jobs": {"permanent": jobs.value, "basis": jobs.basis + "."} if jobs else None,
        "noise": {"distance_km": distance_km, "db_at_pin": None, "basis": noise.basis},
        "timeline": {"construction_months": list(_pair(months)), "basis": months.basis + "."}
        if months
        else None,
    }

    # --- the strip: plain sentences, every one modelled ------------------------
    lines: list[dict[str, Any]] = []
    count = len(engine) if truth.facilities is not None else None
    if gwh and homes:
        text = (
            f"A {mw:,} MW campus would use about {_f(gwh):,.0f} GWh of electricity "
            f"a year, as much as about {_f(homes):,.0f} homes"
        )
        if share and _f(share) >= 1:
            text += f", more than all {u.customers:,} of {u.name}'s customers."
        else:
            text += f", or {_f(share) * 100:.0f}% of {u.name}'s customers." if share else "."
        ground = [utility_source] if share and utility_source else []
        if households is not None:
            text += f" {place_words} has {households.count:,} households."
            ground.append(hh_source)
        if count is not None:
            text += (
                f" {_count_words(count)} {'is' if count == 1 else 'are'} already listed "
                "within five miles."
                if count
                else " No data center is listed within five miles today."
            )
            if engine:
                ground.append(
                    {
                        "title": engine[0].source_title,
                        "url": engine[0].source_url,
                        "retrieved_at": now_iso,
                        "quote": engine[0].name,
                    }
                )
        lines.append(
            _line(
                text,
                "grid",
                min(gwh.confidence, homes.confidence),
                use(gwh, homes, share),
                now_iso,
                [gwh.basis, homes.basis, share.basis if share else ""],
                ground,
            )
        )

    if bill.kind == "shielded":
        bill_text = (
            f"Your bill: {t.name or 'a large-load tariff'} is in force for this utility, and its "
            "stated purpose is to keep the cost of serving a campus like this off household bills."
        )
    elif bill.range_usd_per_month:
        lo, hi = bill.range_usd_per_month
        bill_text = (
            f"If PJM's capacity price for a campus this size were shared out like other costs, "
            f"a typical home could pay about {fmt_range(lo, hi)} more a month."
            + (" A large-load rule covers part of that." if bill.kind == "partial" else "")
        )
    else:
        bill_text = (
            "What a campus this size would do to your bill cannot be modelled here: "
            + bill.basis[0].lower()
            + bill.basis[1:]
        )
    lines.append(
        _line(
            bill_text,
            "bill",
            bill.confidence,
            use(bill),
            now_iso,
            [bill.basis.rstrip(".")],
            [tariff_source] if tariff_source else [],
        )
    )

    if water:
        kind = "evaporative" if inputs.cooling == "evaporative" else "closed-loop"
        if _f(water) > 0:
            text = f"With {kind} cooling it would use about {_f(water):,.0f} gallons of water a day"
            text += f", what about {_f(water_homes):,.0f} homes use." if water_homes else "."
        else:
            text = (
                f"With {kind} cooling it would use no water for cooling, as the cited design does."
            )
        lines.append(
            _line(
                text,
                "water",
                water.confidence,
                use(water, water_homes),
                now_iso,
                [water.basis, water_homes.basis if water_homes else ""],
            )
        )

    if acres:
        text = f"It would cover about {_f(acres):,.0f} acres"
        text += f", roughly {_f(fields):,.0f} football fields." if fields else "."
        if months:
            a, b = _pair(months)
            text += f" Building it would take about {a:,.0f} to {b:,.0f} months."
        lines.append(
            _line(
                text,
                "land",
                acres.confidence,
                use(acres, fields, months),
                now_iso,
                [acres.basis, fields.basis if fields else "", months.basis if months else ""],
            )
        )

    miles = distance_km * model.KM_TO_MI
    where = (
        f"Dropped at the pin, the campus would sit {miles:.1f} miles from the centre of "
        f"{place_words}."
        if inputs.pin
        else f"Dropped at the centre of {place_words}, the campus would sit among its homes."
    )
    lines.append(
        _line(
            f"{where} {noise.basis}",
            "noise",
            noise.confidence,
            (),
            now_iso,
            [f"{distance_km:.2f} km from the campus to the ZIP centre, by the engine"],
        )
    )

    if taxes or jobs:
        parts = []
        if taxes:
            lo_t, hi_t = _pair(taxes)
            parts.append(f"about ${lo_t:,.0f} to ${hi_t:,.0f} a year in local taxes")
        if jobs:
            parts.append(f"about {_f(jobs):,.0f} permanent jobs")
        lines.append(
            _line(
                f"On the other side of the ledger: {' and '.join(parts)}. "
                "These are the least certain numbers here.",
                "taxes",
                min(r.confidence for r in (taxes, jobs) if r),
                use(taxes, jobs),
                now_iso,
                [taxes.basis if taxes else "", jobs.basis if jobs else ""],
            )
        )

    # Timeline constants back the impact block even when no line shows them.
    use(months)
    for k in used:
        claims.append(
            _engine_claim(
                SECTION, _constant_claim_text(k), k.source_url, k.source_title, k.quote, 0, now_iso
            )
        )
    for n, claim in enumerate(claims, start=1):
        claim["id"] = f"c{n}"

    # --- the card -----------------------------------------------------------------
    card_lines: list[str] = []
    if homes:
        card_lines.append(f"{mw:,} MW campus: power for about {_f(homes):,.0f} homes")
    if bill.range_usd_per_month:
        card_lines.append(f"{fmt_range(*bill.range_usd_per_month)}/mo for a typical home")
    elif bill.kind == "shielded":
        card_lines.append("Bill shield: large-load tariff in force")
    if water:
        gal = _f(water)
        card_lines.append(
            f"About {gal / 1e6:.1f} million gallons of water a day"
            if gal >= 1e6
            else f"About {gal:,.0f} gallons of water a day"
            if gal > 0
            else "No water for cooling (closed loop)"
        )
    if acres:
        card_lines.append(
            f"About {_f(acres):,.0f} acres"
            + (f", {_f(fields):,.0f} football fields" if fields else "")
        )
    if count is not None:
        card_lines.append(f"{_count_words(count)} already within 5 miles")
    hosts: list[str] = []
    for cl in claims:
        h = urlparse(cl["source"]["url"]).netloc.lower().removeprefix("www.")
        if h and h not in hosts:
            hosts.append(h)

    return {
        "scenario_id": scenario_id,
        "generated_at": now_iso,
        "engine": "",  # stamped by the cache
        "kind": "scenario",
        "disclosure": DISCLOSURE,
        "inputs": inputs.as_json(),
        "place": {
            "display": geo.display,
            "state": geo.state,
            "county": geo.county,
            "zip": inputs.zip,
            "lat": geo.lat,
            "lon": geo.lon,
            "households": {"count": int(households.count), "source": hh_source}
            if households is not None
            else None,
        },
        "baseline": {
            "facilities": facilities,
            "facility_count": count,
            "utility": {
                "name": u.name,
                "kind": u.kind,
                "customers": u.customers,
                "source": utility_source,
            }
            if u is not None
            else None,
            "price": price,
            "tariff": {
                "large_load_tariff": t.status,
                "name": t.name,
                "protects_households": t.protects_households,
                "docket": t.docket,
            }
            if t is not None
            else None,
        },
        "impact": impact,
        "lines": lines[:MAX_LINES],
        "interpretation": None,
        "claims": claims,
        "card": {
            "title": f"Who's on my grid: what if {mw:,} MW came to {geo.display}",
            "lines": [line[:80] for line in card_lines[:CARD_LINES]],
            "footer": f"Sources: {', '.join(hosts[:4]) if hosts else 'none cited'}. "
            "Modelled by the engine from cited figures; no model wrote these numbers.",
            "disclosure": scenario_disclosure_line(
                scenario_id, now_iso, public_base_url, verified=verified
            ),
        },
    }
