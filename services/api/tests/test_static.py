"""Open Graph tags written into the served index.html: a brief's own on /b/{id},
the site defaults elsewhere, every value escaped."""

from httpx import ASGITransport, AsyncClient

from app.brief import fixtures
from app.main import create_app
from app.static import (
    OG_MARKER,
    SITE_DESCRIPTION,
    OgMeta,
    describe,
    inject,
    og_tags,
    site_description,
)
from tests import fakes
from tests.test_health_regions import enable_ie

INDEX = (
    "<!doctype html><html><head><title>grid</title>\n    "
    f"{OG_MARKER}\n</head><body><div id=root></div></body></html>"
)


def dist(tmp_path, index: str = INDEX):
    d = tmp_path / "dist"
    d.mkdir(parents=True)
    (d / "index.html").write_text(index, encoding="utf-8")
    return d


def test_inject_with_and_without_marker() -> None:
    assert inject("<head>A<!--og-->B<!--og--></head>", "T") == "<head>ATB<!--og--></head>"
    assert (
        inject("<html><head><title>x</title></HEAD>", "T") == "<html><head><title>x</title>T</HEAD>"
    )
    assert (
        inject("<!doctype html><title>grid</title>", "T") == "<!doctype html>T<title>grid</title>"
    )
    assert inject("<p>bare</p>", "T") == "T<p>bare</p>"


def test_og_tags_escape_every_value() -> None:
    tags = og_tags(
        OgMeta(
            title='Who\'s on my grid: <script>alert(1)</script> "x"',
            description="a & b",
            url="https://g.example/b/0123456789abcdef",
            image="https://g.example/api/card/0123456789abcdef.png",
        )
    )
    assert "<script>" not in tags and "&lt;script&gt;" in tags
    assert "&quot;x&quot;" in tags and "a &amp; b" in tags
    assert 'name="twitter:card" content="summary_large_image"' in tags


async def test_share_route_gets_brief_tags(tmp_path) -> None:
    svc = fakes.service(
        tmp_path, web_dist=str(dist(tmp_path)), public_base_url="https://grid.example"
    )
    brief = dict(fixtures.by_key("kenosha"))
    brief["card"] = {**brief["card"], "title": "Who's on my grid: <b>Pleasant</b> & Prairie"}
    svc.cache.put(brief)
    bid = brief["brief_id"]
    app = create_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/b/{bid}")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        page = r.text
        assert OG_MARKER not in page and "<title>grid</title>" in page
        assert f'property="og:image" content="https://grid.example/api/card/{bid}.png"' in page
        assert f'property="og:url" content="https://grid.example/b/{bid}"' in page
        assert 'property="og:type" content="article"' in page
        assert "&lt;b&gt;Pleasant&lt;/b&gt; &amp; Prairie" in page and "<b>Pleasant" not in page
        assert "AI-assisted brief, every claim cited." in page
        assert 'content="summary_large_image"' in page
        alt = page.split('property="og:image:alt" content="')[1].split('"')[0]
        assert "AI-assisted" in alt

        # Unknown brief, other pages: the site defaults, no image.
        for path in (f"/b/{'f' * 16}", "/about", "/", "/b/not-an-id"):
            r = await c.get(path)
            assert r.status_code == 200, path
            assert 'property="og:title" content="Who&#x27;s On My Grid"' in r.text, path
            assert "og:image" not in r.text and 'content="summary"' in r.text, path
            assert 'property="og:url" content="https://grid.example/"' in r.text, path

        # index.html by name is a page too: tags in, marker out, not cached.
        r = await c.get("/index.html")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        assert "og:title" in r.text and OG_MARKER not in r.text

        # The SPA handler never serves the page for an API path.
        r = await c.get("/api/nope")
        assert r.status_code == 404 and r.json()["detail"] == "not_found"


async def test_defaults_use_request_origin_and_no_marker(tmp_path) -> None:
    index = "<!doctype html><html><head><title>grid</title></head><body></body></html>"
    svc = fakes.service(tmp_path, web_dist=str(dist(tmp_path, index)), brief_source="fixtures")
    bid = fixtures.by_key("ashburn")["brief_id"]
    app = create_app(svc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local:8000") as c:
        page = (await c.get(f"/b/{bid}")).text
        assert f'content="http://local:8000/api/card/{bid}.png"' in page
        assert page.index("og:image") < page.index("</head>")


US_DESC = (
    "Type any US address. What is on my grid, what is coming, and what has it done to my bill."
)
DESC_INDEX = (
    "<!doctype html><html><head><title>grid</title>\n"
    f'    <meta name="description" content="{US_DESC}" />\n    '
    f"{OG_MARKER}\n</head><body></body></html>"
)


def test_site_description_names_the_enabled_regions() -> None:
    assert site_description([]) == SITE_DESCRIPTION == US_DESC
    assert site_description(["US"]) == US_DESC
    assert site_description(["US", "Ireland"]) == (
        "Type an address in the US or Ireland. What is on my grid, what is coming, "
        "and what has it done to my bill."
    )
    assert site_description(["Ireland"]).startswith("Type an address in Ireland. ")
    assert site_description(["US", "Ireland", "UK"]).startswith(
        "Type an address in the US, Ireland or UK. "
    )
    assert describe(DESC_INDEX, US_DESC) == DESC_INDEX
    assert describe("<head></head>", "x") == "<head></head>"
    out = describe(DESC_INDEX, 'a "b" & c')
    assert 'content="a &quot;b&quot; &amp; c" />' in out and US_DESC not in out


async def test_description_meta_follows_the_regions(tmp_path, monkeypatch) -> None:
    """US alone: the page as built (byte for byte, the static golden too). With
    Ireland enabled the page's description meta and the default og/twitter
    description name both places; a brief's own tags are unchanged."""
    d = dist(tmp_path, DESC_INDEX)
    app = create_app(fakes.service(tmp_path, web_dist=str(d)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        us_page = (await c.get("/")).text
    assert f'<meta name="description" content="{US_DESC}" />' in us_page
    assert "Ireland" not in us_page

    enable_ie(monkeypatch)
    app = create_app(services=fakes.services(tmp_path, web_dist=str(d)))
    both = site_description(["US", "Ireland"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for path in ("/", "/about", f"/b/{'f' * 16}"):
            page = (await c.get(path)).text
            assert f'<meta name="description" content="{both}" />' in page, path
            assert f'property="og:description" content="{both}"' in page, path
            assert f'name="twitter:description" content="{both}"' in page, path
            assert US_DESC not in page, path
