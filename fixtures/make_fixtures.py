"""Generate the fixture briefs. Every operator, source and quote here is fictional.

Run: python fixtures/make_fixtures.py
"""

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).parent / "briefs"
NOW = "2026-10-27T09:00:00Z"
SRC = lambda title, url, quote="", page=None: {"title": title, "url": url, "retrieved_at": NOW, "page": page, "quote": quote}

# --- five addresses chosen to exercise every UI state -------------------------
# ashburn: everything present, critical band
# kenosha: announced campus under a codename, hearing imminent, nothing live yet
# tucson: construction visible from the air, not in any database, no tariff protection
# boise: low band, little happening, most sections thin
# rural_sd: nothing within five miles, sections unavailable, hearing not covered

ADDRESSES = {
    "ashburn": dict(display="Filigree Ct, Ashburn, VA 20147", lat=39.0163, lon=-77.4588, state="VA", county="Loudoun", zip="20147", utility="Dominion Energy Virginia"),
    "kenosha": dict(display="88th Ave, Pleasant Prairie, WI 53158", lat=42.5491, lon=-87.9112, state="WI", county="Kenosha", zip="53158", utility="We Energies"),
    "tucson": dict(display="S Houghton Rd, Tucson, AZ 85747", lat=32.1240, lon=-110.7689, state="AZ", county="Pima", zip="85747", utility="Tucson Electric Power"),
    "boise": dict(display="W Idaho St, Boise, ID 83702", lat=43.6166, lon=-116.2023, state="ID", county="Ada", zip="83702", utility="Idaho Power"),
    "rural_sd": dict(display="County Rd 12, Faulkton, SD 57438", lat=45.0350, lon=-99.1250, state="SD", county="Faulk", zip="57438", utility="Northern Electric Cooperative"),
}


def section(status, confidence, model, summary, sources=(), gap=None, **extra):
    s = {"status": status, "confidence": confidence, "model": model, "summary": summary, "gap": gap, "sources": list(sources)}
    s.update(extra)
    return s


def claim(cid, sec, text, source, verdict="supported", note=None):
    return {"id": cid, "section": sec, "text": text, "source": source, "drafted_by": "muse-spark-1.3",
            "verdict": verdict, "verified_by": "meta-models/muse-spark-open-1026" if verdict != "unchecked" else None, "verifier_note": note}


def brief(key, headline, sections, claims, card):
    a = ADDRESSES[key]
    return {
        "brief_id": hashlib.sha256(a["display"].lower().encode()).hexdigest()[:16],
        "generated_at": NOW, "source_mode": "fixtures", "fixture": True,
        "address": a, "headline": headline, "sections": sections, "claims": claims, "card": card,
    }


BRIEFS = {}

