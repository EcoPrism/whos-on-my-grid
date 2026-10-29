"""Scripted inputs for the pipeline tests: a geocode result, five section
drafts shaped like Spark's structured output, and the pages the verifier
fetches. Every operator and URL here is fictional."""

from pathlib import Path
from typing import Any

from app.brief.cache import BriefCache
from app.brief.fetch import FakeFetcher
from app.brief.pipeline import BriefService
from app.config import Settings
from app.geocode import FakeGeocoder, GeocodeResult
from app.llm.fake_provider import KeyedFakeProvider

GEO = GeocodeResult(
    display="Filigree Ct, Ashburn, VA 20147",
    lat=39.0163,
    lon=-77.4588,
    state="VA",
    county="Loudoun",
    zip="20147",
    matched="21715 FILIGREE CT, ASHBURN, VA, 20147",
)

URL_REG = "https://example.org/registry/ash-01"
URL_EIA = "https://example.org/prices/VA"
URL_TAR = "https://example.org/scc/order-2026-0412"
URL_HEAR = "https://example.org/loudoun/2026-10-14"
URL_WATER = "https://example.org/loudounwater/permits-2026"
URL_GONE = "https://example.org/missing"

PAGES = {
    URL_REG: "Facility registry. Northgate Campus DC1-DC9 is operated by Halvex Digital at 180 MW. "
    * 10,
    URL_EIA: "Average residential price, VA, Aug 2026: 15.1 c/kWh. Two years earlier it was 13.2 c/kWh. "
    * 10,
    URL_TAR: "Order. Customers with demand above 25 MW shall bear the incremental cost of transmission upgrades. "
    * 10,
    URL_HEAR: "Minutes. The chair said: we are not going to approve another campus on that substation. "
    * 10,
    URL_WATER: "Permits. Combined permitted daily withdrawal, data center accounts: 4.2 MGD. " * 10,
}


def claim(
    text: str, url: str, quote: str = "", title: str = "Source", confidence: float = 0.8
) -> dict[str, Any]:
    return {
        "text": text,
        "source_title": title,
        "source_url": url,
        "quote": quote,
        "page": None,
        "confidence": confidence,
    }


