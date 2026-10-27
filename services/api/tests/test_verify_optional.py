"""The verifier is optional. With no verify provider the service still starts,
nothing is fetched, and every claim is left `unchecked` with an honest note."""

from app.brief.fetch import FakeFetcher
from app.brief.verify import UNCHECKED_NOTE, verify_claims
from app.main import create_app
from tests import fakes


async def test_no_verifier_leaves_claims_unchecked_and_fetches_nothing() -> None:
    fetcher = FakeFetcher({fakes.URL_REG: "some page"})
    claims = [
        {
            "id": "c1",
            "text": "a",
            "source": {"url": fakes.URL_REG, "quote": "x"},
            "verdict": "unchecked",
        },
        {"id": "c2", "text": "b", "source": {"url": fakes.URL_GONE}, "verdict": "unchecked"},
    ]
    await verify_claims(
        None, fetcher, claims, concurrency=2, verified_by="m", now_iso="2026-10-27T00:00:00Z"
    )
    assert fetcher.calls == []
    for c in claims:
        assert c["verdict"] == "unchecked"
        assert c["verified_by"] is None
        assert c["verifier_note"] == UNCHECKED_NOTE


def test_agent_mode_starts_without_baseten_key(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path, llm_provider="openai", openai_api_key="gateway-key"))
    assert app.state.settings.baseten_api_key == ""


def test_card_footer_says_unchecked_without_verifier() -> None:
    from app.brief.assemble import assemble_brief

    drafts = fakes.drafts()
    on = assemble_brief(fakes.GEO, drafts, brief_id="0" * 16, now_iso="2026-10-27T00:00:00Z")
    off = assemble_brief(
        fakes.GEO, drafts, brief_id="0" * 16, now_iso="2026-10-27T00:00:00Z", verified=False
    )
    assert "checked by Muse Spark Open" in on["card"]["footer"]
    assert "not yet checked" in off["card"]["footer"]
