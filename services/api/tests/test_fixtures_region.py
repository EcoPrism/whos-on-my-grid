"""Fixture briefs by region: the Irish fixture is matched only for Irish text,
the five US fixtures keep their keys and ids, and the Irish brief speaks in
km, euro and "data centre"."""

import json
import re

from app.brief import fixtures
from app.geocode import brief_id_for

US_IDS = {
    "ashburn": "3fb95348f1d4081e",
    "boise": "d33d5d7c58e50b16",
    "kenosha": "fbffd30aa062090e",
    "rural_sd": "f2afbbd87226c4c8",
    "tucson": "8bc089ffbae62dd2",
}
IE_ID = "ffefa78202dceea9"


def _ie() -> dict:
    b = fixtures.by_key("blanchardstown")
    assert b is not None
    return b


def test_irish_text_never_opens_a_us_brief() -> None:
    key = fixtures.resolve_address("County Dublin Avenue", country="IE")
    assert key not in US_IDS
    assert key == "blanchardstown"
    assert fixtures.resolve_address("Blanchardstown Centre, Dublin 15", country="IE") == (
        "blanchardstown"
    )


def test_us_text_never_opens_the_irish_brief() -> None:
    assert fixtures.resolve_address("Blanchardstown Centre, Dublin 15") != "blanchardstown"
    assert fixtures.resolve_address("21715 Filigree Ct, Ashburn, VA") == "ashburn"
    assert fixtures.resolve_address("W Idaho St, Boise, ID 83702") == "boise"


def test_us_keys_and_ids_unchanged() -> None:
    us = {k: b["brief_id"] for k, b in fixtures.all_fixtures().items() if k in US_IDS}
    assert us == US_IDS
    assert sorted(e["key"] for e in fixtures.examples()) == sorted(US_IDS)
    assert {e["currency"] for e in fixtures.examples()} == {"USD"}


def test_irish_fixture_id() -> None:
    b = _ie()
    assert b["brief_id"] == IE_ID
    assert brief_id_for(b["address"]["display"], "IE") == IE_ID
    assert fixtures.by_id(IE_ID) is b
    assert fixtures.country_of(b) == "IE"


def test_irish_examples() -> None:
    ex = fixtures.examples(country="IE")
    assert [e["key"] for e in ex] == ["blanchardstown"]
    assert ex[0]["currency"] == "EUR" and ex[0]["language"] == "en-IE"
    assert ex[0]["ai_rent_usd_per_month"] == 44.8  # (0.3871 - 0.2590) * 350, the engine's sum


def test_irish_fixture_speaks_metric_and_euro() -> None:
    text = json.dumps(_ie(), ensure_ascii=False)
    for leak in (r"\$", r"\bmiles?\b", r"\bacres?\b", r"\bZIP\b", r"\bstatewide\b", r"data center"):
        assert not re.search(leak, text, re.I), leak
    assert "8 km" in text and "€" in text and "data centre" in text


def test_irish_card_lines() -> None:
    lines = _ie()["card"]["lines"]
    assert any(re.match(r"^[+−-]€", ln) for ln in lines)
    assert "CRU data-centre connection policy in force; household bills not its stated aim" in lines
    assert all(len(ln) <= 80 for ln in lines)


def test_irish_rent_is_the_price_arithmetic() -> None:
    b = _ie()
    p = b["sections"]["your_bill"]["price"]
    assert (p["rate_now"], p["rate_then"], p["typical_household_kwh_month"]) == (
        0.3871,
        0.2590,
        350,
    )
    assert (p["as_of"], p["window_months"], p["trend_pct"]) == ("2026-06", 24, 49.5)
    assert b["headline"]["ai_rent_usd_per_month"] == round((0.3871 - 0.2590) * 350, 1)