def drafts() -> dict[str, dict[str, Any]]:
    return {
        "draft_on_your_grid": {
            "confidence": 0.7,
            "summary": "Two data-center campuses sit within five miles. One is live and one is under construction.",
            "gap": None,
            "card_line": "2 data centers within 5 miles",
            "facilities": [
                {
                    "name": "Northgate Campus DC1-DC9",
                    "codename": None,
                    "operator": "Halvex Digital",
                    "operator_confidence": 0.9,
                    "distance_km": 0.4,
                    "status": "live",
                    "estimated_mw": 180,
                    "mw_basis": "reported",
                    "shares_substation": None,
                    "lat": 39.019,
                    "lon": -77.455,
                },
                {
                    "name": "Broad Run Technology Park",
                    "codename": "Project Kestrel",
                    "operator": "Orrin Cloud",
                    "operator_confidence": 0.6,
                    "distance_km": 2.7,
                    "status": "under_construction",
                    "estimated_mw": 300,
                    "mw_basis": "filed",
                    "shares_substation": None,
                    "lat": None,
                    "lon": None,
                },
            ],
            "claims": [
                claim(
                    "Northgate Campus is operated by Halvex Digital at about 180 MW.",
                    URL_REG,
                    "operated by Halvex Digital at 180 MW",
                    "Facility registry",
                ),
                claim(
                    "Broad Run Technology Park is under construction.",
                    URL_GONE,
                    "",
                    "County permit",
                ),
            ],
        },
        "draft_coming": {
            "confidence": 0.5,
            "summary": "One campus has been announced within five miles. Aerial imagery is not available in this mode.",
            "gap": "No aerial imagery in agent mode.",
            "card_line": "1 campus announced",
            "facilities": [
                {
                    "name": "Waxpool North",
                    "codename": None,
                    "operator": "Pinefield Networks",
                    "operator_confidence": 0.5,
                    "distance_km": 3.9,
                    "status": "announced",
                    "estimated_mw": None,
                    "mw_basis": None,
                    "shares_substation": None,
                    "lat": None,
                    "lon": None,
                },
            ],
            "claims": [
                claim(
                    "Waxpool North has been announced by Pinefield Networks.",
                    URL_REG,
                    "",
                    "Facility registry",
                )
            ],
        },
        "draft_your_bill": {
            "confidence": 0.8,
            "summary": "Virginia's residential price rose about 14% over 24 months. That is about $21 more a month for a typical home.",
            "gap": None,
            "card_line": "+$21/mo for a typical home vs 2024",
            "price": {
                "currency": "USD",
                "rate_now": 0.151,
                "rate_then": 0.132,
                "trend_pct": 14.4,
                "window_months": 24,
                "typical_household_kwh_month": 1100,
                "attribution": None,
            },
            "claims": [
                claim(
                    "Virginia's average residential price was 15.1 c/kWh in August 2026.",
                    URL_EIA,
                    "Aug 2026: 15.1 c/kWh",
                    "State price series",
                )
            ],
        },
        "draft_protection": {
            "confidence": 0.6,
            "summary": "A large-load tariff is in force. It makes customers above 25 MW bear transmission upgrade costs.",
            "gap": None,
            "card_line": "Tariff protection: in force",
            "tariff": {
                "large_load_tariff": "in_force",
                "name": "Schedule GS-5",
                "protects_households": True,
                "docket": "PUR-2026-0412",
            },
            "claims": [
                claim(
                    "Customers above 25 MW bear incremental transmission costs.",
                    URL_TAR,
                    "shall bear the incremental cost of transmission upgrades",
                    "Commission order",
                )
            ],
        },
        "draft_at_your_house": {
            "lines": [
                {
                    "text": "The data centers near you may use up to 4.2 million gallons of water a day, about what 14,000 homes use.",
                    "topic": "water",
                    "confidence": 0.7,
                    "claims": [
                        claim(
                            "Data-center accounts are permitted 4.2 million gallons a day.",
                            URL_WATER,
                            "4.2 MGD",
                            "Water permits",
                        )
                    ],
                },
                {
                    "text": "The nearest building is 0.2 miles from your door. No sound measurement is public.",
                    "topic": "noise",
                    "confidence": 0.3,
                    "claims": [],
                },
            ]
        },
        "draft_hearing": {
            "confidence": 0.4,
            "summary": "The county board next meets on 2026-11-12. At the last meeting the chair opposed another campus on the substation.",
            "gap": None,
            "card_line": None,
            "hearing": {
                "next_date": "2026-11-12",
                "body": "Loudoun County Board of Supervisors",
                "subject": "Rezoning",
                "last_meeting_date": "2026-10-14",
                "last_meeting_said": [
                    {
                        "speaker_role": "chair",
                        "speaker_name": None,
                        "quote": "we are not going to approve another campus on that substation",
                        "timestamp_s": None,
                    }
                ],
            },
            "claims": [
                claim(
                    "The chair said the board would not approve another campus on that substation.",
                    URL_HEAR,
                    "not going to approve another campus",
                    "Board minutes",
                )
            ],
        },
    }


SUPPORTED = {"verdict": {"verdict": "supported", "note": "The page says so."}}


def settings(tmp_path: Path, **over: Any) -> Settings:
    kw: dict[str, Any] = {
        "brief_source": "agent",
        "llm_provider": "fake",
        "data_dir": str(tmp_path / "briefs"),
        # Never serve a local web build from the test app.
        "web_dist": str(tmp_path / "no-dist"),
    }
    kw.update(over)
    return Settings(_env_file=None, **kw)


def service(
    tmp_path: Path,
    *,
    draft_responses: dict[str, Any] | None = None,
    verify_responses: dict[str, Any] | None = None,
    pages: dict[str, str] | None = None,
    geo: GeocodeResult | None = GEO,
    **over: Any,
) -> BriefService:
    s = settings(tmp_path, **over)
    return BriefService(
        settings=s,
        geocoder=FakeGeocoder(geo),
        draft_provider=KeyedFakeProvider(drafts() if draft_responses is None else draft_responses),
        verify_provider=KeyedFakeProvider(
            SUPPORTED if verify_responses is None else verify_responses
        ),
        fetcher=FakeFetcher(PAGES if pages is None else pages),
        cache=BriefCache(s.data_path),
    )
