"""Run the 30-address test set against a running API and score the briefs.

    python eval/run_eval.py --api http://localhost:8010 --out eval/runs/baseline
    python eval/run_eval.py --out eval/runs/baseline --score-only
    python eval/run_eval.py --api ... --out ... --only bellevue,quincy

Resolution: the test set gives street-level pins without house numbers, which the
Census geocoder rejects. Each pin is reverse-geocoded once (Nominatim, 1 req/s) to
a numbered address, checked against the Census geocoder, and the result is cached
in eval/resolved.json so later runs hit the same address.

Scoring is per dimension (grid, bill, protection, strip, signatures, hearing) from
`expect` in eval/addresses.json. Hearing is scored where a hook is expected and the county
is indexed (step 4), informational elsewhere. A row passes when every
other dimension passes. The report is written to <out>/report.md and
<out>/summary.json; raw briefs to <out>/briefs/<id>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
ADDRESSES = HERE / "addresses.json"
RESOLVED = HERE / "resolved.json"
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
UA = "whos-on-my-grid-eval/0.1 (dev harness)"

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}  # fmt: skip


# --- resolution -------------------------------------------------------------


async def census_match(client: httpx.AsyncClient, address: str) -> str | None:
    r = await client.get(
        CENSUS,
        params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
        timeout=30,
    )
    r.raise_for_status()
    m = r.json().get("result", {}).get("addressMatches") or []
    return m[0]["matchedAddress"] if m else None


async def reverse(client: httpx.AsyncClient, lat: float, lon: float) -> dict[str, Any]:
    r = await client.get(
        NOMINATIM,
        params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18},
        headers={"User-Agent": UA},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("address", {})


def compose(addr: dict[str, Any], fallback_city: str, fallback_state: str, zip_code: str) -> str | None:
    num = addr.get("house_number")
    road = addr.get("road")
    if not num or not road:
        return None
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("suburb") or fallback_city
    state = STATES.get((addr.get("state") or "").lower(), fallback_state)
    return f"{num} {road}, {city}, {state} {addr.get('postcode') or zip_code}"


def split_test_address(address: str) -> tuple[str, str, str]:
    """'F St SW, Quincy, WA 98848' -> ('Quincy', 'WA', '98848')."""
    parts = [p.strip() for p in address.split(",")]
    city = parts[-2] if len(parts) >= 2 else ""
    st_zip = parts[-1].split()
    return city, st_zip[0], st_zip[1] if len(st_zip) > 1 else ""


# Offsets in degrees: the pin, then ~100 m and ~250 m in eight directions.
PROBES = [(0.0, 0.0)] + [
    (r * dy, r * dx * 1.3)
    for r in (0.0009, 0.0022)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
]


async def resolve_all(rows: list[dict[str, Any]]) -> dict[str, str]:
    cache: dict[str, str] = json.loads(RESOLVED.read_text("utf-8")) if RESOLVED.exists() else {}
    async with httpx.AsyncClient() as client:
        for row in rows:
            if row["id"] in cache:
                continue
            if await census_match(client, row["address"]):
                cache[row["id"]] = row["address"]
            else:
                city, state, zip_code = split_test_address(row["address"])
                found = None
                # The pin itself first, then a ring of nearby points: a street-level pin
                # often sits on the carriageway, where OSM has no house number.
                fallback = None
                for dlat, dlon in PROBES:
                    addr = await reverse(client, row["lat"] + dlat, row["lon"] + dlon)
                    await asyncio.sleep(1.1)  # Nominatim usage policy
                    composed = compose(addr, city, state, zip_code)
                    if composed and await census_match(client, composed):
                        # Stay in the test row's city: a pin on a city line must not
                        # drift into the next town's territory and facilities.
                        if city.lower() in composed.lower():
                            found = composed
                            break
                        fallback = fallback or composed
                found = found or fallback
                if found:
                    cache[row["id"]] = found
                else:
                    print(f"  ! {row['id']}: could not resolve {row['address']!r}")
                    continue
            print(f"  {row['id']}: {cache[row['id']]}")
            RESOLVED.write_text(json.dumps(cache, indent=2), "utf-8")
    return cache


# --- run -------------------------------------------------------------------


async def run_all(
    api: str, rows: list[dict[str, Any]], resolved: dict[str, str], out: Path, concurrency: int
) -> None:
    (out / "briefs").mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=30)) as client:

        async def one(row: dict[str, Any]) -> None:
            rid = row["id"]
            if rid not in resolved:
                return
            async with sem:
                started = time.monotonic()
                try:
                    r = await client.post(f"{api}/api/brief", json={"address": resolved[rid]})
                    ms = int((time.monotonic() - started) * 1000)
                    body: Any = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
                    (out / "briefs" / f"{rid}.json").write_text(
                        json.dumps({"status": r.status_code, "ms": ms, "brief": body}, indent=1), "utf-8"
                    )
                    print(f"  {rid}: HTTP {r.status_code} in {ms / 1000:.0f}s")
                except Exception as exc:  # noqa: BLE001
                    ms = int((time.monotonic() - started) * 1000)
                    (out / "briefs" / f"{rid}.json").write_text(
                        json.dumps({"status": 0, "ms": ms, "error": repr(exc)}, indent=1), "utf-8"
                    )
                    print(f"  {rid}: ERROR {exc!r}")

        await asyncio.gather(*(one(r) for r in rows))


# --- score -----------------------------------------------------------------


def all_text(brief: dict[str, Any]) -> str:
    return json.dumps(brief, ensure_ascii=False)


def facilities(brief: dict[str, Any]) -> list[dict[str, Any]]:
    s = brief["sections"]
    return [*(s["on_your_grid"].get("facilities") or []), *(s["coming"].get("facilities") or [])]


def rx(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def score_row(row: dict[str, Any], result: dict[str, Any], global_forbid: dict[str, str]) -> dict[str, Any]:
    exp = row["expect"]
    dims: dict[str, dict[str, Any]] = {}
    if result.get("status") != 200 or not isinstance(result.get("brief"), dict):
        why = result.get("error") or f"HTTP {result.get('status')}: {str(result.get('brief'))[:120]}"
        return {"id": row["id"], "pass": False, "dims": {"request": {"pass": False, "note": why}}}
    b = result["brief"]
    text = all_text(b)
    facs = facilities(b)
    live = [f for f in facs if f["status"] == "live"]
    ann = [f for f in facs if f["status"] in ("announced", "under_construction")]
    # Measured construction counts as coming when it adjoins a listed data center.
    cons = [c for c in (b["sections"]["coming"].get("construction") or []) if c.get("in_database") or c.get("near_cluster")]

    # grid: bucket, live split, operators named
    notes = []
    ok = True
    lo, hi = exp["facilities"]
    n = len(facs)
    if n < lo or (hi is not None and n > hi):
        ok = False
        notes.append(f"{n} facilities, expected {lo}..{hi if hi is not None else '∞'}")
    if "live" in exp:
        llo, lhi = exp["live"]
        if len(live) < llo or (lhi is not None and len(live) > lhi):
            ok = False
            notes.append(f"{len(live)} live, expected {llo}..{lhi}")
    if exp.get("announced_min", 0) > len(ann) + len(cons):
        ok = False
        notes.append(f"{len(ann)} announced/under construction + {len(cons)} measured roofs, expected ≥{exp['announced_min']}")
    named = " ".join(f"{f.get('operator', '')} {f.get('name', '')}" for f in facs)
    hits = [o for o in exp.get("operators", []) if rx(re.escape(o), named)]
    if len(hits) < exp.get("operators_min", 0):
        ok = False
        notes.append(f"operators named {hits or 'none'}, expected ≥{exp['operators_min']} of {exp['operators']}")
    for pat in exp.get("forbid_announced", []):
        if any(rx(pat, f"{f.get('name', '')} {f.get('codename', '')}") for f in ann):
            ok = False
            notes.append(f"'{pat}' listed as announced/under construction")
    if b["sections"]["on_your_grid"]["status"] == "unavailable" and lo > 0:
        ok = False
        notes.append("On your grid unavailable")
    dims["grid"] = {"pass": ok, "note": "; ".join(notes) or f"{n} facilities ({len(live)} live), named {hits}"}

    # bill: direction, hero size, attribution, serving utility
    notes, ok = [], True
    h = b["headline"]
    rent = h.get("ai_rent_usd_per_month")
    bill = exp["bill"]
    if rent is None:
        ok = False
        notes.append("no bill number")
    else:
        rlo, rhi = bill["range"]
        if not (rlo <= rent <= rhi):
            ok = False
            notes.append(f"hero ${rent:+.0f}/mo outside {rlo}..{rhi}")
        if bill["direction"] == "up" and rent <= 0:
            ok = False
            notes.append("direction not up")
    price = b["sections"]["your_bill"].get("price") or {}
    attribution = price.get("attribution")
    if bill.get("attribution", "any") is None and attribution:
        ok = False
        notes.append(f"attribution present where none is warranted: {attribution[:80]!r}")
    if bill.get("attribution") == "required" and not attribution:
        ok = False
        notes.append("attribution missing")
    util = b["address"].get("utility") or ""
    util_ok = rx(exp["utility"], util) or rx(exp["utility"], text)
    if not util_ok:
        ok = False
        notes.append(f"serving utility {util or 'not named'}; expected /{exp['utility']}/")
    elif not rx(exp["utility"], util):
        notes.append("utility only in prose, not in address.utility")
    dims["bill"] = {"pass": ok, "note": "; ".join(notes) or f"${rent:+.0f}/mo, utility {util or '(prose)'}"}

    # protection
    notes, ok = [], True
    t = b["sections"]["protection"].get("tariff") or {}
    val = t.get("large_load_tariff", "unknown")
    if val not in exp["protection"]:
        ok = False
        notes.append(f"tariff {val}, expected one of {exp['protection']}")
    if exp.get("protection_specific") and not (t.get("name") or t.get("docket")):
        ok = False
        notes.append("no tariff name or docket where a real case exists")
    dims["protection"] = {"pass": ok, "note": "; ".join(notes) or f"{val}{' ' + t['name'] if t.get('name') else ''}"}

    # strip
    notes, ok = [], True
    lines = b.get("at_your_house") or []
    topics = [ln["topic"] for ln in lines]
    for tp in exp.get("strip_requires", []):
        if tp not in topics:
            ok = False
            notes.append(f"no {tp} line")
    if exp.get("strip_requires_any") and not any(tp in topics for tp in exp["strip_requires_any"]):
        ok = False
        notes.append(f"none of {exp['strip_requires_any']}")
    model_lines = [ln for ln in lines if ln["topic"] != "bill"]
    if exp.get("strip_lead") and (not model_lines or model_lines[0]["topic"] != exp["strip_lead"]):
        ok = False
        notes.append(f"strip leads with {model_lines[0]['topic'] if model_lines else 'nothing'}, expected {exp['strip_lead']}")
    # a consequence line that asserts a nearby facility while the brief lists none
    if not facs:
        for ln in model_lines:
            if ln["topic"] in ("noise", "water", "air", "land") and ln["status"] != "unavailable" and not rx(r"not (known|public)|no (nearby|data)", ln["text"]):
                notes.append(f"{ln['topic']} line asserts impact with no facility listed")
    dims["strip"] = {"pass": ok, "note": "; ".join(notes) or f"topics {topics}"}

    # signatures: hard-fail patterns, global and per address
    notes = []
    for name, pat in global_forbid.items():
        if rx(pat, text):
            notes.append(name)
    for pat in exp.get("forbid", []):
        if rx(pat, text):
            notes.append(f"forbidden /{pat}/")
    for pat in exp.get("require_text", []):
        if not rx(pat, text):
            notes.append(f"missing /{pat}/")
    if exp.get("require_text_any") and not any(rx(p, text) for p in exp["require_text_any"]):
        notes.append(f"missing any of {exp['require_text_any']}")
    dims["signatures"] = {"pass": not notes, "note": "; ".join(notes) or "clean"}

    # hearing: scored where a hook is expected and the county is indexed (step 4);
    # informational elsewhere, since no transcript exists to measure against.
    hs = b["sections"]["hearing"]
    hr = hs.get("hearing") or {}
    has = bool(hr.get("next_date") or hr.get("body") or hr.get("last_meeting_said"))
    want = exp.get("hearing", "none_ok")
    unindexed = "not indexed yet" in (hs.get("gap") or "")
    dims["hearing"] = {
        "pass": has or want == "none_ok",
        "note": (("measured: " if hs.get("status") == "measured" else "hook found: ") + str(hr.get("body") or hr.get("subject"))[:60]) if has else ("none (hook expected)" if want == "expected" else "none"),
        "informational": want != "expected" or unindexed,
    }

    # verification state
    claims = b.get("claims", [])
    verdicts = {}
    for c in claims:
        verdicts[c["verdict"]] = verdicts.get(c["verdict"], 0) + 1
    dims["claims"] = {"pass": True, "note": ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items())) or "none", "informational": True}

    overall = all(d["pass"] for d in dims.values() if not d.get("informational"))
    return {"id": row["id"], "pass": overall, "dims": dims, "ms": result.get("ms"), "brief_id": b.get("brief_id")}


def score_all(rows: list[dict[str, Any]], out: Path, global_forbid: dict[str, str]) -> dict[str, Any]:
    scored = []
    for row in rows:
        p = out / "briefs" / f"{row['id']}.json"
        if not p.exists():
            scored.append({"id": row["id"], "pass": False, "dims": {"request": {"pass": False, "note": "not run"}}})
            continue
        scored.append(score_row(row, json.loads(p.read_text("utf-8")), global_forbid))
    passed = sum(1 for s in scored if s["pass"])
    dim_names = ["grid", "bill", "protection", "strip", "signatures"]
    per_dim = {d: sum(1 for s in scored if s["dims"].get(d, {}).get("pass")) for d in dim_names}
    summary = {"run": out.name, "addresses": len(scored), "passed": passed, "per_dimension": per_dim, "rows": scored}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), "utf-8")
    (out / "report.md").write_text(render(summary, rows), "utf-8")
    return summary


def render(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    by_id = {r["id"]: r for r in rows}
    lines = [
        f"# Eval run `{summary['run']}`",
        "",
        f"**{summary['passed']} / {summary['addresses']} addresses pass.** "
        + ", ".join(f"{k} {v}/{summary['addresses']}" for k, v in summary["per_dimension"].items()),
        "",
        "| # | Address | Result | Grid | Bill | Protection | Strip | Signatures | Hearing | Claims |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def cell(d: dict[str, Any] | None) -> str:
        if d is None:
            return "—"
        mark = "✅" if d["pass"] else "❌"
        return f"{mark} {d['note']}".replace("|", "/")

    for i, s in enumerate(summary["rows"], 1):
        row = by_id[s["id"]]
        dims = s["dims"]
        if "request" in dims:
            lines.append(f"| {i} | {row['address']} | ❌ | {cell(dims['request'])} | | | | | | |")
            continue
        lines.append(
            f"| {i} | {row['address']} | {'PASS' if s['pass'] else 'FAIL'} | {cell(dims.get('grid'))} | {cell(dims.get('bill'))} | "
            f"{cell(dims.get('protection'))} | {cell(dims.get('strip'))} | {cell(dims.get('signatures'))} | "
            f"{cell(dims.get('hearing'))} | {dims.get('claims', {}).get('note', '')} |"
        )
    return "\n".join(lines) + "\n"


# --- main ------------------------------------------------------------------


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8010")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--resolve-only", action="store_true")
    args = ap.parse_args()

    data = json.loads(ADDRESSES.read_text("utf-8"))
    rows = data["addresses"]
    if args.only:
        keep = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in keep]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if not args.score_only:
        print("Resolving addresses…")
        resolved = await resolve_all(rows)
        if args.resolve_only:
            return 0
        print(f"Running {len(rows)} briefs against {args.api} (concurrency {args.concurrency})…")
        await run_all(args.api, rows, resolved, out, args.concurrency)

    summary = score_all(rows, out, data.get("global_forbid", {}))
    print(f"\n{summary['passed']} / {summary['addresses']} pass. Report: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