# ---------------------------------------------------------------- ashburn ----
s_pdb = SRC("Facility registry (fictional)", "https://example.org/registry/ash-01")
s_eia = SRC("State residential price series (fictional)", "https://example.org/prices/VA", "Average residential price, VA, Aug 2026: 15.1 c/kWh")
s_mm = SRC("Regional market monitor report (fictional)", "https://example.org/mm/2026", "63% of the capacity price increase is attributable to data center load", page=12)
s_tar = SRC("Commission order, large-load tariff (fictional)", "https://example.org/scc/order-2026-0412", "Customers with demand above 25 MW shall bear the incremental cost of transmission upgrades", page=7)
s_hear = SRC("Board of Supervisors meeting archive, 14 Oct 2026 (fictional)", "https://example.org/loudoun/2026-10-14", "We are not going to approve another campus on that substation until the utility shows us the capacity study")
BRIEFS["ashburn"] = brief(
    "ashburn",
    {"ai_rent_usd_per_month": 31.4, "percentile": 94, "band": "critical",
     "one_liner": "Fifteen data centres within five miles share your substation. A typical home here pays about $31 more a month than two years ago."},
    {
        "on_your_grid": section("measured", 0.92, None,
            "Fifteen data-centre facilities sit within five miles, nine of them within one mile. Eight share the Nimbus 230 kV substation with your street.",
            [s_pdb], facilities=[
                {"name": "Northgate Campus DC1-DC9", "codename": None, "operator": "Halvex Digital (fictional)", "operator_confidence": 0.98, "distance_km": 0.4, "status": "live", "estimated_mw": 180, "mw_basis": "reported", "shares_substation": True, "lat": 39.019, "lon": -77.455},
                {"name": "Loudoun Gateway IAD-4", "codename": None, "operator": "Meridian Realty Trust (fictional)", "operator_confidence": 0.98, "distance_km": 0.9, "status": "live", "estimated_mw": 96, "mw_basis": "reported", "shares_substation": True, "lat": 39.012, "lon": -77.466},
                {"name": "Broad Run Technology Park", "codename": "Project Kestrel", "operator": "Orrin Cloud Services (fictional)", "operator_confidence": 0.81, "distance_km": 2.7, "status": "under_construction", "estimated_mw": 300, "mw_basis": "filed", "shares_substation": False, "lat": 39.03, "lon": -77.48},
                {"name": "Waxpool Edge Site", "codename": None, "operator": "Pinefield Networks (fictional)", "operator_confidence": 0.95, "distance_km": 3.9, "status": "live", "estimated_mw": 10, "mw_basis": "class_estimate", "shares_substation": False, "lat": 39.04, "lon": -77.49},
            ]),
        "coming": section("measured", 0.84, "sam-3.1",
            "Large-roof footprint within five miles grew from 112 to 171 acres between the 2023 and 2025 imagery. One 23-acre site 2.7 km north is not in any facility database.",
            [SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/VA")], construction=[
                {"label": "Broad Run north parcel", "distance_km": 2.7, "footprint_acres_then": 0, "footprint_acres_now": 23.1, "vintages": [2023, 2025], "in_database": False, "polygon": [[39.031, -77.482], [39.031, -77.478], [39.028, -77.478], [39.028, -77.482]]},
                {"label": "Northgate expansion", "distance_km": 0.6, "footprint_acres_then": 41.0, "footprint_acres_now": 58.4, "vintages": [2023, 2025], "in_database": True, "polygon": [[39.020, -77.457], [39.020, -77.452], [39.017, -77.452], [39.017, -77.457]]},
            ]),
        "your_bill": section("modelled", 0.78, "muse-spark-1.3",
            "Your state's residential price rose 14.2% over 24 months. For a home using 1,100 kWh a month that is about $31 more per month. The regional market monitor attributes most of the latest capacity-price increase to data-centre load.",
            [s_eia, s_mm], price={"currency": "USD", "rate_now": 0.151, "rate_then": 0.132, "trend_pct": 14.2, "window_months": 24, "typical_household_kwh_month": 1100,
                                  "attribution": "63% of the capacity price increase is attributable to data center load (market monitor, fictional)"}),
        "protection": section("reported", 0.88, "muse-spark-1.3",
            "A large-load tariff is in force. Customers above 25 MW bear incremental transmission costs, which shields households from that part of the build-out but not from capacity prices.",
            [s_tar], tariff={"large_load_tariff": "in_force", "name": "Schedule GS-5 (fictional)", "protects_households": True, "docket": "PUR-2026-00041"}),
        "hearing": section("measured", 0.9, "muse-voice-transcribe-1.0",
            "The Board of Supervisors votes on the Broad Run rezoning on 12 November. At the last meeting a supervisor said no further campus would be approved on that substation without a capacity study.",
            [s_hear], hearing={"next_date": "2026-11-12", "body": "Loudoun County Board of Supervisors", "subject": "Broad Run Technology Park rezoning",
                               "last_meeting_date": "2026-10-14", "last_meeting_said": [
                                   {"speaker_role": "supervisor", "speaker_name": None, "quote": "We are not going to approve another campus on that substation until the utility shows us the capacity study", "timestamp_s": 4812.0},
                                   {"speaker_role": "resident", "speaker_name": None, "quote": "The hum starts at ten and does not stop", "timestamp_s": 5330.5}]}),
    },
    [
        claim("c1", "on_your_grid", "Eight facilities share the Nimbus substation with the address.", s_pdb),
        claim("c2", "coming", "A 23-acre large-roof site 2.7 km north appears in 2025 imagery and not in 2023 imagery.", SRC("USDA aerial imagery 2025 (public domain)", "https://example.org/naip/VA")),
        claim("c3", "your_bill", "The state residential price rose 14.2% between Aug 2024 and Aug 2026.", s_eia),
        claim("c4", "your_bill", "The market monitor attributes 63% of the capacity price increase to data-centre load.", s_mm),
        claim("c5", "protection", "Customers above 25 MW bear incremental transmission costs under the order.", s_tar),
        claim("c6", "hearing", "The rezoning vote is scheduled for 12 November 2026.", s_hear, "unverifiable", "Agenda for 12 Nov not yet published; date comes from the chair's statement at the 14 Oct meeting."),
    ],
    {"title": "Who's on my grid: Ashburn, VA", "lines": ["15 data centres within 5 miles, 8 on your substation", "+$31/mo for a typical home vs 2024, more than 94% of US households", "23 acres of new campus visible from the air, in no database", "County vote in 16 days"],
     "footer": "Sources: facility registry, state price series, market monitor, county archive. Fictional fixture."},
)

