"""Generate the fixture briefs. Every operator, source and quote here is fictional,
except that the Irish fixture's Coming entry names the applicant of a real, public
planning decision (its source is still a fictional example.org page).

Run: python fixtures/make_fixtures.py
"""

import hashlib
import json
import math
import re
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
    # Ireland (region `ie`): the region-neutral address keys, no state or zip.
    "blanchardstown": dict(display="Blanchardstown, Fingal, Co. Dublin, D15", lat=53.393, lon=-6.392, country="IE", region_code="IE-D", county="Fingal", postal_code="D15", utility="ESB Networks"),
}
LOCALES = {
    "blanchardstown": {"country": "IE", "currency": "EUR", "units": "metric", "language": "en-IE"},
}


def km(a_lat, a_lon, b_lat, b_lon):
    """Great-circle distance, so every plotted facility sits where its row says."""
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dphi, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * 6371.0 * math.asin(math.sqrt(h)), 1)


def facility(key, name, operator, lat, lon, status, mw, basis, codename=None, shares=None, op_conf=0.95):
    a = ADDRESSES[key]
    return {"name": name, "codename": codename, "operator": operator, "operator_confidence": op_conf,
            "distance_km": km(a["lat"], a["lon"], lat, lon), "status": status, "estimated_mw": mw, "mw_basis": basis,
            "shares_substation": shares, "lat": lat, "lon": lon}


def price(rate_now, rate_then, kwh, attribution=None):
    trend = round((rate_now / rate_then - 1) * 100, 1)
    return {"currency": "USD", "rate_now": rate_now, "rate_then": rate_then, "trend_pct": trend, "window_months": 24,
            "typical_household_kwh_month": kwh, "attribution": attribution}


# The headline number and its range come from the price block and nowhere else,
# the same arithmetic as services/api/app/brief/headline.py. The range is the
# spread of household usage around the typical figure (±20%).
def rent(p):
    return round((p["rate_now"] - p["rate_then"]) * p["typical_household_kwh_month"], 1)


def rent_range(p):
    diff = p["rate_now"] - p["rate_then"]
    k = p["typical_household_kwh_month"]
    return [float(round(diff * k * 0.8)), float(round(diff * k * 1.2))]


def headline(p, percentile, band, one_liner):
    return {"ai_rent_usd_per_month": rent(p), "ai_rent_range_usd_per_month": rent_range(p), "percentile": percentile, "band": band, "one_liner": one_liner}


def section(status, confidence, model, summary, sources=(), gap=None, **extra):
    s = {"status": status, "confidence": confidence, "model": model, "summary": summary, "gap": gap, "sources": list(sources)}
    s.update(extra)
    return s


def house(topic, status, confidence, text, sources=()):
    return {"text": text, "topic": topic, "status": status, "confidence": confidence, "sources": list(sources)}


def claim(cid, sec, text, source, verdict="supported", note=None):
    return {"id": cid, "section": sec, "text": text, "source": source, "drafted_by": "muse-spark-1.3", "verdict": verdict,
            "verified_by": "meta-models/muse-spark-open", "verifier_note": note}


def brief_id(a):
    """US: sha256 of the lower-cased display (the ids the five US fixtures always had).
    Elsewhere: app.geocode.brief_id_for(display, country), the country-prefixed key."""
    country = a.get("country", "US")
    if country == "US":
        return hashlib.sha256(a["display"].lower().encode()).hexdigest()[:16]
    norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", a["display"].lower())).strip()
    return hashlib.sha256(f"{country.lower()}|{norm}".encode()).hexdigest()[:16]


def brief(key, headline, sections, claims, card, at_your_house):
    a = ADDRESSES[key]
    out = {"brief_id": brief_id(a), "generated_at": NOW, "source_mode": "fixtures", "fixture": True, "address": a}
    if key in LOCALES:
        out["locale"] = LOCALES[key]
    out.update(headline=headline, sections=sections, claims=claims, at_your_house=at_your_house, card=card)
    return out


BRIEFS = {}

