"""POST /api/scenario needs no sign-in, only a same-site POST when the gate
is on, and stops at the daily soft cap; GET reads any engine's scenario; the
scenario card and the /what-if/ Open Graph tags read the same cache. The
interpretation is behind the gate: signed in, charged once per scenario,
streamed as NDJSON, free once made."""

import asyncio
import io
import json

from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import create_app
from tests import fakes, scenario_fakes

HDR = {"x-requested-with": "grid"}
SECRET = "s" * 40
BODY = {"zip": "20147", "mw": 300, "cooling": "evaporative"}


def gated_app(tmp_path, draft=None, **over):
    svc = fakes.service(
        tmp_path, auth_provider="fake", session_secret=SECRET, cookie_secure=False, **over
    )
    scenarios = scenario_fakes.service(
        tmp_path,
        auth_provider="fake",
        session_secret=SECRET,
        cookie_secure=False,
        draft=draft,
        **over,
    )
    return scenarios, create_app(svc, scenarios)


def client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_post_without_sign_in_succeeds(tmp_path) -> None:
    scenarios, app = gated_app(tmp_path)
    async with client(app) as c:
        r = await c.post("/api/scenario", json=BODY, headers=HDR)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["kind"] == "scenario" and s["inputs"] == {**BODY, "pin": None}
        # Nobody was charged: the usage store holds briefs only.
        assert await app.state.gate.usage.count_global_today() == 0

        got = await c.get(f"/api/scenario/{s['scenario_id']}")
        assert got.status_code == 200 and got.json()["scenario_id"] == s["scenario_id"]
        assert (await c.get("/api/scenario/0123456789abcdef")).status_code == 404
        assert (await c.get("/api/scenario/..")).status_code == 404

        # Cross-site POSTs are refused while the gate is on.
        r = await c.post("/api/scenario", json=BODY)
        assert r.status_code == 403 and r.json()["detail"] == "cross_site"


async def test_validation_and_unknown_zip(tmp_path) -> None:
    _, app = gated_app(tmp_path)
    async with client(app) as c:
        for bad in (
            {**BODY, "zip": "2014"},
            {**BODY, "zip": "20147-1234"},
            {**BODY, "zip": 20147},
            {**BODY, "mw": 5},
            {**BODY, "mw": 2001},
            {**BODY, "mw": 100.5},
            {**BODY, "cooling": "air"},
            {**BODY, "pin": {"lat": 120, "lon": 0}},
        ):
            r = await c.post("/api/scenario", json=bad, headers=HDR)
            assert r.status_code == 422, bad
    svc = fakes.service(tmp_path)
    app = create_app(svc, scenario_fakes.service(tmp_path, geo=None))
    async with client(app) as c:
        r = await c.post("/api/scenario", json=BODY)
        assert r.status_code == 404 and r.json()["detail"] == "zip_not_found"


async def test_global_soft_cap(tmp_path) -> None:
    svc = fakes.service(tmp_path)
    app = create_app(svc, scenario_fakes.service(tmp_path, scenario_global_day=1))
    async with client(app) as c:
        assert (await c.post("/api/scenario", json=BODY)).status_code == 200
        # The same scenario is cached: free.
        assert (await c.post("/api/scenario", json=BODY)).status_code == 200
        r = await c.post("/api/scenario", json={**BODY, "mw": 100})
        assert r.status_code == 429 and r.json()["detail"] == "quota_exceeded_today"