# ---------------------------------------------------------------- kenosha ----
s_news = SRC("County planning packet (fictional)", "https://example.org/kenosha/packet-2026-10", "The applicant, identified in filings as Project Tembo, is a subsidiary of Calder Hyperscale Inc.", page=3)
s_eia_wi = SRC("State residential price series (fictional)", "https://example.org/prices/WI", "Average residential price, WI, Aug 2026: 17.4 c/kWh")
s_hear_k = SRC("County Board meeting archive, 7 Oct 2026 (fictional)", "https://example.org/kenosha/2026-10-07", "We will take public comment on the water agreement at the November 5 session")
BRIEFS["kenosha"] = brief(
    "kenosha",
    {"ai_rent_usd_per_month": 9.8, "percentile": 61, "band": "high",
     "one_liner": "Nothing is running yet. A 600 MW campus filed under a codename is 2.4 miles away and the county votes on 5 November."},
    {
        "on_your_grid": section("reported", 0.81, "muse-spark-1.3",
            "No data-centre facility is live within five miles. One campus is announced 3.9 km west under the name Project Tembo. The county planning packet identifies the applicant as Calder Hyperscale.",
            [s_news], facilities=[
                {"name": "Project Tembo", "codename": "Project Tembo", "operator": "Calder Hyperscale Inc. (fictional)", "operator_confidence": 0.86, "distance_km": 3.9, "status": "announced", "estimated_mw": 600, "mw_basis": "filed", "shares_substation": None, "lat": 42.55, "lon": -87.96}]),
        "coming": section("measured", 0.7, "sam-3.1",
            "Imagery shows grading on 140 acres at the announced site between 2023 and 2025 but no roofs yet.",
            [SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/WI")], construction=[
                {"label": "Project Tembo site", "distance_km": 3.9, "footprint_acres_then": 0, "footprint_acres_now": 0, "vintages": [2023, 2025], "in_database": False, "polygon": []}],
            gap="Graded land is not a roof. Footprint is 0 until buildings appear."),
        "your_bill": section("modelled", 0.74, "muse-spark-1.3",
            "Your state's residential price rose 6.1% over 24 months, about $10 more per month for a typical home. No regulator statement attributes any of it to data centres yet.",
            [s_eia_wi], price={"currency": "USD", "rate_now": 0.174, "rate_then": 0.164, "trend_pct": 6.1, "window_months": 24, "typical_household_kwh_month": 950, "attribution": None}),
        "protection": section("reported", 0.6, "muse-spark-1.3",
            "A large-load tariff has been proposed but not approved. Until it is, the cost allocation for the new load is the general tariff.",
            [SRC("Commission docket index (fictional)", "https://example.org/psc/docket-5-UR-200")], tariff={"large_load_tariff": "proposed", "name": "Very Large Customer rate (fictional)", "protects_households": None, "docket": "5-UR-200"}),
        "hearing": section("measured", 0.9, "muse-voice-transcribe-1.0",
            "The County Board takes public comment on the water agreement on 5 November. At the 7 October meeting the chair confirmed the comment session; a resident asked who the applicant was and was not answered.",
            [s_hear_k], hearing={"next_date": "2026-11-05", "body": "Kenosha County Board", "subject": "Project Tembo water agreement, public comment",
                                 "last_meeting_date": "2026-10-07", "last_meeting_said": [
                                     {"speaker_role": "chair", "speaker_name": None, "quote": "We will take public comment on the water agreement at the November 5 session", "timestamp_s": 2210.0},
                                     {"speaker_role": "resident", "speaker_name": None, "quote": "Who is actually behind this? Nobody will say.", "timestamp_s": 3105.0}]}),
    },
    [
        claim("c1", "on_your_grid", "The planning packet identifies the Project Tembo applicant as a Calder Hyperscale subsidiary.", s_news),
        claim("c2", "your_bill", "The state residential price rose 6.1% over 24 months.", s_eia_wi),
        claim("c3", "hearing", "Public comment on the water agreement is scheduled for 5 November.", s_hear_k),
        claim("c4", "protection", "The large-load tariff is proposed and not yet approved.", SRC("Commission docket index (fictional)", "https://example.org/psc/docket-5-UR-200"), "unverifiable", "Docket index lists the filing but the verifier could not read the status field."),
    ],
    {"title": "Who's on my grid: Pleasant Prairie, WI", "lines": ["0 live, 1 announced: Project Tembo = Calder Hyperscale, 600 MW, 2.4 mi", "140 acres graded, no roofs yet", "+$10/mo for a typical home vs 2024", "Public comment in 9 days"],
     "footer": "Sources: county packet, state price series, county archive. Fictional fixture."},
)

