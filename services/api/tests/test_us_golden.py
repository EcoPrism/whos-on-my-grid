"""US byte-identity: what the engine wrote for a US address at b02e7d1 (step 5),
before Ireland. Each case below is computed here and its SHA-256 compared with
the digest recorded from a git worktree at that commit (tests/us_golden.py).
Nothing is printed: a failing case names itself and the two digests.

A case reads only what a US brief, prompt, card or endpoint showed at the
baseline. New keys added since (health `regions[]` fields, `examples[].currency`,
pulse `peeringdb.countries`) are projected away, so adding a field for another
region never breaks a case, but changing a US byte does.

To re-record (only for a deliberate US change, said so in the build log): run
the cases at the new baseline and replace the digests in tests/us_golden.py."""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from tests import fakes

Case = Callable[[Path], Awaitable[Any]]

ADDR = "21715 Filigree Ct, Ashburn, VA"
FIXED_NOW = "2026-01-01T00:00:00Z"
PUBLIC_BASE = "https://whoisonmygrid.com"
US_FIXTURES = ("ashburn", "boise", "kenosha", "rural_sd", "tucson")

# /api/health keys at the baseline; regions[] rows held only id and label,
# examples[] rows these four keys.
HEALTH_KEYS = (
    "ok",
    "mode",
    "region",
    "regions",
    "examples",
    "test_addresses",
    "auth",
    "google_client_id",
    "user",
    "quota_per_user_day",
)
HEALTH_REGION_KEYS = ("id", "label")
EXAMPLE_KEYS = ("key", "brief_id", "display", "ai_rent_usd_per_month")
PEERINGDB_KEYS = ("total", "added", "days", "fetched_at", "source_url", "source_title")

_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

