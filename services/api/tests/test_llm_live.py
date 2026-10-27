"""Live canaries against the real endpoints. Deselected by default.

    uv run pytest -m live --run-live tests/test_llm_live.py

Each test skips without its key. They prove what the fakes cannot: that the
gateway alias honours strict JSON-schema output for a section draft, and that
the Baseten endpoint returns a verdict (with GRID_VERIFY_STRICT_JSON as set).
"""

import pytest

from app.brief.draft import DraftResult, draft_section
from app.brief.verify import VERDICTS
from app.config import get_settings
from app.llm import get_draft_provider, get_verify_provider
from app.llm.openai_provider import OpenAIProvider
from app.schema import VERDICT_SCHEMA
from tests import fakes

pytestmark = pytest.mark.live


@pytest.fixture
def live_settings():
    get_settings.cache_clear()
    s = get_settings()
    s.llm_provider = "openai"
    return s


async def test_draft_one_section_through_gateway(live_settings) -> None:
    if not live_settings.openai_api_key:
        pytest.skip("GRID_OPENAI_API_KEY not set")
    provider = get_draft_provider()
    assert isinstance(provider, OpenAIProvider)
    result = await draft_section(provider, "protection", fakes.GEO, "2026-10-27T12:00:00Z")
    assert isinstance(result, DraftResult), result
    assert result.summary and 0 <= result.confidence <= 1
    assert result.extra["tariff"]["large_load_tariff"] in {
        "in_force",
        "proposed",
        "none_found",
        "unknown",
    }


async def test_verdict_through_baseten(live_settings) -> None:
    if not live_settings.baseten_api_key:
        pytest.skip("GRID_BASETEN_API_KEY not set")
    provider = get_verify_provider()
    messages = [
        {"role": "system", "content": "You are a fact checker. Output only the JSON object."},
        {
            "role": "user",
            "content": "Claim: the order sets a 25 MW threshold.\nPage text: Customers with demand "
            "above 25 MW shall bear the incremental cost of transmission upgrades.",
        },
    ]
    result = await provider.complete_structured(messages, VERDICT_SCHEMA, "verdict")
    assert result["verdict"] in VERDICTS and isinstance(result["note"], str)