# ----------------------------------------------------------------- tucson ----
s_eia_az = SRC("State residential price series (fictional)", "https://example.org/prices/AZ", "Average residential price, AZ, Aug 2026: 14.9 c/kWh")
BRIEFS["tucson"] = brief(
    "tucson",
    {"ai_rent_usd_per_month": 12.6, "percentile": 72, "band": "high",
     "one_liner": "A 61-acre building appeared 1.8 miles away between the last two aerial surveys. No database lists it, and the state has no large-load tariff."},
    {
        "on_your_grid": section("reported", 0.55, "muse-spark-1.3",
            "No facility within five miles appears in any registry. One is visible from the air (see Coming). The operator is not known.",
            [], gap="No registry entry and no public filing names an operator for the site visible in imagery.", facilities=[]),
        "coming": section("measured", 0.88, "sam-3.1",
            "A 61-acre large-roof building 2.9 km south-east appears in 2025 imagery and not in 2023 imagery. It is in no facility database.",
            [SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/AZ")], construction=[
                {"label": "Houghton Rd south parcel", "distance_km": 2.9, "footprint_acres_then": 0, "footprint_acres_now": 61.2, "vintages": [2023, 2025], "in_database": False, "polygon": [[32.105, -110.765], [32.105, -110.758], [32.100, -110.758], [32.100, -110.765]]}]),
        "your_bill": section("modelled", 0.76, "muse-spark-1.3",
            "Your state's residential price rose 8.9% over 24 months, about $13 more per month for a typical home.",
            [s_eia_az], price={"currency": "USD", "rate_now": 0.149, "rate_then": 0.137, "trend_pct": 8.9, "window_months": 24, "typical_household_kwh_month": 1150, "attribution": None}),
        "protection": section("reported", 0.7, "muse-spark-1.3",
            "No large-load tariff was found for this state. Costs of serving new large customers fall under the general tariff.",
            [SRC("Commission tariff index (fictional)", "https://example.org/acc/tariffs")], tariff={"large_load_tariff": "none_found", "name": None, "protects_households": False, "docket": None}),
        "hearing": section("measured", 0.85, "muse-voice-transcribe-1.0",
            "The Board of Supervisors rejected the development agreement for the site on 20 October. No further hearing is scheduled.",
            [SRC("Board of Supervisors meeting archive, 20 Oct 2026 (fictional)", "https://example.org/pima/2026-10-20", "The motion to deny the development agreement carries unanimously")],
            hearing={"next_date": None, "body": "Pima County Board of Supervisors", "subject": "Development agreement, Houghton Rd parcel", "last_meeting_date": "2026-10-20",
                     "last_meeting_said": [{"speaker_role": "chair", "speaker_name": None, "quote": "The motion to deny the development agreement carries unanimously", "timestamp_s": 7720.0}]}),
    },
    [
        claim("c1", "coming", "A 61-acre building appears in 2025 imagery and not in 2023 imagery at the Houghton Rd parcel.", SRC("USDA aerial imagery 2025 (public domain)", "https://example.org/naip/AZ")),
        claim("c2", "your_bill", "The state residential price rose 8.9% over 24 months.", s_eia_az),
        claim("c3", "protection", "No large-load tariff is listed in the commission tariff index.", SRC("Commission tariff index (fictional)", "https://example.org/acc/tariffs")),
        claim("c4", "hearing", "The board denied the development agreement unanimously on 20 October.", SRC("Board of Supervisors meeting archive, 20 Oct 2026 (fictional)", "https://example.org/pima/2026-10-20", "The motion to deny the development agreement carries unanimously")),
    ],
    {"title": "Who's on my grid: Tucson, AZ", "lines": ["61 acres of new building 1.8 mi away, in no database", "Operator: not known", "+$13/mo for a typical home vs 2024", "No large-load tariff in this state"],
     "footer": "Sources: aerial imagery, state price series, commission index, county archive. Fictional fixture."},
)