# ---------------------------------------------------------------- ashburn ----
s_pdb = SRC("Facility registry (fictional)", "https://example.org/registry/ash-01")
s_terr = SRC("Utility service territory map (fictional)", "https://example.org/territory/VA", "Dominion Energy Virginia: Loudoun County east of Route 15")
s_eia = SRC("State residential price series (fictional)", "https://example.org/prices/VA", "Average residential price, VA, Aug 2026: 15.1 c/kWh; Aug 2024: 12.3 c/kWh")
s_mm = SRC("Regional market monitor report (fictional)", "https://example.org/mm/2026", "63% of the capacity price increase is attributable to data center load", page=12)
s_tar = SRC("Commission order, large-load tariff (fictional)", "https://example.org/scc/order-2026-0412", "Customers with demand above 25 MW shall bear the incremental cost of transmission upgrades", page=7)
s_hear = SRC("Board of Supervisors meeting archive, 14 Oct 2026 (fictional)", "https://example.org/loudoun/2026-10-14", "We are not going to approve another campus on that substation until the utility shows us the capacity study")
s_water = SRC("Water authority large-user permits (fictional)", "https://example.org/loudounwater/permits-2026", "Combined permitted daily withdrawal, data center accounts: 4.2 MGD, of which 2.3 MGD reclaimed", page=4)
s_budget = SRC("County adopted budget FY2027 (fictional)", "https://example.org/loudoun/budget-fy27", "Data center personal property tax accounts for 38 percent of general fund revenue and allowed a two-cent reduction in the real property tax rate", page=11)
p_va = price(0.151, 0.123, 1100, "63% of the capacity price increase is attributable to data center load (market monitor, fictional)")

# Fifteen facilities, nine within a mile, every one with a point on the map.
# Eight Northgate buildings make the near cluster; the substation flag is an
# inference from distance and is shown as such.
ASHBURN_FACILITIES = [
    *[facility("ashburn", f"Northgate Campus DC{i}", "Halvex Digital (fictional)", lat, lon, "live", 22, "reported", shares=True, op_conf=0.98)
      for i, (lat, lon) in enumerate([(39.0185, -77.4565), (39.0192, -77.4552), (39.0199, -77.4540), (39.0206, -77.4528),
                                      (39.0178, -77.4548), (39.0186, -77.4535), (39.0194, -77.4522), (39.0213, -77.4545)], start=1)],
    facility("ashburn", "Loudoun Gateway IAD-4", "Meridian Realty Trust (fictional)", 39.012, -77.466, "live", 96, "reported", op_conf=0.98),
    facility("ashburn", "Ashburn Crossing B", "Halvex Digital (fictional)", 39.004, -77.470, "live", 36, "reported", op_conf=0.96),
    facility("ashburn", "Beaumeade Hall 2", "Meridian Realty Trust (fictional)", 39.027, -77.443, "live", 48, "reported", op_conf=0.97),
    facility("ashburn", "Pacific Blvd Colo", "Pinefield Networks (fictional)", 39.000, -77.440, "live", 24, "class_estimate", op_conf=0.9),
    facility("ashburn", "Broad Run Technology Park", "Orrin Cloud Services (fictional)", 39.03, -77.48, "under_construction", 300, "filed", codename="Project Kestrel", shares=False, op_conf=0.81),
    facility("ashburn", "Waxpool Edge Site", "Pinefield Networks (fictional)", 39.04, -77.49, "live", 10, "class_estimate", op_conf=0.95),
    facility("ashburn", "Dulles Tech Center 7", "Orrin Cloud Services (fictional)", 38.985, -77.435, "live", 60, "reported", op_conf=0.93),
]
assert len(ASHBURN_FACILITIES) == 15
assert sum(1 for f in ASHBURN_FACILITIES if f["distance_km"] <= 1.609) == 9

