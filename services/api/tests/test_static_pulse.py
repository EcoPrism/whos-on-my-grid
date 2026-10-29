"""The built web app is served by the API when its dist exists, with the SPA
fallback behind every /api route; and /api/pulse is measured and free."""

from httpx import ASGITransport, AsyncClient

from app.ground import Ground
from app.ground.facilities import FakeFacilityDatabase
from app.main import create_app
from app.pulse import equivalences
from tests import fakes


def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>grid</title>", encoding="utf-8")
    (d / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (d / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return d


async def test_spa_fallback_and_assets(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path, web_dist=str(dist(tmp_path))))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for path in ("/", "/b/0123456789abcdef", "/about"):
            r = await c.get(path)
            assert r.status_code == 200 and "<title>grid</title>" in r.text, path
            assert r.headers["cache-control"] == "no-cache"
        r = await c.get("/assets/app-abc123.js")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        r = await c.get("/favicon.svg")
        assert r.status_code == 200 and r.text == "<svg/>"
        # API paths never fall back to the page.
        r = await c.get("/api/nope")
        assert r.status_code == 404 and r.json()["detail"] == "not_found"
        assert (await c.get("/api/health")).json()["ok"] is True


async def test_no_dist_no_mount(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path, web_dist=str(tmp_path / "missing")))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/about")).status_code == 404


def test_equivalences_are_cited_arithmetic() -> None:
    lines = equivalences()
    assert [line["id"] for line in lines] == ["homes_per_100mw", "fields_per_million_sq_ft"]
    for line in lines:
        assert line["source_url"].startswith("https://") and line["quote"] and line["basis"]
    # 100 MW × 8,760 h ÷ 10,791 kWh = 81,179 homes, shown to the nearest thousand.
    assert "about 81,000 average US homes" in lines[0]["text"]
    assert "23 acres" in lines[1]["text"] and "17 football fields" in lines[1]["text"]


async def test_pulse_full_mode_and_fixtures(tmp_path) -> None:
    svc = fakes.service(tmp_path, brief_source="full")
    svc.ground = Ground(facilities=FakeFacilityDatabase([]))
    app = create_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = (await c.get("/api/pulse")).json()
        assert body["peeringdb"]["total"] == 2 and body["peeringdb"]["added"] == 1
        assert len(body["equivalences"]) == 2
    app = create_app(fakes.service(tmp_path, brief_source="fixtures"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/pulse")).json() == {"peeringdb": None, "equivalences": []}
