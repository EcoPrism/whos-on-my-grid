"""The share card: its spec mirrors ShareCard.tsx, the PNG is deterministic and
says it is AI-assisted in its metadata, and the routes check the id first."""

import io
import json
import struct
from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.brief import fixtures
from app.brief.assemble import assemble_brief
from app.card import CardCache, make_png
from app.card.provenance import IPTC_COMPOSITE_AI, with_c2pa
from app.card.render import CQW, H, W, fit_title, render_png
from app.card.spec import (
    _BILL_LINE,
    fmt_money,
    fmt_range,
    share_text,
    spec_from_brief,
    spec_from_scenario,
)
from app.config import REPO_ROOT
from app.main import create_app
from tests import fakes

BILL = _BILL_LINE
BILL_CASES = json.loads((REPO_ROOT / "schema" / "card_bill_cases.json").read_text("utf-8"))
SYMBOL = {"USD": "$", "EUR": "€"}


def _chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    out, i = [], 8
    while i < len(png):
        (n,) = struct.unpack(">I", png[i : i + 4])
        out.append((png[i + 4 : i + 8], png[i + 8 : i + 8 + n]))
        i += 12 + n
    return out


@pytest.mark.parametrize("key", sorted(fixtures.all_fixtures()))
def test_spec_from_brief_mirrors_share_card(key) -> None:
    brief = fixtures.by_key(key)
    spec = spec_from_brief(brief)
    card, headline = brief["card"], brief["headline"]
    assert spec.kind == "brief" and not spec.hypothetical
    assert spec.title == card["title"].removeprefix("Who's on my grid: ")
    if headline["ai_rent_usd_per_month"] is None:
        assert spec.big is None and spec.lines == tuple(card["lines"])
    else:
        lo, hi = headline["ai_rent_range_usd_per_month"]
        cur = SYMBOL[(brief.get("locale") or {}).get("currency", "USD")]
        assert spec.big == f"+{cur}{lo:.0f} to {cur}{hi:.0f}"
        assert spec.big_caption and spec.big_caption.endswith(("· modeled", "· modelled"))
        assert spec.lines == tuple(line for line in card["lines"] if not BILL.match(line))
    assert spec.footer == card["footer"]
    # Fixtures predate card.disclosure: it is made from the id and the date.
    assert spec.disclosure.startswith("AI-assisted brief.")
    assert f"/b/{brief['brief_id']} · 2026-10-27" in spec.disclosure


def test_bill_line_dropped_only_when_big_shows() -> None:
    brief = fixtures.by_key("ashburn")
    card = {**brief["card"], "lines": ["+$20/mo for a typical VA home vs 2 yrs ago", "15 nearby"]}
    assert spec_from_brief({**brief, "card": card}).lines == ("15 nearby",)
    headline = {**brief["headline"], "ai_rent_usd_per_month": None}
    spec = spec_from_brief({**brief, "card": card, "headline": headline})
    assert spec.big is None and len(spec.lines) == 2


@pytest.mark.parametrize("case", BILL_CASES["cases"], ids=lambda c: c["line"][:24])
def test_bill_line_cases(case) -> None:
    """The shared table (schema/card_bill_cases.json) that ShareCard.tsx's regex
    is checked against too."""
    assert bool(_BILL_LINE.match(case["line"])) is case["bill"]
    assert _BILL_LINE.pattern == "^[+−-][$€£₹]"


def test_euro_card_drops_the_euro_bill_line() -> None:
    brief = fixtures.by_key("blanchardstown")
    assert brief is not None
    spec = spec_from_brief(brief)
    assert spec.big == "+€36 to €54"
    assert spec.big_caption == "a month for a typical home, H1 2026 vs H1 2024 · modelled"
    assert not any(line.startswith("+€") for line in spec.lines)
    assert spec.title == "Blanchardstown, Co. Dublin"


def test_usd_strings_unchanged() -> None:
    assert fmt_money(31) == fmt_money(31, "USD") == "+$31"
    assert fmt_range(25, 37) == "+$25 to $37"
    assert fmt_range(36, 54, "EUR") == "+€36 to €54"
    assert fmt_money(-3, "EUR") == "−€3"
    spec = spec_from_brief(fixtures.by_key("ashburn"))
    assert spec.big == "+$25 to $37" and spec.big_caption.endswith("· modeled")