BRIEFS["ashburn"] = brief(
    "ashburn",
    headline(p_va, 94, "critical",
             "Fifteen data centers within five miles are on your local grid, served by Dominion Energy. A typical home here pays about $31 more a month than two years ago."),
    {
        "on_your_grid": section("measured", 0.92, None,
            "Fifteen data-center facilities sit within five miles, nine of them within one mile. All are served by Dominion Energy, the utility that serves your street. "
            "The eight Northgate buildings are likely fed from the same 230 kV substation as your neighborhood; that is inferred from distance, not from utility records.",
            [s_pdb, s_terr], facilities=ASHBURN_FACILITIES),
        "coming": section("measured", 0.84, "sam-3.1",
            "Within five miles, 59 acres of open land became data-center roof between the 2023 and 2025 imagery, taking the total from 112 to 171 acres. "
            "One 23-acre site 1.4 miles north of you is in no facility database.",
            [SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/VA")], construction=[
                {"label": "Broad Run north parcel", "distance_km": km(39.0163, -77.4588, 39.0295, -77.48), "footprint_acres_then": 0, "footprint_acres_now": 23.1, "vintages": [2023, 2025], "in_database": False, "polygon": [[39.031, -77.482], [39.031, -77.478], [39.028, -77.478], [39.028, -77.482]]},
                {"label": "Northgate expansion", "distance_km": km(39.0163, -77.4588, 39.0185, -77.4545), "footprint_acres_then": 41.0, "footprint_acres_now": 58.4, "vintages": [2023, 2025], "in_database": True, "polygon": [[39.020, -77.457], [39.020, -77.452], [39.017, -77.452], [39.017, -77.457]]},
            ]),
        "your_bill": section("modelled", 0.78, "muse-spark-1.3",
            "Your state's average residential price rose 22.8% over 24 months. For a home using 1,100 kWh a month that is about $31 more per month, between $25 and $37 depending on how much you use. "
            "The regional market monitor attributes most of the latest capacity-price increase to data-center load.",
            [s_eia, s_mm], price=p_va),
        "protection": section("reported", 0.88, "muse-spark-1.3",
            "Partly. A large-load tariff is in force: customers above 25 MW pay for their own transmission upgrades, so that part of the build-out is kept off your bill. "
            "It does not shield you from capacity prices, which every customer pays and which the market monitor says are rising with data-center load.",
            [s_tar, s_mm], tariff={"large_load_tariff": "in_force", "name": "Schedule GS-5 (fictional)", "protects_households": True, "docket": "PUR-2026-00041"}),
        "hearing": section("measured", 0.9, "muse-voice-transcribe-1.0",
            "The Board of Supervisors votes on the Broad Run rezoning on 12 November. At the last meeting a supervisor said no further campus would be approved on that substation without a capacity study.",
            [s_hear], hearing={"next_date": "2026-11-12", "body": "Loudoun County Board of Supervisors", "subject": "Broad Run Technology Park rezoning",
                               "last_meeting_date": "2026-10-14", "last_meeting_said": [
                                   {"speaker_role": "supervisor", "speaker_name": None, "quote": "We are not going to approve another campus on that substation until the utility shows us the capacity study", "timestamp_s": 4812.0},
                                   {"speaker_role": "resident", "speaker_name": None, "quote": "The hum starts at ten and does not stop", "timestamp_s": 5330.5}]}),
    },
    [
        claim("c1", "on_your_grid", "Fifteen facilities within five miles are in Dominion Energy Virginia's service territory, as is the address.", s_terr),
        claim("c2", "coming", "A 23-acre large-roof site 2.3 km north appears in 2025 imagery and not in 2023 imagery.", SRC("USDA aerial imagery 2025 (public domain)", "https://example.org/naip/VA")),
        claim("c3", "your_bill", "The state residential price rose 22.8% between Aug 2024 and Aug 2026.", s_eia),
        claim("c4", "your_bill", "The market monitor attributes 63% of the capacity price increase to data-center load.", s_mm),
        claim("c5", "protection", "Customers above 25 MW bear incremental transmission costs under the order.", s_tar),
        claim("c6", "hearing", "The rezoning vote is scheduled for 12 November 2026.", s_hear, "unverifiable", "Agenda for 12 Nov not yet published; date comes from the chair's statement at the 14 Oct meeting."),
        claim("c7", "at_your_house", "Data-center accounts within five miles are permitted to withdraw up to 4.2 million gallons a day, 2.3 million of it reclaimed water.", s_water),
        claim("c8", "at_your_house", "Data-center personal property tax is 38% of the county general fund, per the adopted budget.", s_budget),
    ],
    {"title": "Who's on my grid: Ashburn, VA", "lines": ["15 data centers within 5 miles, all on your local grid", "About +$31/mo for a typical home vs 2024, more than 94% of US households", "59 acres of open land became data-center roof since 2023", "County vote in 16 days"],
     "footer": "Sources: facility registry, state price series, market monitor, water permits, county budget, county archive. Fictional fixture."},
    [
        house("bill", "modelled", 0.78, "Your power bill is about $31 a month higher than two years ago, somewhere between $25 and $37 depending on how much electricity you use.", [s_eia]),
        house("water", "reported", 0.72, "The data centers within five miles are permitted to use up to 4.2 million gallons of water a day, about what 14,000 homes use. Just over half of it has to be reclaimed water, not drinking water.", [s_water]),
        house("noise", "modelled", 0.45, "The nearest building is 0.2 miles from your door. At the last county meeting a resident said the hum starts at ten and does not stop. No sound measurement for your street is public.", [s_hear]),
        house("taxes", "reported", 0.85, "The other side, honestly: data centers pay about 38% of Loudoun County's general fund, and the county budget credits that for cutting the residential property tax rate.", [s_budget]),
    ],
)

