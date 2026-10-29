"""The sign-in gate guards only new briefs. Cached briefs, brief links and
test-set addresses are free; a signed-in user has a daily quota; the global
cap holds for everyone. Fake verifier, memory usage store, no network."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests import fakes

HDR = {"x-requested-with": "grid"}
ADDR = "21715 Filigree Ct, Ashburn, VA"
TEST_SET_ADDR = "Filigree Ct, Ashburn, VA 20147"  # first row of eval/addresses.json
SECRET = "s" * 40


def gated(tmp_path, **over):
    svc = fakes.service(
        tmp_path, auth_provider="fake", session_secret=SECRET, cookie_secure=False, **over
    )
    return svc, create_app(svc)


@pytest.fixture
async def client(tmp_path):
    svc, app = gated(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.service = svc  # type: ignore[attr-defined]
        c.app = app  # type: ignore[attr-defined]
        yield c


async def sign_in(c: AsyncClient, email: str = "a@example.com") -> dict:
    r = await c.post("/api/auth/google", json={"credential": f"fake:{email}:{email}"}, headers=HDR)
    assert r.status_code == 200, r.text
    return r.json()


async def test_health_reports_the_gate(client) -> None:
    h = (await client.get("/api/health")).json()
    assert h["auth"] == "fake" and h["user"] is None and h["google_client_id"] is None
    assert h["quota_per_user_day"] == 5


async def test_new_brief_needs_sign_in_and_spends_nothing(client) -> None:
    r = await client.post("/api/brief", json={"address": ADDR}, headers=HDR)
    assert r.status_code == 401 and r.json()["detail"] == "sign_in_required"
    r = await client.post("/api/brief/stream", json={"address": ADDR}, headers=HDR)
    assert r.status_code == 401
    assert client.service.draft_provider.calls == []


async def test_cross_site_post_is_refused_when_gated(client) -> None:
    r = await client.post("/api/brief", json={"address": ADDR})
    assert r.status_code == 403 and r.json()["detail"] == "cross_site"
    r = await client.post("/api/auth/google", json={"credential": "fake:x:x@example.com"})
    assert r.status_code == 403


async def test_bad_credential(client) -> None:
    r = await client.post("/api/auth/google", json={"credential": "not-a-token"}, headers=HDR)
    assert r.status_code == 401 and r.json()["detail"] == "invalid_credential"
    assert (await client.get("/api/auth/me")).json() is None


async def test_sign_in_generate_cache_and_quota(tmp_path) -> None:
    svc, app = gated(tmp_path, quota_per_user_day=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        who = await sign_in(c)
        assert who == {"email": "a@example.com", "remaining": 1}
        assert c.cookies.get("grid_session")
        assert (await c.get("/api/auth/me")).json()["email"] == "a@example.com"
        assert (await c.get("/api/health")).json()["user"]["remaining"] == 1

        r = await c.post("/api/brief", json={"address": ADDR}, headers=HDR)
        assert r.status_code == 200, r.text
        brief = r.json()
        assert (await c.get("/api/auth/me")).json()["remaining"] == 0
        assert await app.state.gate.usage.count_global_today() == 1

        # The same address again is a cache hit: free, no sign-in needed either.
        r = await c.post("/api/brief", json={"address": ADDR}, headers=HDR)
        assert r.status_code == 200 and r.json() == brief
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
            assert (
                await anon.post("/api/brief", json={"address": ADDR}, headers=HDR)
            ).json() == brief
            assert (await anon.get(f"/api/brief/{brief['brief_id']}")).status_code == 200

        # A new brief with the quota spent is refused before any model call.
        svc.cache.path(brief["brief_id"]).unlink()
        calls = len(svc.draft_provider.calls)
        r = await c.post("/api/brief", json={"address": ADDR}, headers=HDR)
        assert r.status_code == 429 and r.json()["detail"] == "quota_exceeded_user"
        assert len(svc.draft_provider.calls) == calls

        # Sign out: no user, and a new brief needs sign-in again.
        assert (await c.post("/api/auth/logout", headers=HDR)).status_code == 200
        assert (await c.get("/api/auth/me")).json() is None
        r = await c.post("/api/brief", json={"address": ADDR}, headers=HDR)
        assert r.status_code == 401


async def test_test_set_address_runs_without_sign_in(client) -> None:
    r = await client.post("/api/brief", json={"address": TEST_SET_ADDR}, headers=HDR)
    assert r.status_code == 200, r.text
    assert await client.app.state.gate.usage.count_global_today() == 1


async def test_global_cap_holds_for_everyone(tmp_path) -> None:
    _, app = gated(tmp_path, quota_global_day=0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await sign_in(c)
        for addr in (ADDR, TEST_SET_ADDR):
            r = await c.post("/api/brief", json={"address": addr}, headers=HDR)
            assert r.status_code == 429 and r.json()["detail"] == "quota_exceeded_today"


async def test_gate_off_has_no_auth_surface(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/auth/me")).status_code == 404
        h = (await c.get("/api/health")).json()
        assert h["auth"] == "off" and h["user"] is None
        # No X-Requested-With needed, no sign-in needed.
        assert (await c.post("/api/brief", json={"address": ADDR})).status_code == 200


def test_half_configured_gate_fails_fast(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="GRID_SESSION_SECRET"):
        create_app(fakes.service(tmp_path, auth_provider="fake", session_secret="short"))
    with pytest.raises(RuntimeError, match="GRID_GOOGLE_CLIENT_ID"):
        create_app(fakes.service(tmp_path, auth_provider="google", session_secret=SECRET))
    with pytest.raises(RuntimeError, match="GRID_STORAGE_ACCOUNT"):
        create_app(fakes.service(tmp_path, usage_store="table"))
    with pytest.raises(RuntimeError, match="GRID_AUTH_PROVIDER"):
        create_app(fakes.service(tmp_path, auth_provider="maybe"))
