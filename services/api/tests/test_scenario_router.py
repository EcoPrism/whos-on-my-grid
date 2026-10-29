"""POST /api/scenario needs no sign-in, only a same-site POST when the gate
is on, and stops at the daily soft cap; GET reads any engine's scenario; the
scenario card and the /what-if/ Open Graph tags read the same cache."""

import io

from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import create_app
from tests import fakes, scenario_fakes

HDR = {"x-requested-with": "grid"}
SECRET = "s" * 40
BODY = {"zip": "20147", "mw": 300, "cooling": "evaporative"}


def gated_app(tmp_path, **over):
    svc = fakes.service(
        tmp_path, auth_provider="fake", session_secret=SECRET, cookie_secure=False, **over
    )
    scenarios = scenario_fakes.service(
        tmp_path, auth_provider="fake", session_secret=SECRET, cookie_secure=False, **over
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
