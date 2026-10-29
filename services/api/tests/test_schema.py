from typing import Any

import pytest

from app.brief import fixtures
from app.geocode import brief_id_for, display_from, normalise
from app.schema import SECTION_IDS, draft_schemas, validate_brief, validate_draft
from tests import fakes


@pytest.mark.parametrize("key", ["ashburn", "boise", "kenosha", "rural_sd", "tucson"])
def test_fixtures_match_schema(key: str) -> None:
    validate_brief(fixtures.by_key(key))


def _walk(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        if "properties" in node:
            assert node.get("additionalProperties") is False, path
            assert set(node["required"]) == set(node["properties"]), path
        for k in ("format", "minimum", "maximum", "minItems", "maxItems", "pattern"):
            assert k not in node, f"{path}: {k}"
        for k, v in node.items():
            _walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("sid", SECTION_IDS)
def test_strict_schemas_are_strict_shaped(sid: str) -> None:
    _, strict = draft_schemas(sid)
    _walk(strict)
    assert "$ref" not in str(strict)


@pytest.mark.parametrize("sid", SECTION_IDS)
def test_scripted_drafts_validate_after_pruning(sid: str) -> None:
    pruned = validate_draft(sid, fakes.drafts()[f"draft_{sid}"])
    # Optional nulls are pruned, nullable-by-contract keys stay.
    if sid == "on_your_grid":
        assert "lat" not in pruned["facilities"][1]
        assert pruned["facilities"][0]["codename"] is None


def test_normalise_and_id() -> None:
    a = brief_id_for("21715 Filigree Ct, Ashburn, VA, 20147")
    b = brief_id_for("21715  FILIGREE CT  ASHBURN VA 20147")
    assert a == b and len(a) == 16
    assert normalise("A-B, c.") == "a b c"
    # Pinned: a US id never changes, or every share link and cached brief breaks.
    assert brief_id_for("21715 FILIGREE CT, ASHBURN, VA, 20147") == "4fb253585fde1c93"
    assert brief_id_for("zip:20147") == "59605c4e69c5d94c"
    assert brief_id_for(fakes.GEO.matched, "US") == brief_id_for(fakes.GEO.matched)
    assert brief_id_for(fakes.GEO.matched, "us") == brief_id_for(fakes.GEO.matched)
    assert brief_id_for(fakes.GEO.matched, "IE") != brief_id_for(fakes.GEO.matched)


def test_geocode_result_us_aliases() -> None:
    g = fakes.GEO
    assert g.country == "US"
    assert g.state == g.region_code == "VA" and g.zip == g.postal_code == "20147"


def test_display_strips_house_number() -> None:
    assert (
        display_from("21715 FILIGREE CT, ASHBURN, VA, 20147", "VA", "20147")
        == "Filigree Ct, Ashburn, VA 20147"
    )


def test_fixture_resolution() -> None:
    assert fixtures.resolve_address("somewhere in ashburn") == "ashburn"
    assert fixtures.resolve_address("53158") == "kenosha"
    assert fixtures.resolve_address("nowhere") is None