# ------------------------------------------------------------------ boise ----
s_eia_id = SRC("State residential price series (fictional)", "https://example.org/prices/ID", "Average residential price, ID, Aug 2026: 11.2 c/kWh")
BRIEFS["boise"] = brief(
    "boise",
    {"ai_rent_usd_per_month": 4.1, "percentile": 28, "band": "low",
     "one_liner": "Two small facilities within five miles, no construction visible, and a typical home pays about $4 more a month than two years ago."},
    {
        "on_your_grid": section("measured", 0.9, None,
            "Two facilities within five miles, both small colocation sites. Neither shares your substation.",
            [SRC("Facility registry (fictional)", "https://example.org/registry/boi-01")], facilities=[
                {"name": "Capitol Colo", "codename": None, "operator": "Sawtooth Data (fictional)", "operator_confidence": 0.97, "distance_km": 1.1, "status": "live", "estimated_mw": 10, "mw_basis": "class_estimate", "shares_substation": False, "lat": 43.62, "lon": -116.21},
                {"name": "Boise Edge 2", "codename": None, "operator": "Pinefield Networks (fictional)", "operator_confidence": 0.97, "distance_km": 4.6, "status": "live", "estimated_mw": 10, "mw_basis": "class_estimate", "shares_substation": False, "lat": 43.59, "lon": -116.25}]),
        "coming": section("measured", 0.8, "sam-3.1", "No new large-roof construction within five miles between the 2023 and 2025 imagery.",
            [SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/ID")], construction=[]),
        "your_bill": section("modelled", 0.8, "muse-spark-1.3", "Your state's residential price rose 3.7% over 24 months, about $4 more per month for a typical home.",
            [s_eia_id], price={"currency": "USD", "rate_now": 0.112, "rate_then": 0.108, "trend_pct": 3.7, "window_months": 24, "typical_household_kwh_month": 1000, "attribution": None}),
        "protection": section("reported", 0.65, "muse-spark-1.3", "A large-load tariff is in force for customers above 20 MW.",
            [SRC("Commission order (fictional)", "https://example.org/puc/order-36000", "Schedule 20 applies to new loads of 20 MW or more", page=2)], tariff={"large_load_tariff": "in_force", "name": "Schedule 20 (fictional)", "protects_households": True, "docket": "IPC-E-26-11"}),
        "hearing": section("unavailable", 0.0, None, "Hearings in this county are not yet indexed.", [], gap="Ada County is not in the indexed set. See docs/counties.md.", hearing={"next_date": None, "body": None}),
    },
    [
        claim("c1", "your_bill", "The state residential price rose 3.7% over 24 months.", s_eia_id),
        claim("c2", "protection", "Schedule 20 applies to new loads of 20 MW or more.", SRC("Commission order (fictional)", "https://example.org/puc/order-36000", "Schedule 20 applies to new loads of 20 MW or more", page=2)),
    ],
    {"title": "Who's on my grid: Boise, ID", "lines": ["2 small facilities within 5 miles, none on your substation", "No new construction visible from the air", "+$4/mo for a typical home vs 2024", "Large-load tariff in force"],
     "footer": "Sources: facility registry, aerial imagery, state price series, commission order. Fictional fixture."},
)

# --------------------------------------------------------------- rural_sd ----
s_eia_sd = SRC("State residential price series (fictional)", "https://example.org/prices/SD", "Average residential price, SD, Aug 2026: 12.8 c/kWh")
BRIEFS["rural_sd"] = brief(
    "rural_sd",
    {"ai_rent_usd_per_month": 2.3, "percentile": 11, "band": "low",
     "one_liner": "No data centre within five miles and nothing visible from the air. Your state's price rose about $2 a month for a typical home."},
    {
        "on_your_grid": section("measured", 0.9, None, "No data-centre facility within five miles.", [SRC("Facility registry (fictional)", "https://example.org/registry/sd")], facilities=[]),
        "coming": section("measured", 0.8, "sam-3.1", "No new large-roof construction within five miles between the 2022 and 2024 imagery.",
            [SRC("USDA aerial imagery 2022 and 2024 (public domain)", "https://example.org/naip/SD")], construction=[]),
        "your_bill": section("modelled", 0.8, "muse-spark-1.3", "Your state's residential price rose 2.1% over 24 months, about $2 more per month for a typical home.",
            [s_eia_sd], price={"currency": "USD", "rate_now": 0.128, "rate_then": 0.125, "trend_pct": 2.1, "window_months": 24, "typical_household_kwh_month": 1050, "attribution": None}),
        "protection": section("unavailable", 0.0, "muse-spark-1.3", "Not known. No large-load tariff or docket was found for this state, and the absence could not be confirmed.", [],
            gap="Search found no tariff and no docket; the verifier could not confirm a negative.", tariff={"large_load_tariff": "unknown", "name": None, "protects_households": None, "docket": None}),
        "hearing": section("unavailable", 0.0, None, "Hearings in this county are not yet indexed.", [], gap="Faulk County is not in the indexed set.", hearing={"next_date": None, "body": None}),
    },
    [claim("c1", "your_bill", "The state residential price rose 2.1% over 24 months.", s_eia_sd)],
    {"title": "Who's on my grid: Faulkton, SD", "lines": ["Nothing within 5 miles", "Nothing new visible from the air", "+$2/mo for a typical home vs 2024", "Tariff protection: not known"],
     "footer": "Sources: facility registry, aerial imagery, state price series. Fictional fixture."},
)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for key, b in BRIEFS.items():
        (OUT / f"{key}.json").write_text(json.dumps(b, indent=2) + "\n", encoding="utf-8")
        print("wrote", key, b["brief_id"])