def test_disclosure_written_into_new_briefs() -> None:
    from app.brief.draft import SectionFailure
    from app.schema import SECTION_IDS, brief_errors

    drafts = {sid: SectionFailure(sid, "x") for sid in SECTION_IDS}
    brief = assemble_brief(
        fakes.GEO,
        drafts,
        brief_id="0123456789abcdef",
        now_iso="2026-10-28T12:00:00Z",
        public_base_url="https://grid.example/",
    )
    assert brief["card"]["disclosure"].endswith(
        "checked by Muse Spark Open. https://grid.example/b/0123456789abcdef · 2026-10-28"
    )
    spec = spec_from_brief(brief, public_base_url="https://grid.example")
    assert spec.disclosure == brief["card"]["disclosure"]
    assert not brief_errors(brief)


def test_disclosure_claims_only_what_was_done() -> None:
    from app.brief.draft import SectionFailure
    from app.brief.headline import disclosure_line
    from app.schema import SECTION_IDS

    full = disclosure_line("0123456789abcdef", "2026-10-28T12:00:00Z", "https://g.example")
    assert full == (
        "AI-assisted brief. Facts measured from public data; sentences drafted by Muse Spark "
        "and checked by Muse Spark Open. https://g.example/b/0123456789abcdef · 2026-10-28"
    )
    drafts = {sid: SectionFailure(sid, "x") for sid in SECTION_IDS}
    brief = assemble_brief(
        fakes.GEO,
        drafts,
        brief_id="0123456789abcdef",
        now_iso="2026-10-28T12:00:00Z",
        verified=False,
        truth=None,
    )
    for line in (brief["card"]["disclosure"], spec_from_brief(brief).disclosure):
        assert line.startswith("AI-assisted brief.")
        assert "checked by" not in line and "measured" not in line, line
    # A brief cached before card.disclosure: the footer says what was checked.
    old = {**brief, "card": {k: v for k, v in brief["card"].items() if k != "disclosure"}}
    assert "checked by" not in spec_from_brief(old).disclosure


def test_stored_disclosure_without_host_gets_one() -> None:
    from app.brief.draft import SectionFailure
    from app.schema import SECTION_IDS

    drafts = {sid: SectionFailure(sid, "x") for sid in SECTION_IDS}
    brief = assemble_brief(
        fakes.GEO, drafts, brief_id="0123456789abcdef", now_iso="2026-10-28T12:00:00Z"
    )
    assert " /b/0123456789abcdef" in brief["card"]["disclosure"]
    spec = spec_from_brief(brief, public_base_url="http://local:8000")
    assert "http://local:8000/b/0123456789abcdef · 2026-10-28" in spec.disclosure


def test_money_rounds_like_to_fixed() -> None:
    assert fmt_range(12.5, 20.5) == "+$13 to $21"
    assert fmt_money(-0.5) == "−$1"
    assert fmt_money(0.49999999999999994) == "+$0"
    assert fmt_range(-14.2, -9.6) == "−$14 to $10"


def test_scenario_spec_is_hypothetical() -> None:
    scenario = {
        "disclosure": "Hypothetical. Modelled, not measured.",
        "impact": {"bill": {"kind": "range", "range_usd_per_month": [2.0, 6.0]}},
        "card": {
            "title": "Who's on my grid: Kenosha, WI",
            "lines": ["300 MW, about 240,000 homes' worth", "+$2/mo bill line"],
            "footer": "Sources: eia.gov",
        },
    }
    spec = spec_from_scenario(scenario)
    assert spec.hypothetical and spec.kind == "scenario" and spec.big == "+$2 to $6"
    assert spec.lines == ("300 MW, about 240,000 homes' worth",)
    assert spec.disclosure == "Hypothetical. Modelled, not measured."


def test_share_text() -> None:
    spec = spec_from_brief(fixtures.by_key("boise"))
    assert share_text(spec, "https://g.example/b/x") == (
        "Boise, ID. 2 small facilities within 5 miles, both colocation sites. "
        "AI-assisted brief, every claim cited. https://g.example/b/x"
    )


def test_render_is_deterministic_and_marked(tmp_path) -> None:
    spec = spec_from_brief(fixtures.by_key("ashburn"), public_base_url="https://g.example")
    a, b = render_png(spec), render_png(spec)
    assert a == b
    img = Image.open(io.BytesIO(a))
    assert img.size == (W, H) == (1200, 630) and img.format == "PNG"
    # A scenario band and a long place name still render the same size.
    hyp = replace(spec, hypothetical=True, title="Pleasant Prairie Village Center, WI")
    assert Image.open(io.BytesIO(render_png(hyp))).size == (W, H)

    settings = fakes.settings(tmp_path)
    png = make_png(spec, link="https://g.example/b/3fb95348f1d4081e", settings=settings)
    assert png == make_png(spec, link="https://g.example/b/3fb95348f1d4081e", settings=settings)
    itxt = [data for kind, data in _chunks(png) if kind == b"iTXt"]
    assert len(itxt) == 1 and itxt[0].startswith(b"XML:com.adobe.xmp\x00")
    xmp = itxt[0].decode("utf-8")
    assert "Iptc4xmpExt:DigitalSourceType" in xmp and IPTC_COMPOSITE_AI in xmp
    assert "AI-assisted brief." in xmp and "https://g.example/b/3fb95348f1d4081e" in xmp
    assert _chunks(png)[-1][0] == b"IEND"
    Image.open(io.BytesIO(png)).load()  # still a valid PNG
    # No certificate configured: C2PA is a no-op.
    assert with_c2pa(png, settings=settings) == png


