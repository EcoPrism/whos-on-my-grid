"""Scenario ids and the scenario cache: same inputs, same id; pins a few tens
of metres apart, same id; an engine change regenerates on request."""

import json

import pytest

from app.brief.cache import engine_fingerprint
from app.scenario.inputs import InputsInvalid, ScenarioInputs
from tests import scenario_fakes


def test_same_inputs_same_id() -> None:
    a = ScenarioInputs.create(zip="20147", mw=300, cooling="evaporative")
    b = ScenarioInputs.create(zip="20147", mw=300, cooling="evaporative")
    assert a.scenario_id() == b.scenario_id()
    assert len(a.scenario_id()) == 16
    others = [
        ScenarioInputs.create(zip="20148", mw=300, cooling="evaporative"),
        ScenarioInputs.create(zip="20147", mw=301, cooling="evaporative"),
        ScenarioInputs.create(zip="20147", mw=300, cooling="closed_loop"),
        ScenarioInputs.create(zip="20147", mw=300, cooling="evaporative", pin=(39.0, -77.0)),
    ]
    assert len({a.scenario_id(), *(o.scenario_id() for o in others)}) == 5


def test_pins_30m_apart_share_an_id() -> None:
    # 0.00027 degrees of latitude is about 30 m; both round to 39.016.
    a = ScenarioInputs.create(zip="20147", mw=100, cooling="evaporative", pin=(39.01562, -77.4588))
    b = ScenarioInputs.create(zip="20147", mw=100, cooling="evaporative", pin=(39.01589, -77.4589))
    assert a.pin == b.pin == (39.016, -77.459)
    assert a.scenario_id() == b.scenario_id()


@pytest.mark.parametrize(
    "kw",
    [
        {"zip": "2014", "mw": 100, "cooling": "evaporative"},
        {"zip": "20147", "mw": 5, "cooling": "evaporative"},
        {"zip": "20147", "mw": 2001, "cooling": "evaporative"},
        {"zip": "20147", "mw": 100, "cooling": "air"},
        {"zip": "20147", "mw": 100, "cooling": "evaporative", "pin": (91.0, 0.0)},
    ],
)
def test_inputs_out_of_range(kw) -> None:
    with pytest.raises(InputsInvalid):
        ScenarioInputs.create(**kw)


async def test_compute_caches_and_fingerprint_change_regenerates(tmp_path) -> None:
    svc = scenario_fakes.service(tmp_path)
    inputs = ScenarioInputs.create(zip="20147", mw=300, cooling="evaporative")
    first = await svc.compute(await svc.resolve(inputs))
    sid = inputs.scenario_id()
    assert first["scenario_id"] == sid and first["engine"] == engine_fingerprint()
    assert (tmp_path / "scenarios" / f"{sid}.json").exists()
    # Verified against the constants' pages, as briefs are.
    assert {c["verdict"] for c in first["claims"]} == {"supported"}
    assert "sources checked by Muse Spark Open" in first["card"]["disclosure"]

    again = await svc.resolve(inputs)
    assert again.cached is not None and again.cached["generated_at"] == first["generated_at"]

    # A scenario an older deploy made: same id, another engine.
    stale = dict(first, engine="000000000000", generated_at="2020-01-01T00:00:00Z")
    path = tmp_path / "scenarios" / f"{sid}.json"
    path.write_text(json.dumps(stale), encoding="utf-8")
    resolved = await svc.resolve(inputs)
    assert resolved.cached is None
    assert svc.cache.get(sid)["engine"] == "000000000000"  # links still open the old one
    fresh = await svc.compute(resolved)
    assert (
        fresh["engine"] == engine_fingerprint() and fresh["generated_at"] != stale["generated_at"]
    )


async def test_no_verifier_leaves_claims_unchecked(tmp_path) -> None:
    svc = scenario_fakes.service(tmp_path, verify=False)
    inputs = ScenarioInputs.create(zip="20147", mw=100, cooling="closed_loop")
    s = await svc.compute(await svc.resolve(inputs))
    assert {c["verdict"] for c in s["claims"]} == {"unchecked"}
    assert all(c["verifier_note"] for c in s["claims"])
    assert "sources not yet checked" in s["card"]["disclosure"]
