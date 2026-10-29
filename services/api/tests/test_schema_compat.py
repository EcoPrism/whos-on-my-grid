"""The brief contract after regions: every brief already written still reads,
and a US brief made today carries the region-neutral keys beside the old ones.

Cached briefs hold addresses, which are personal data. Nothing here may put
one in pytest output: params are named by brief id, failures list only key
paths and validator names, and no assertion compares a whole brief.
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.brief import fixtures
from app.config import REPO_ROOT
from app.main import create_app
from app.schema import SECTION_IDS, _brief_validator, _scenario_validator, draft_schemas
from tests import fakes, test_full_mode

FIXTURES_DIR = REPO_ROOT / "fixtures" / "briefs"
FIXTURE_IDS = {
    "ashburn": "3fb95348f1d4081e",
    "boise": "d33d5d7c58e50b16",
    "kenosha": "fbffd30aa062090e",
    "rural_sd": "f2afbbd87226c4c8",
    "tucson": "8bc089ffbae62dd2",
    # Ireland: brief_id_for("Blanchardstown, Fingal, Co. Dublin, D15", "IE").
    "blanchardstown": "ffefa78202dceea9",
}
US_FIXTURES = ("ashburn", "boise", "kenosha", "rural_sd", "tucson")
# Gitignored caches that exist on a developer's machine: checked when present.
CACHED_SETS = {
    "pre-step4": (REPO_ROOT / "data" / "briefs.pre-step4", "*.json"),
    "briefs": (REPO_ROOT / "data" / "briefs", "*.json"),
    "runs": (REPO_ROOT / "eval" / "runs", "**/*.json"),
}
SCENARIOS = REPO_ROOT / "data" / "scenarios"
US_LOCALE = {"country": "US", "currency": "USD", "units": "us", "language": "en-US"}
IE_LOCALE = {"country": "IE", "currency": "EUR", "units": "metric", "language": "en-IE"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _problems(validator: Any, doc: dict[str, Any]) -> list[str]:
    """Where and which rule, never the value: a jsonschema message quotes the
    instance, and an address instance would quote the address."""
    return sorted(
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.validator}"
        for e in validator.iter_errors(doc)
    )


def brief_problems(brief: dict[str, Any]) -> list[str]:
    return _problems(_brief_validator(), brief)


def _us_problems(brief: dict[str, Any]) -> list[str]:
    """What would stop an old brief reading as US, by key name only."""
    a = brief["address"]
    out = []
    state = a.get("state")
    if not (isinstance(state, str) and len(state) == 2 and state.isupper()):
        out.append("address.state")
    if not isinstance(a.get("zip"), str):
        out.append("address.zip")
    if "country" in a and a["country"] != "US":
        out.append("address.country")
    price = brief["sections"]["your_bill"].get("price")
    if price and price.get("currency") != "USD":
        out.append("price.currency")
    if brief.get("locale", US_LOCALE) != US_LOCALE:
        out.append("locale")
    return out


def _cached_params() -> list[Any]:
    params: list[Any] = []
    for name, (root, pattern) in CACHED_SETS.items():
        if not root.is_dir():
            params.append(pytest.param(name, None, id=f"{name}-absent", marks=pytest.mark.skip))
            continue
        for path in sorted(root.glob(pattern)):
            try:
                doc = _load(path)
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and "brief_id" in doc and "address" in doc:
                params.append(pytest.param(name, path, id=f"{name}-{doc['brief_id']}"))
    return params


def _scenario_params() -> list[Any]:
    if not SCENARIOS.is_dir():
        return [pytest.param(None, id="scenarios-absent", marks=pytest.mark.skip)]
    return [pytest.param(p, id=p.stem) for p in sorted(SCENARIOS.glob("*.json"))]


# --- briefs already written ----------------------------------------------------


def test_committed_fixtures_exist() -> None:
    assert sorted(p.stem for p in FIXTURES_DIR.glob("*.json")) == sorted(FIXTURE_IDS)


@pytest.mark.parametrize("key", sorted(FIXTURE_IDS))
def test_committed_fixture_validates(key: str) -> None:
    brief = _load(FIXTURES_DIR / f"{key}.json")
    assert brief_problems(brief) == []
    assert brief["brief_id"] == FIXTURE_IDS[key]
    if key not in US_FIXTURES:
        return  # a non-US fixture is checked below; the legacy shape is US-only
    assert _us_problems(brief) == []
    # The legacy shape: none of the new keys, so these stay the canaries.
    assert "locale" not in brief and "country" not in brief["address"]


def test_irish_fixture_is_irish() -> None:
    brief = _load(FIXTURES_DIR / "blanchardstown.json")
    a = brief["address"]
    assert brief["locale"] == IE_LOCALE
    assert (a["country"], a["region_code"], a["county"], a["postal_code"]) == (
        "IE",
        "IE-D",
        "Fingal",
        "D15",
    )
    assert "state" not in a and "zip" not in a
    price = brief["sections"]["your_bill"]["price"]
    assert price["currency"] == "EUR" and price["granularity"] == "semiannual"
    assert brief["sections"]["protection"]["tariff"]["kind"] == "connection_policy"
    assert brief["headline"]["percentile"] is None


@pytest.mark.parametrize("name,path", _cached_params())
def test_cached_brief_still_validates(name: str, path: Path) -> None:
    brief = _load(path)
    assert brief_problems(brief) == []
    assert _us_problems(brief) == []
    if name != "runs":
        # Share links fetch a brief by the file's name.
        assert path.stem == brief["brief_id"]


@pytest.mark.parametrize("path", _scenario_params())
def test_cached_scenario_still_validates(path: Path) -> None:
    assert _problems(_scenario_validator(), _load(path)) == []


async def test_fixture_ids_resolve(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path, brief_source="fixtures"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for key, brief_id in FIXTURE_IDS.items():
            assert fixtures.by_id(brief_id) is fixtures.by_key(key)
            r = await c.get(f"/api/brief/{brief_id}")
            assert r.status_code == 200 and r.json()["brief_id"] == brief_id


# --- the shape a region-neutral brief takes -------------------------------------


def _ashburn() -> dict[str, Any]:
    brief = fixtures.by_key("ashburn")
    assert brief is not None
    return copy.deepcopy(brief)


def _forward(brief: dict[str, Any]) -> dict[str, Any]:
    a = brief["address"]
    a.update(country="US", region_code=a["state"], postal_code=a["zip"])
    brief["locale"] = dict(US_LOCALE)
    brief["sections"]["your_bill"]["price"]["granularity"] = "monthly"
    return brief


def test_new_keys_validate() -> None:
    assert brief_problems(_forward(_ashburn())) == []


def test_new_trio_stands_without_state_and_zip() -> None:
    brief = _forward(_ashburn())
    del brief["address"]["state"], brief["address"]["zip"]
    assert brief_problems(brief) == []


def test_address_without_identity_is_invalid() -> None:
    brief = _forward(_ashburn())
    for k in ("state", "zip", "country", "region_code", "postal_code"):
        del brief["address"][k]
    assert "address: anyOf" in brief_problems(brief)


def test_half_filled_address_is_invalid() -> None:
    # A state with no zip, and none of the new trio: today's contract rejects it too.
    brief = _ashburn()
    del brief["address"]["zip"]
    assert "address: anyOf" in brief_problems(brief)
    # Nor does part of the trio rescue it.
    brief["address"].update(country="US", region_code="VA")
    assert "address: anyOf" in brief_problems(brief)


def test_unknown_units_are_invalid() -> None:
    brief = _forward(_ashburn())
    brief["locale"]["units"] = "imperial"
    assert brief_problems(brief) == ["locale/units: enum"]


def test_unknown_granularity_is_invalid() -> None:
    brief = _forward(_ashburn())
    brief["sections"]["your_bill"]["price"]["granularity"] = "weekly"
    assert brief_problems(brief) == ["sections/your_bill/price/granularity: enum"]


# --- what the models are asked to fill ---------------------------------------------

# sha256 of each section's (original, strict) draft schema as it was before the
# region keys: price.granularity is engine-owned and pruned, so prompts and the
# strict schemas the models receive are byte-for-byte what they were.
DRAFT_SCHEMA_SHA256 = {
    "on_your_grid": (
        "58bbbac5a5f7ff562429154d4c43d6915786413dd71ebbdeb1fa80d91f938eeb",
        "19fcbd9a98550d1a7724e08bbe13558cbc3829796696be56d7ece80b268918c2",
    ),
    "coming": (
        "58bbbac5a5f7ff562429154d4c43d6915786413dd71ebbdeb1fa80d91f938eeb",
        "19fcbd9a98550d1a7724e08bbe13558cbc3829796696be56d7ece80b268918c2",
    ),
    "your_bill": (
        "ac3d3cfe718a44b3523229844b754a1b8800235b2708f335075076ca54159480",
        "5ee0c9f3cfd10251728f4377c24837d1f43e92b773468d7a732182c6ce2bda87",
    ),
    "protection": (
        "7ecaabcdad443a7defa803ff442a7bcec4a8141c5427e60396cf7c28422bc6a3",
        "fa10d02f78fe0f896f0caaff6d66e7cb751b785e6e4d87035691736beb66981e",
    ),
    "hearing": (
        "ca3016a07bd7a7363712dbcc668985256b98bedf28e492905ab22c657e01469f",
        "119d71283d861bd031d7be06cb6fff57f70ba9070d7530cdf3d781476e5c9119",
    ),
}


def _sha(schema: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("section_id", SECTION_IDS)
def test_draft_schemas_unchanged(section_id: str) -> None:
    original, strict = draft_schemas(section_id)
    assert (_sha(original), _sha(strict)) == DRAFT_SCHEMA_SHA256[section_id]
    assert "granularity" not in json.dumps([original, strict])


# --- a US brief made today --------------------------------------------------------


def _new_keys(brief: dict[str, Any]) -> None:
    a = brief["address"]
    assert a["state"] == a["region_code"] == "VA"
    assert a["zip"] == a["postal_code"] == "20147"
    assert a["country"] == "US"
    assert brief["locale"] == US_LOCALE
    assert brief["brief_id"] == "4fb253585fde1c93"


async def test_assembled_full_brief_is_us(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = test_full_mode.ground()
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    assert brief_problems(brief) == []
    _new_keys(brief)
    price = brief["sections"]["your_bill"]["price"]
    assert price["currency"] == "USD"
    assert price["granularity"] in {"monthly", "annual"}


async def test_assembled_agent_brief_is_us(tmp_path) -> None:
    svc = fakes.service(tmp_path)
    brief = await svc.brief_for_address("21715 Filigree Ct, Ashburn, VA")
    assert brief["source_mode"] == "agent"
    assert brief_problems(brief) == []
    _new_keys(brief)
    # The model's price: no engine series behind it, so no granularity.
    price = brief["sections"]["your_bill"]["price"]
    assert price["currency"] == "USD" and "granularity" not in price
