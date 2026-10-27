import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests import fakes


@pytest.fixture
async def fixtures_client(tmp_path):
    app = create_app(fakes.service(tmp_path, brief_source="fixtures"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def agent_client(tmp_path):
    svc = fakes.service(tmp_path)
    app = create_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.service = svc  # type: ignore[attr-defined]
        yield c


async def test_health_fixtures(fixtures_client) -> None:
    r = await fixtures_client.get("/api/health")
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "fixtures"
    assert {e["key"] for e in body["examples"]} == {
        "ashburn",
        "boise",
        "kenosha",
        "rural_sd",
        "tucson",
    }


async def test_fixtures_by_key_id_and_address(fixtures_client) -> None:
    by_key = await fixtures_client.get("/api/brief/ashburn")
    assert by_key.status_code == 200
    by_id = await fixtures_client.get(f"/api/brief/{by_key.json()['brief_id']}")
    assert by_id.json() == by_key.json()
    posted = await fixtures_client.post("/api/brief", json={"address": "Filigree Ct, Ashburn"})
    assert posted.json() == by_key.json()
    miss = await fixtures_client.post("/api/brief", json={"address": "nowhere at all"})
    assert miss.status_code == 404 and miss.json()["detail"] == "fixture_not_matched"
    assert (await fixtures_client.get("/api/brief/nope")).status_code == 404


async def test_agent_post_then_get(agent_client) -> None:
    health = await agent_client.get("/api/health")
    assert health.json()["mode"] == "agent" and health.json()["examples"] == []
    r = await agent_client.post("/api/brief", json={"address": "21715 Filigree Ct, Ashburn, VA"})
    assert r.status_code == 200, r.text
    brief = r.json()
    again = await agent_client.get(f"/api/brief/{brief['brief_id']}")
    assert again.json() == brief
    calls = len(agent_client.service.draft_provider.calls)
    r2 = await agent_client.post("/api/brief", json={"address": "21715 Filigree Ct, Ashburn, VA"})
    assert r2.json() == brief and len(agent_client.service.draft_provider.calls) == calls
    assert (await agent_client.get("/api/brief/0000000000000000")).status_code == 404
    assert (await agent_client.get("/api/brief/../../etc")).status_code in (404, 422)


async def test_agent_address_not_found(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path, geo=None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/brief", json={"address": "asdfgh qwerty"})
    assert r.status_code == 422 and r.json()["detail"] == "address_not_found"


async def test_agent_drafting_unavailable(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path, draft_responses={}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/brief", json={"address": "x y z"})
    assert r.status_code == 502


def test_agent_mode_requires_keys(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="GRID_OPENAI_API_KEY"):
        create_app(fakes.service(tmp_path, llm_provider="openai"))