async def test_scenario_card_and_og(tmp_path) -> None:
    index = tmp_path / "dist" / "index.html"
    index.parent.mkdir()
    index.write_text("<html><head><!--og--></head><body></body></html>", encoding="utf-8")
    over = {"public_base_url": "https://grid.example", "web_dist": str(index.parent)}
    svc = fakes.service(tmp_path, **over)
    app = create_app(svc, scenario_fakes.service(tmp_path, **over))
    async with client(app) as c:
        sid = (await c.post("/api/scenario", json=BODY)).json()["scenario_id"]

        r = await c.get(f"/api/scenario-card/{sid}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
        assert list((tmp_path / "cards" / "scenario").glob(f"{sid}.*.png"))

        info = (await c.get(f"/api/scenario-card/{sid}.json")).json()
        assert info["kind"] == "scenario" and info["id"] == sid
        assert info["url"] == f"https://grid.example/what-if/{sid}"
        assert info["image_url"] == f"https://grid.example/api/scenario-card/{sid}.png"
        assert info["spec"]["hypothetical"] is True
        assert info["spec"]["disclosure"].startswith("Hypothetical what-if")
        assert info["share_text"].endswith(f"modelled from cited figures. {info['url']}")

        missing = await c.get("/api/scenario-card/0123456789abcdef.png")
        assert missing.status_code == 404 and missing.json()["detail"] == "scenario_not_found"
        assert (await c.get("/api/scenario-card/XYZ.json")).status_code == 422

        page = (await c.get(f"/what-if/{sid}")).text
        assert f'content="https://grid.example/api/scenario-card/{sid}.png"' in page
        assert 'content="article"' in page and "what if 300 MW" in page
        # An unknown scenario gets the site defaults.
        other = (await c.get("/what-if/0123456789abcdef")).text
        assert "og:image" not in other and 'content="website"' in other


async def sign_in(c: AsyncClient, email: str = "a@example.com") -> None:
    r = await c.post("/api/auth/google", json={"credential": f"fake:{email}:{email}"}, headers=HDR)
    assert r.status_code == 200, r.text


def events(r) -> list[dict]:
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


async def test_interpret_needs_sign_in_and_charges_once(tmp_path) -> None:
    scenarios, app = gated_app(tmp_path, draft=scenario_fakes.interpretation())
    usage = app.state.gate.usage
    async with client(app) as c:
        sid = (await c.post("/api/scenario", json=BODY, headers=HDR)).json()["scenario_id"]
        url = f"/api/scenario/{sid}/interpret"

        r = await c.post(url, headers=HDR)
        assert r.status_code == 401 and r.json()["detail"] == "sign_in_required"
        assert scenarios.draft_provider.calls == []
        assert (await c.post(url)).status_code == 403  # cross-site

        await sign_in(c)
        r = await c.post(url, headers=HDR)
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
        ev = events(r)
        assert [e["stage"] for e in ev] == [
            "drafting",
            "verifying",
            "verifying",
            "verifying",
            "done",
        ]
        assert ev[1] == {"stage": "verifying", "verified": 0, "claims": 2}
        interp = ev[-1]["scenario"]["interpretation"]
        assert interp["status"] == "reported" and interp["text"]
        assert scenarios.cache.get(sid)["interpretation"] == interp
        assert await usage.count_global_today() == 1
        assert (await c.get("/api/auth/me")).json()["remaining"] == 4
        # The usage row names the scenario, never the ZIP.
        assert "20147" not in repr(vars(usage))

        # Again: done at once, nothing drafted, nothing charged; free to anyone.
        calls = len(scenarios.draft_provider.calls)
        r = await c.post(url, headers=HDR)
        assert [e["stage"] for e in events(r)] == ["done"]
        async with client(app) as anon:
            r = await anon.post(url, headers=HDR)
            assert r.status_code == 200 and [e["stage"] for e in events(r)] == ["done"]
        assert len(scenarios.draft_provider.calls) == calls
        assert await usage.count_global_today() == 1

        # The scenario as read back carries the paragraph.
        got = (await c.get(f"/api/scenario/{sid}")).json()
        assert got["interpretation"] == interp


async def test_interpret_unknown_and_malformed_ids(tmp_path) -> None:
    _, app = gated_app(tmp_path, draft=scenario_fakes.interpretation())
    async with client(app) as c:
        await sign_in(c)
        r = await c.post("/api/scenario/0123456789abcdef/interpret", headers=HDR)
        assert r.status_code == 404 and r.json()["detail"] == "not_found"
        for bad in ("XYZ", "0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0"):
            r = await c.post(f"/api/scenario/{bad}/interpret", headers=HDR)
            assert r.status_code == 422, bad
        assert (await c.post("/api/scenario/../interpret", headers=HDR)).status_code == 404
        assert await app.state.gate.usage.count_global_today() == 0


async def test_interpret_without_a_drafting_model_is_503(tmp_path) -> None:
    _, app = gated_app(tmp_path)
    async with client(app) as c:
        sid = (await c.post("/api/scenario", json=BODY, headers=HDR)).json()["scenario_id"]
        await sign_in(c)
        r = await c.post(f"/api/scenario/{sid}/interpret", headers=HDR)
        assert r.status_code == 503 and r.json()["detail"] == "interpretation_unavailable"
        assert await app.state.gate.usage.count_global_today() == 0


async def test_interpret_failure_is_a_final_error_line(tmp_path) -> None:
    bad = scenario_fakes.interpretation(summary="Hypothetical: 123,456 homes. Two. Three.")
    scenarios, app = gated_app(tmp_path, draft=bad)
    async with client(app) as c:
        sid = (await c.post("/api/scenario", json=BODY, headers=HDR)).json()["scenario_id"]
        await sign_in(c)
        ev = events(await c.post(f"/api/scenario/{sid}/interpret", headers=HDR))
        assert ev[0] == {"stage": "drafting"}
        assert ev[-1]["stage"] == "error" and ev[-1]["status"] == 502
        assert ev[-1]["detail"] == "drafting_unavailable" and ev[-1]["reason"]
        assert scenarios.cache.get(sid)["interpretation"] is None
        # Nothing stored, nothing charged: a retry is not a second run's cost.
        assert await app.state.gate.usage.count_global_today() == 0
        assert (await c.get("/api/auth/me")).json()["remaining"] == 5


async def test_two_first_requests_are_charged_once(tmp_path) -> None:
    scenarios, app = gated_app(tmp_path, draft=scenario_fakes.interpretation())
    usage = app.state.gate.usage
    count = usage.count_global_today

    async def slow_count() -> int:
        await asyncio.sleep(0.01)  # a table round trip: lets the other request in
        return await count()

    usage.count_global_today = slow_count
    async with client(app) as c:
        sid = (await c.post("/api/scenario", json=BODY, headers=HDR)).json()["scenario_id"]
        await sign_in(c)
        url = f"/api/scenario/{sid}/interpret"
        a, b = await asyncio.gather(c.post(url, headers=HDR), c.post(url, headers=HDR))
        assert events(a)[-1]["stage"] == "done" and events(b)[-1]["stage"] == "done"
        assert len(scenarios.draft_provider.calls) == 1
        assert await count() == 1


async def test_interpret_with_the_gate_off_needs_no_sign_in(tmp_path) -> None:
    svc = fakes.service(tmp_path)
    scenarios = scenario_fakes.service(tmp_path, draft=scenario_fakes.interpretation())
    app = create_app(svc, scenarios)
    async with client(app) as c:
        sid = (await c.post("/api/scenario", json=BODY)).json()["scenario_id"]
        ev = events(await c.post(f"/api/scenario/{sid}/interpret"))
        assert ev[-1]["stage"] == "done"
        assert ev[-1]["scenario"]["interpretation"]["status"] == "reported"