INDEX_HTML = (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    '<meta charset="UTF-8" />\n'
    '<meta name="description" content="Type any US address. What is on my grid, what is '
    'coming, and what has it done to my bill." />\n'
    '<title>Who\'s On My Grid</title>\n<!--og-->\n</head>\n<body><div id="root"></div></body>\n'
    "</html>\n"
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _stable(brief: dict[str, Any]) -> Any:
    """The brief without what changes per run: the engine fingerprint (a hash of
    the code itself) and the generation time, wherever it is written."""
    doc = {k: v for k, v in brief.items() if k != "engine"}
    ts = str(brief.get("generated_at") or "")
    text = canonical(doc)
    if ts:
        text = text.replace(ts, "<ts>").replace(ts[:10], "<date>")
    return json.loads(_TS.sub("<ts>", text))


def _calls(provider: Any, ts: str) -> Any:
    """Every draft request the service made, by schema name: the prompts as sent."""
    text = canonical(sorted(provider.calls, key=lambda c: (c[0], canonical(c[1]))))
    if ts:
        text = text.replace(ts, "<ts>").replace(ts[:10], "<date>")
    return json.loads(text)


def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- the inputs, from the tree's own full-mode tests ----------------------------


def _full(**over: Any) -> Any:
    from tests.test_full_mode import ground

    return ground(**over)


def _step4_ground() -> Any:
    from app.ground import FakeHearingIndex, FakeImageryIndex
    from tests.test_step4_full_mode import DECISION, HEARING, IMAGERY, TRANSCRIPT

    return _full(
        imagery=FakeImageryIndex(IMAGERY),
        hearings=FakeHearingIndex(HEARING, [DECISION], TRANSCRIPT),
    )


async def _truths() -> dict[str, Any]:
    from app.ground import FakeHearingIndex, FakeImageryIndex, gather_ground

    return {
        "none": None,
        "full": await gather_ground(fakes.GEO, _full()),
        "step4": await gather_ground(fakes.GEO, _step4_ground()),
        "outside": await gather_ground(
            fakes.GEO,
            _full(imagery=FakeImageryIndex(None), hearings=FakeHearingIndex(None)),
        ),
    }


async def _brief(svc: Any, address: str = ADDR) -> dict[str, Any]:
    brief = await svc.brief_for_address(address)
    return {
        "brief": _stable(brief),
        "calls": _calls(svc.draft_provider, str(brief.get("generated_at") or "")),
    }


# --- cases -----------------------------------------------------------------------


async def case_system_prompts(_: Path) -> Any:
    from app.brief import prompts

    return {
        "system": prompts.system_prompt(FIXED_NOW),
        "house_system": prompts.house_system_prompt(FIXED_NOW),
        "verifier_system": prompts.verifier_system_prompt(),
    }


async def case_section_prompts(_: Path) -> Any:
    from app.brief import prompts
    from app.schema import SECTION_IDS

    truths = await _truths()
    return {
        name: {sid: prompts.section_prompt(sid, fakes.GEO, truth) for sid in SECTION_IDS}
        for name, truth in truths.items()
    }


async def case_house_prompts(_: Path) -> Any:
    from app.brief import prompts
    from app.schema import SECTION_IDS

    d = fakes.drafts()
    summaries = {sid: d[f"draft_{sid}"]["summary"] for sid in SECTION_IDS}
    truths = await _truths()
    return {
        "agent": prompts.house_prompt(fakes.GEO, summaries),
        "agent_empty": prompts.house_prompt(fakes.GEO, {}),
        **{name: prompts.house_prompt(fakes.GEO, {}, t) for name, t in truths.items() if t},
    }


async def case_draft_schemas(_: Path) -> Any:
    from app import schema

    return {
        "house_draft": schema.HOUSE_DRAFT,
        "house_schemas": list(schema.house_schemas()),
        "sections": {sid: list(schema.draft_schemas(sid)) for sid in schema.SECTION_IDS},
    }


async def case_brief_agent(tmp_path: Path) -> Any:
    return await _brief(fakes.service(tmp_path))


async def case_brief_full(tmp_path: Path) -> Any:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = _full()
    return await _brief(svc)


async def case_brief_full_variants(tmp_path: Path) -> Any:
    from app.ground import FakeFacilityDatabase, FakePrices, FakeUtility
    from tests.test_full_mode import BEYOND

    out: dict[str, Any] = {}
    variants = {
        "beyond": {"facilities": FakeFacilityDatabase([], beyond=BEYOND)},
        "empty": {"facilities": FakeFacilityDatabase([])},
        "failures": {
            "facilities": FakeFacilityDatabase(fail=True),
            "utility": FakeUtility(fail=True),
            "prices": FakePrices(fail=True),
        },
    }
    for name, over in variants.items():
        svc = fakes.service(tmp_path / name, brief_source="full")
        svc.ground = _full(**over)
        out[name] = await _brief(svc)
    drafts = fakes.drafts()
    del drafts["draft_on_your_grid"]
    del drafts["draft_your_bill"]
    svc = fakes.service(tmp_path / "dropped", brief_source="full", draft_responses=drafts)
    svc.ground = _full()
    out["dropped"] = await _brief(svc)
    return out


async def _tariff_brief(tmp_path: Path) -> dict[str, Any]:
    from app.ground import FakeTariffs, FakeUtilityPrices
    from tests.test_full_mode import TARIFF, UTILITY_PRICE

    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = _full(utility_prices=FakeUtilityPrices(UTILITY_PRICE), tariffs=FakeTariffs(TARIFF))
    return await svc.brief_for_address(ADDR)


async def case_brief_tariff(tmp_path: Path) -> Any:
    brief = await _tariff_brief(tmp_path)
    return {"brief": _stable(brief)}


async def case_utility_and_protection_claims(tmp_path: Path) -> Any:
    brief = _stable(await _tariff_brief(tmp_path))
    engine = [c for c in brief["claims"] if c["drafted_by"] == "engine"]
    utility = [c for c in engine if "electric-retail-service-territories" in c["source"]["url"]]
    protection = [c for c in engine if c["section"] == "protection"]
    assert utility and protection
    return {"utility": utility, "protection": protection}


async def case_brief_step4(tmp_path: Path) -> Any:
    from app.brief.fetch import TranscriptFetcher
    from tests.test_step4_full_mode import PAGES

    svc = fakes.service(tmp_path, brief_source="full", pages=PAGES)
    svc.ground = _step4_ground()
    svc.fetcher = TranscriptFetcher(svc.fetcher, svc.ground.hearings)
    step4 = await _brief(svc, "x")
    from app.ground import FakeHearingIndex, FakeImageryIndex

    svc = fakes.service(tmp_path / "outside", brief_source="full")
    svc.ground = _full(imagery=FakeImageryIndex(None), hearings=FakeHearingIndex(None))
    return {"step4": step4, "outside": await _brief(svc, "x")}


async def case_ground_notes(_: Path) -> Any:
    from app.ground import FakeFacilityDatabase, FakePrices, FakeUtility, gather_ground

    failing = await gather_ground(
        fakes.GEO,
        _full(
            facilities=FakeFacilityDatabase(fail=True),
            utility=FakeUtility(fail=True),
            prices=FakePrices(fail=True),
        ),
    )
    truths = await _truths()
    return {
        "failing": [failing.notes, failing.hearing_note],
        **{
            name: [t.notes, t.hearing_note, len(t.decisions)]
            for name, t in truths.items()
            if t is not None
        },
    }


async def case_pulse(tmp_path: Path) -> Any:
    from app.ground import FakeFacilityDatabase, Ground
    from app.main import create_app

    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = Ground(facilities=FakeFacilityDatabase([]))
    async with _client(create_app(svc)) as c:
        body = (await c.get("/api/pulse")).json()
        regional = (await c.get("/api/pulse?region=us")).json()
    assert body == regional
    if body.get("peeringdb") is not None:
        body["peeringdb"] = {k: body["peeringdb"][k] for k in PEERINGDB_KEYS}
    async with _client(create_app(fakes.service(tmp_path / "fx", brief_source="fixtures"))) as c:
        fixtures_body = (await c.get("/api/pulse")).json()
    return {"full": body, "fixtures": fixtures_body}


def _health(body: dict[str, Any]) -> dict[str, Any]:
    out = {k: body[k] for k in HEALTH_KEYS}
    out["regions"] = [{k: r[k] for k in HEALTH_REGION_KEYS} for r in body["regions"]]
    out["examples"] = [{k: e[k] for k in EXAMPLE_KEYS} for e in body["examples"]]
    return out


async def case_health(tmp_path: Path) -> Any:
    from app.main import create_app

    out: dict[str, Any] = {}
    for mode in ("fixtures", "agent"):
        async with _client(create_app(fakes.service(tmp_path / mode, brief_source=mode))) as c:
            out[mode] = _health((await c.get("/api/health")).json())
            out[f"{mode}_us"] = _health((await c.get("/api/health?region=us")).json())
    return out


async def case_cards(_: Path) -> Any:
    from app.brief import fixtures
    from app.card.spec import share_text, spec_from_brief

    out: dict[str, Any] = {}
    for key in US_FIXTURES:
        brief = fixtures.by_key(key)
        assert brief is not None, key
        spec = spec_from_brief(brief, public_base_url=PUBLIC_BASE)
        out[key] = {
            "spec": spec.as_json(),
            "share_text": share_text(spec, f"{PUBLIC_BASE}/b/{brief['brief_id']}"),
            "card": brief.get("card"),
            "brief_id": brief["brief_id"],
        }
    return out


async def case_assembled_cards(tmp_path: Path) -> Any:
    """The card spec and share text of freshly made US briefs (not fixtures)."""
    from app.card.spec import share_text, spec_from_brief

    out: dict[str, Any] = {}
    agent = await fakes.service(tmp_path / "agent").brief_for_address(ADDR)
    svc = fakes.service(tmp_path / "full", brief_source="full")
    svc.ground = _full()
    full = await svc.brief_for_address(ADDR)
    tariff = await _tariff_brief(tmp_path / "tariff")
    for name, brief in (("agent", agent), ("full", full), ("tariff", tariff)):
        stable = _stable(brief)
        spec = spec_from_brief(stable, public_base_url=PUBLIC_BASE)
        out[name] = {
            "spec": spec.as_json(),
            "share_text": share_text(spec, f"{PUBLIC_BASE}/b/{stable['brief_id']}"),
        }
    return out


async def case_static_meta(tmp_path: Path) -> Any:
    from app.brief import fixtures
    from app.main import create_app

    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    ashburn = fixtures.by_key("ashburn")
    assert ashburn is not None
    out: dict[str, Any] = {}
    for base in ("", PUBLIC_BASE):
        svc = fakes.service(
            tmp_path / f"s{len(base)}",
            brief_source="fixtures",
            web_dist=str(dist),
            public_base_url=base,
        )
        async with _client(create_app(svc)) as c:
            for path in ("/", f"/b/{ashburn['brief_id']}", "/b/0000000000000000", "/about"):
                r = await c.get(path)
                out[f"{base}{path}"] = [r.status_code, r.text]
    return out


CASES: dict[str, Case] = {
    "system_prompts": case_system_prompts,
    "section_prompts": case_section_prompts,
    "house_prompts": case_house_prompts,
    "draft_schemas": case_draft_schemas,
    "brief_agent": case_brief_agent,
    "brief_full": case_brief_full,
    "brief_full_variants": case_brief_full_variants,
    "brief_tariff": case_brief_tariff,
    "utility_and_protection_claims": case_utility_and_protection_claims,
    "brief_step4": case_brief_step4,
    "ground_notes": case_ground_notes,
    "pulse": case_pulse,
    "health": case_health,
    "cards": case_cards,
    "assembled_cards": case_assembled_cards,
    "static_meta": case_static_meta,
}


async def capture(tmp_path: Path) -> dict[str, str]:
    """Every case's digest; the recording script calls this in the baseline tree."""
    out: dict[str, str] = {}
    for name, case in CASES.items():
        out[name] = digest(await case(tmp_path / name))
    return out


@pytest.mark.parametrize("name", list(CASES))
async def test_us_output_matches_the_step5_baseline(tmp_path: Path, name: str) -> None:
    from tests.us_golden import GOLDEN

    got = digest(await CASES[name](tmp_path))
    assert got == GOLDEN[name], f"US output changed for {name}: {got} != {GOLDEN[name]}"


def test_every_case_has_a_golden() -> None:
    from tests.us_golden import GOLDEN

    assert set(GOLDEN) == set(CASES)
