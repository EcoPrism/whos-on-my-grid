"""The fetcher follows model-supplied URLs, so it must refuse anything that is
not a public http(s) host. These cases need no network: IP literals and
localhost resolve locally."""

import pytest

from app.brief.fetch import blocked_reason, html_to_text, pin, vet


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost:8000/api/health",
        "http://[::1]/",
        "http://10.0.0.1/secret",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
    ],
)
async def test_non_public_hosts_are_blocked(url: str) -> None:
    assert "non-public" in (await blocked_reason(url) or "")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.org/x", "not a url", "http:///nohost"]
)
async def test_non_http_is_blocked(url: str) -> None:
    assert await blocked_reason(url) is not None


async def test_public_literal_is_allowed() -> None:
    assert await blocked_reason("http://93.184.216.34/") is None


def test_html_to_text_drops_script_and_keeps_blocks() -> None:
    html = "<html><head><script>x()</script><style>a{}</style></head><body><p>One</p><div>Two</div></body></html>"
    assert html_to_text(html) == "One\nTwo"


async def test_vet_returns_the_public_ip_to_connect_to() -> None:
    reason, ip = await vet("http://93.184.216.34/x")
    assert reason is None and ip == "93.184.216.34"


def test_pin_connects_to_the_ip_and_keeps_the_name_for_host_and_sni() -> None:
    url, headers, ext = pin("https://example.org:8443/a?b=1", "2606:2800:220:1:248:1893:25c8:1946")
    assert str(url) == "https://[2606:2800:220:1:248:1893:25c8:1946]:8443/a?b=1"
    assert headers == {"Host": "example.org:8443"}
    assert ext == {"sni_hostname": "example.org"}


def test_pin_plain_http_sets_no_sni() -> None:
    url, headers, ext = pin("http://example.org/", "93.184.216.34")
    assert str(url) == "http://93.184.216.34/"
    assert headers == {"Host": "example.org"} and ext == {}