def test_long_title_shrinks_then_is_marked_cut() -> None:
    width = W - 2 * round(4.5 * CQW) - 300
    sign, lines = fit_title("Rancho Santa Margarita Mission Viejo, CA", width)
    assert len(lines) <= 2
    assert sign.size < round(9 * CQW) or lines[-1].endswith("…")
    sign, lines = fit_title(" ".join(["Wordy"] * 40) + ", CA", width)
    assert len(lines) == 2 and lines[-1].endswith("…")
    sign, lines = fit_title("Boise, ID", width)
    assert lines == ["Boise, ID"] and sign.size == round(9 * CQW)


def test_card_cache_paths(tmp_path) -> None:
    cache = CardCache(tmp_path)
    assert cache.path("brief", "../../etc/passwd") is None
    assert cache.path("other", "0123456789abcdef") is None
    assert cache.get("brief", "0123456789abcdef", "ab12") is None
    cache.put("brief", "0123456789abcdef", b"png", "ab12")
    assert cache.get("brief", "0123456789abcdef", "ab12") == b"png"
    assert cache.get("brief", "0123456789abcdef", "cd34") is None
    assert not list(tmp_path.rglob("*.tmp"))


async def test_card_routes(tmp_path) -> None:
    svc = fakes.service(tmp_path, public_base_url="https://grid.example")
    brief = dict(fixtures.by_key("tucson"))
    svc.cache.put(brief)
    bid = brief["brief_id"]
    app = create_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/card/{bid}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert r.headers["cache-control"] == "public, max-age=86400"
        assert bid in r.headers["etag"]
        assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
        assert list((tmp_path / "cards" / "brief").glob(f"{bid}.*.png"))
        # Second hit is the cached file, byte for byte.
        assert (await c.get(f"/api/card/{bid}.png")).content == r.content

        info = (await c.get(f"/api/card/{bid}.json")).json()
        assert set(info) == {"kind", "id", "spec", "share_text", "url", "image_url"}
        assert info["kind"] == "brief" and info["id"] == bid
        assert info["url"] == f"https://grid.example/b/{bid}"
        assert info["image_url"] == f"https://grid.example/api/card/{bid}.png"
        assert set(info["spec"]) == {
            "title", "lines", "big", "big_caption", "footer", "disclosure", "hypothetical",
        }  # fmt: skip
        assert info["spec"]["title"] == "Tucson, AZ" and info["spec"]["hypothetical"] is False
        assert info["share_text"].endswith(f"every claim cited. https://grid.example/b/{bid}")

        missing = await c.get("/api/card/0123456789abcdef.png")
        assert missing.status_code == 404 and missing.json()["detail"] == "brief_not_found"
        assert (await c.get("/api/card/0123456789abcdef.json")).status_code == 404
        for bad in ("XYZ", "0123456789ABCDEF", "0123456789abcdef0", ".."):
            r = await c.get(f"/api/card/{bad}.png")
            assert r.status_code == 422, bad
            assert (await c.get(f"/api/card/{bad}.json")).status_code == 422


async def test_card_routes_fixtures_mode_and_request_origin(tmp_path) -> None:
    app = create_app(fakes.service(tmp_path, brief_source="fixtures"))
    bid = fixtures.by_key("ashburn")["brief_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local:8000") as c:
        info = (await c.get(f"/api/card/{bid}.json")).json()
        assert info["url"] == f"http://local:8000/b/{bid}"
        assert info["spec"]["big"] == "+$25 to $37"
        assert f"http://local:8000/b/{bid} · " in info["spec"]["disclosure"]
        assert (await c.get(f"/api/card/{bid}.png")).status_code == 200
    # Another Host draws its own card; the first one's link is not served to it.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://other") as c:
        png = (await c.get(f"/api/card/{bid}.png")).content
        assert b"http://other/b/" in png and b"http://local:8000" not in png
    assert len(list((tmp_path / "cards" / "brief").glob(f"{bid}.*.png"))) == 2