# ---------------------------------------------------------------- kenosha ----
s_news = SRC("County planning packet (fictional)", "https://example.org/kenosha/packet-2026-10", "The applicant, identified in filings as Project Tembo, is a subsidiary of Calder Hyperscale Inc.", page=3)
s_eia_wi = SRC("State residential price series (fictional)", "https://example.org/prices/WI", "Average residential price, WI, Aug 2026: 17.4 c/kWh")
s_hear_k = SRC("County Board meeting archive, 7 Oct 2026 (fictional)", "https://example.org/kenosha/2026-10-07", "We will take public comment on the water agreement at the November 5 session")
s_naip_wi = SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/WI")
p_wi = price(0.174, 0.164, 950)
BRIEFS["kenosha"] = brief(
    "kenosha",
    headline(p_wi, 61, "high",
             "Nothing is running yet. A 600 MW campus filed under a codename is 2.4 miles away and the county votes on 5 November."),
    {
        "on_your_grid": section("reported", 0.81, "muse-spark-1.3",
            "No data-center facility is live within five miles. One campus is announced 3.9 km west under the name Project Tembo. The county planning packet identifies the applicant as Calder Hyperscale.",
            [s_news], facilities=[
                facility("kenosha", "Project Tembo", "Calder Hyperscale Inc. (fictional)", 42.55, -87.96, "announced", 600, "filed", codename="Project Tembo", op_conf=0.86)]),
        "coming": section("measured", 0.7, "sam-3.1",
            "About 140 acres of farmland at the announced site has been graded flat between the 2023 and 2025 imagery. No roofs yet.",
            [s_naip_wi], construction=[
                {"label": "Project Tembo site", "distance_km": 3.9, "footprint_acres_then": 0, "footprint_acres_now": 0, "vintages": [2023, 2025], "in_database": False, "polygon": []}],
            gap="Graded land is not a roof. Footprint is 0 until buildings appear."),
        "your_bill": section("modelled", 0.74, "muse-spark-1.3",
            "Your state's residential price rose 6.1% over 24 months, about $10 more per month for a typical home. No regulator statement attributes any of it to data centers yet.",
            [s_eia_wi], price=p_wi),
        "protection": section("reported", 0.6, "muse-spark-1.3",
            "Not yet. A large-load tariff has been proposed but not approved. Until it is, the new load is served under the general tariff and nothing in the rules keeps its grid costs off your bill.",
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
    {"title": "Who's on my grid: Pleasant Prairie, WI", "lines": ["0 live, 1 announced: Project Tembo = Calder Hyperscale, 600 MW, 2.4 mi", "140 acres of farmland graded, no roofs yet", "About +$10/mo for a typical home vs 2024", "Public comment in 9 days"],
     "footer": "Sources: county packet, state price series, county archive. Fictional fixture."},
    [
        house("bill", "modelled", 0.74, "Your power bill is about $10 a month higher than two years ago, between $8 and $11 depending on usage. No regulator has tied any of that to data centers.", [s_eia_wi]),
        house("water", "reported", 0.6, "The county is about to vote on a water agreement for the Project Tembo site. How much water it would use has not been made public. Comment is open on 5 November.", [s_hear_k]),
        house("land", "measured", 0.7, "About 140 acres of farmland 2.4 miles west of you has been graded flat since 2023. Nothing has been built on it yet.", [s_naip_wi]),
    ],
)

# ----------------------------------------------------------------- tucson ----
s_eia_az = SRC("State residential price series (fictional)", "https://example.org/prices/AZ", "Average residential price, AZ, Aug 2026: 14.9 c/kWh")
s_naip_az = SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/AZ")
s_pima = SRC("Board of Supervisors meeting archive, 20 Oct 2026 (fictional)", "https://example.org/pima/2026-10-20", "The motion to deny the development agreement carries unanimously")
p_az = price(0.149, 0.137, 1150)
BRIEFS["tucson"] = brief(
    "tucson",
    headline(p_az, 72, "high",
             "A 61-acre building appeared 1.8 miles away between the last two aerial surveys. No database lists it, and the state has no large-load tariff."),
    {
        "on_your_grid": section("reported", 0.55, "muse-spark-1.3",
            "No facility within five miles appears in any registry. One is visible from the air (see Coming). The operator is not known.",
            [], gap="No registry entry and no public filing names an operator for the site visible in imagery.", facilities=[]),
        "coming": section("measured", 0.88, "sam-3.1",
            "A 61-acre building, about 46 football fields of roof, appeared on open desert 2.9 km south-east between the 2023 and 2025 imagery. It is in no facility database.",
            [s_naip_az], construction=[
                {"label": "Houghton Rd south parcel", "distance_km": 2.9, "footprint_acres_then": 0, "footprint_acres_now": 61.2, "vintages": [2023, 2025], "in_database": False, "polygon": [[32.105, -110.765], [32.105, -110.758], [32.100, -110.758], [32.100, -110.765]]}]),
        "your_bill": section("modelled", 0.76, "muse-spark-1.3",
            "Your state's residential price rose 8.8% over 24 months, about $14 more per month for a typical home.",
            [s_eia_az], price=p_az),
        "protection": section("reported", 0.7, "muse-spark-1.3",
            "No. No large-load tariff was found for this state. The cost of serving new large customers falls under the general tariff, which every customer pays.",
            [SRC("Commission tariff index (fictional)", "https://example.org/acc/tariffs")], tariff={"large_load_tariff": "none_found", "name": None, "protects_households": False, "docket": None}),
        "hearing": section("measured", 0.85, "muse-voice-transcribe-1.0",
            "The Board of Supervisors rejected the development agreement for the site on 20 October. No further hearing is scheduled.",
            [s_pima],
            hearing={"next_date": None, "body": "Pima County Board of Supervisors", "subject": "Development agreement, Houghton Rd parcel", "last_meeting_date": "2026-10-20",
                     "last_meeting_said": [{"speaker_role": "chair", "speaker_name": None, "quote": "The motion to deny the development agreement carries unanimously", "timestamp_s": 7720.0}]}),
    },
    [
        claim("c1", "coming", "A 61-acre building appears in 2025 imagery and not in 2023 imagery at the Houghton Rd parcel.", SRC("USDA aerial imagery 2025 (public domain)", "https://example.org/naip/AZ")),
        claim("c2", "your_bill", "The state residential price rose 8.8% over 24 months.", s_eia_az),
        claim("c3", "protection", "No large-load tariff is listed in the commission tariff index.", SRC("Commission tariff index (fictional)", "https://example.org/acc/tariffs")),
        claim("c4", "hearing", "The board denied the development agreement unanimously on 20 October.", s_pima),
    ],
    {"title": "Who's on my grid: Tucson, AZ", "lines": ["61 acres of new building 1.8 mi away, in no database", "Operator: not known", "About +$14/mo for a typical home vs 2024", "No large-load tariff in this state"],
     "footer": "Sources: aerial imagery, state price series, commission index, county archive. Fictional fixture."},
    [
        house("bill", "modelled", 0.76, "Your power bill is about $14 a month higher than two years ago, between $11 and $17 depending on usage.", [s_eia_az]),
        house("land", "measured", 0.88, "A 61-acre building, about 46 football fields of roof, went up on open desert 1.8 miles from you between the last two aerial surveys. Nobody has said publicly who owns it.", [s_naip_az]),
        house("other", "measured", 0.85, "The county board voted unanimously on 20 October to deny the site's development agreement. No new hearing is scheduled.", [s_pima]),
    ],
)

# ------------------------------------------------------------------ boise ----
s_eia_id = SRC("State residential price series (fictional)", "https://example.org/prices/ID", "Average residential price, ID, Aug 2026: 11.2 c/kWh")
s_reg_id = SRC("Facility registry (fictional)", "https://example.org/registry/boi-01")
s_naip_id = SRC("USDA aerial imagery 2023 and 2025 (public domain)", "https://example.org/naip/ID")
s_puc = SRC("Commission order (fictional)", "https://example.org/puc/order-36000", "Schedule 20 applies to new loads of 20 MW or more", page=2)
p_id = price(0.112, 0.108, 1000)
BRIEFS["boise"] = brief(
    "boise",
    headline(p_id, 28, "low",
             "Two small facilities within five miles, no construction visible, and a typical home pays about $4 more a month than two years ago."),
    {
        "on_your_grid": section("measured", 0.9, None,
            "Two facilities within five miles, both small colocation sites, both served by Idaho Power like your street.",
            [s_reg_id], facilities=[
                facility("boise", "Capitol Colo", "Sawtooth Data (fictional)", 43.62, -116.21, "live", 10, "class_estimate", op_conf=0.97),
                facility("boise", "Boise Edge 2", "Pinefield Networks (fictional)", 43.59, -116.25, "live", 10, "class_estimate", op_conf=0.97)]),
        "coming": section("measured", 0.8, "sam-3.1", "No new large-roof construction within five miles between the 2023 and 2025 imagery.",
            [s_naip_id], construction=[]),
        "your_bill": section("modelled", 0.8, "muse-spark-1.3", "Your state's residential price rose 3.7% over 24 months, about $4 more per month for a typical home.",
            [s_eia_id], price=p_id),
        "protection": section("reported", 0.65, "muse-spark-1.3",
            "Partly. A large-load tariff is in force for customers above 20 MW, so new large customers pay their own way onto the grid. The order does not say whether every cost of the build-out stays off household bills.",
            [s_puc], tariff={"large_load_tariff": "in_force", "name": "Schedule 20 (fictional)", "protects_households": True, "docket": "IPC-E-26-11"}),
        "hearing": section("unavailable", 0.0, None, "Hearings in this county are not yet indexed.", [], gap="Ada County is not in the indexed set. See docs/counties.md.", hearing={"next_date": None, "body": None}),
    },
    [
        claim("c1", "your_bill", "The state residential price rose 3.7% over 24 months.", s_eia_id),
        claim("c2", "protection", "Schedule 20 applies to new loads of 20 MW or more.", s_puc),
    ],
    {"title": "Who's on my grid: Boise, ID", "lines": ["2 small facilities within 5 miles, both colocation sites", "No new construction visible from the air", "About +$4/mo for a typical home vs 2024", "Large-load tariff in force"],
     "footer": "Sources: facility registry, aerial imagery, state price series, commission order. Fictional fixture."},
    [
        house("bill", "modelled", 0.8, "Your power bill is about $4 a month higher than two years ago, between $3 and $5 depending on usage.", [s_eia_id]),
        house("grid", "measured", 0.9, "Two small data centers sit within five miles, the nearest 0.7 miles away. Together they draw about 20 MW, roughly what 15,000 homes use at once.", [s_reg_id]),
        house("land", "measured", 0.8, "Nothing new has been built within five miles between the 2023 and 2025 aerial surveys.", [s_naip_id]),
    ],
)

# --------------------------------------------------------------- rural_sd ----
s_eia_sd = SRC("State residential price series (fictional)", "https://example.org/prices/SD", "Average residential price, SD, Aug 2026: 12.8 c/kWh")
s_reg_sd = SRC("Facility registry (fictional)", "https://example.org/registry/sd")
s_naip_sd = SRC("USDA aerial imagery 2022 and 2024 (public domain)", "https://example.org/naip/SD")
p_sd = price(0.128, 0.125, 1050)
BRIEFS["rural_sd"] = brief(
    "rural_sd",
    headline(p_sd, 11, "low",
             "No data center within five miles and nothing visible from the air. Your state's price rose about $3 a month for a typical home."),
    {
        "on_your_grid": section("measured", 0.9, None, "No data-center facility within five miles.", [s_reg_sd], facilities=[]),
        "coming": section("measured", 0.8, "sam-3.1", "No new large-roof construction within five miles between the 2022 and 2024 imagery.",
            [s_naip_sd], construction=[]),
        "your_bill": section("modelled", 0.8, "muse-spark-1.3", "Your state's residential price rose 2.4% over 24 months, about $3 more per month for a typical home.",
            [s_eia_sd], price=p_sd),
        "protection": section("unavailable", 0.0, "muse-spark-1.3", "Not known. No large-load tariff or docket was found for this state, and the absence could not be confirmed.", [],
            gap="Search found no tariff and no docket; the verifier could not confirm a negative.", tariff={"large_load_tariff": "unknown", "name": None, "protects_households": None, "docket": None}),
        "hearing": section("unavailable", 0.0, None, "Hearings in this county are not yet indexed.", [], gap="Faulk County is not in the indexed set.", hearing={"next_date": None, "body": None}),
    },
    [claim("c1", "your_bill", "The state residential price rose 2.4% over 24 months.", s_eia_sd)],
    {"title": "Who's on my grid: Faulkton, SD", "lines": ["Nothing within 5 miles", "Nothing new visible from the air", "About +$3/mo for a typical home vs 2024", "Tariff protection: not known"],
     "footer": "Sources: facility registry, aerial imagery, state price series. Fictional fixture."},
    [
        house("bill", "modelled", 0.8, "Your power bill is about $3 a month higher than two years ago, between $3 and $4 depending on usage.", [s_eia_sd]),
        house("grid", "measured", 0.9, "There is no data center within five miles of you, and nothing new has been built from the air.", [s_reg_sd, s_naip_sd]),
    ],
)

# --------------------------------------------------------- blanchardstown ----
# Ireland: km, EUR, a semiannual Eurostat series, a connection policy rather than a
# tariff, a planning decision 9 km away in Coming, no imagery and no indexed meeting.
# The headline band follows the facility count (step 6 decision 0.9: a national price
# does not set the band).
s_reg_ie = SRC("Facility registry (fictional)", "https://example.org/registry/d15")
s_esb = SRC("Network operator page (fictional)", "https://example.org/esb/about", "ESB Networks DAC is the licensed distribution system operator for Ireland (fictional quote)")
s_estat = SRC("National household price series, semiannual (fictional)", "https://example.org/eurostat/IE", "IE, band DC, all taxes and levies included: 2026-S1 0.3871 EUR/kWh; 2024-S1 0.2590 EUR/kWh (fictional)")
s_kwh = SRC("Regulator typical consumption paper (fictional)", "https://example.org/cru/typical-consumption", "Typical annual domestic electricity consumption: 4,200 kWh (fictional)")
s_cru = SRC("Regulator decision, data-centre connection policy (fictional)", "https://example.org/cru/dc-connection-policy", "New data centres must provide generation or storage to match their requested import capacity (fictional)")
s_acp = SRC("Planning appeal decision (fictional)", "https://example.org/acp/case-320852", "Grant Permissions with Conditions")
p_ie = {**price(0.3871, 0.2590, 350), "currency": "EUR", "as_of": "2026-06", "granularity": "semiannual"}

BLANCHARDSTOWN_FACILITIES = [
    facility("blanchardstown", "Corduff Data Campus A", "Liffey Compute (fictional)", 53.400, -6.405, "live", 40, "reported", op_conf=0.97),
    facility("blanchardstown", "Corduff Data Campus B", "Liffey Compute (fictional)", 53.405, -6.398, "live", 40, "reported", op_conf=0.97),
    facility("blanchardstown", "Ballycoolin Hall 1", "Meridian Realty Trust (fictional)", 53.410, -6.380, "live", 24, "reported", op_conf=0.95),
    facility("blanchardstown", "Damastown Colo", "Pinefield Networks (fictional)", 53.385, -6.420, "live", 10, "class_estimate", op_conf=0.9),
    facility("blanchardstown", "Coolmine Edge", "Pinefield Networks (fictional)", 53.398, -6.360, "live", 6, "class_estimate", op_conf=0.9),
    facility("blanchardstown", "Mulhuddart Cloud Park", "Orrin Cloud Services (fictional)", 53.420, -6.410, "under_construction", 120, "filed", op_conf=0.85),
]
assert len(BLANCHARDSTOWN_FACILITIES) == 6 and all(f["distance_km"] < 8 for f in BLANCHARDSTOWN_FACILITIES)
GRANGE_CASTLE = {"name": "Google Ireland Grange Castle expansion (SD24A/0164W)", "codename": None, "operator": "Google Ireland Limited",
                 "operator_confidence": 0.9, "distance_km": km(53.393, -6.392, 53.3144, -6.4443), "status": "announced",
                 "estimated_mw": None, "mw_basis": None, "shares_substation": None, "lat": 53.3144, "lon": -6.4443}

BRIEFS["blanchardstown"] = brief(
    "blanchardstown",
    headline(p_ie, None, "high", "Six data centres sit within 8 km of you, in ESB Networks' area. A typical Irish home pays about €45 more a month than two years ago."),
    {
        "on_your_grid": section("measured", 0.9, None,
            "Six data-centre facilities sit within 8 km, five running and one under construction. ESB Networks is the distribution operator for Ireland, your street included.",
            [s_reg_ie, s_esb], facilities=BLANCHARDSTOWN_FACILITIES),
        "coming": section("reported", 0.8, None,
            f"An Coimisiún Pleanála granted permission with conditions for the Grange Castle data storage expansion, {GRANGE_CASTLE['distance_km']} km south of you, in September 2026.",
            [s_acp], gap="No aerial imagery is indexed for Ireland, so new roofs are not measured.", facilities=[GRANGE_CASTLE], construction=[]),
        "your_bill": section("modelled", 0.8, "muse-spark-1.3",
            "Ireland's average household electricity price rose 49.5% between the first half of 2024 and the first half of 2026. For a home using 350 kWh a month that is about €45 more per month, between €36 and €54 depending on how much you use.",
            [s_estat, s_kwh], price=p_ie),
        "protection": section("reported", 0.85, "muse-spark-1.3",
            "No. A CRU connection policy for new data centres is in force: they must bring generation or storage to match the capacity they ask for. "
            "Its stated aim is grid constraints, security of supply and renewable targets, not household costs.",
            [s_cru], tariff={"large_load_tariff": "in_force", "name": "CRU connection policy for new data centres (December 2025)", "protects_households": False, "docket": None, "kind": "connection_policy"}),
        "hearing": section("unavailable", 0.0, None, "Meetings of this planning authority are not yet indexed.", [],
            gap="Fingal County Council is not in the indexed set.", hearing={"next_date": None, "body": None}),
    },
    [
        claim("c1", "on_your_grid", "ESB Networks DAC is the licensed distribution system operator for Ireland.", s_esb),
        claim("c2", "your_bill", "Ireland's household electricity price, band DC with all taxes, was 0.3871 EUR per kWh in 2026-S1 and 0.2590 EUR per kWh in 2024-S1.", s_estat),
        claim("c3", "your_bill", "The regulator's typical annual domestic electricity consumption figure is 4,200 kWh.", s_kwh),
        claim("c4", "protection", "New data centres must provide generation or storage to match their requested import capacity.", s_cru),
        claim("c5", "coming", "An Coimisiún Pleanála decided the Grange Castle appeal with the decision Grant Permissions with Conditions.", s_acp),
    ],
    {"title": "Who's on my grid: Blanchardstown, Co. Dublin",
     "lines": ["6 data centres within 8 km", "+€45/mo for a typical home vs 2 yrs ago",
               "CRU data-centre connection policy in force; household bills not its stated aim", f"Grange Castle expansion granted {GRANGE_CASTLE['distance_km']} km away"],
     "footer": "Sources: facility registry, network operator, national price series, regulator decision, planning appeal. Fictional fixture."},
    [
        house("bill", "modelled", 0.8, "Your electricity bill is about €45 a month higher than two years ago, between €36 and €54 depending on how much you use.", [s_estat, s_kwh]),
        house("grid", "measured", 0.9, "Six data centres sit within 8 km, the nearest about a kilometre away.", [s_reg_ie]),
    ],
)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for key, b in BRIEFS.items():
        # newline="\n": the committed files are LF; on Windows text mode would write CRLF.
        (OUT / f"{key}.json").write_text(json.dumps(b, indent=2) + "\n", encoding="utf-8", newline="\n")
        h = b["headline"]
        print("wrote", key, b["brief_id"], h["ai_rent_usd_per_month"], h["ai_rent_range_usd_per_month"])
