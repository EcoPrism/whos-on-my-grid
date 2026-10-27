"""Fetch a cited page and turn it into text the verifier can read.

The URLs come from model output, so they are untrusted. Every hop is checked
before it is fetched: the hostname must resolve only to public addresses, and
the connection is opened to the address that was vetted (Host header and TLS
server name pinned to the original hostname), so a DNS answer cannot change
between the check and the connect. Redirects are followed by hand (at most
MAX_REDIRECTS) with the same check on each Location. Bounded in time and size.
HTML and plain text only: a PDF is reported as such so the claim shows as
unverifiable with an honest note.
"""

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol

import httpx

from app.config import get_settings

MAX_BYTES = 1_500_000
MIN_TEXT = 200
MAX_REDIRECTS = 3
USER_AGENT = (
    "Mozilla/5.0 (compatible; WhosOnMyGrid/0.1; +https://github.com/EcoPrism/whos-on-my-grid) "
    "fact-check fetch"
)
PDF_NOTE = "PDF source; PDFs are not fetched in agent mode"


@dataclass
class FetchResult:
    ok: bool
    text: str = ""
    note: str = ""
    status: int | None = None


class Fetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult: ...


# --- URL policy -----------------------------------------------------------


def _non_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def vet(url: str) -> tuple[str | None, str | None]:
    """(reason the URL must not be fetched, vetted public IP). Resolves the
    host and rejects it if any address is not public, so a model-supplied URL
    can never reach loopback, a private network or a cloud metadata service.
    The fetcher connects to the returned IP, never to the name again."""
    try:
        u = httpx.URL(url)
    except Exception:
        return "malformed URL", None
    if u.scheme not in ("http", "https"):
        return "not an http(s) URL", None
    if not u.host:
        return "URL has no host", None
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(u.host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return "host not found", None
    if not infos:
        return "host not found", None
    ips: list[str] = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return "host resolves to an unusable address", None
        if _non_public(ip):
            return "host resolves to a non-public address", None
        ips.append(str(ip))
    return None, ips[0]


async def blocked_reason(url: str) -> str | None:
    """Why this URL must not be fetched, or None if it may be."""
    reason, _ip = await vet(url)
    return reason


def pin(url: str, ip: str) -> tuple[httpx.URL, dict[str, str], dict[str, str]]:
    """The request that reaches exactly the vetted address: URL with the IP
    literal in place of the name, Host header and SNI carrying the name."""
    u = httpx.URL(url)
    headers = {"Host": u.netloc.decode()}
    extensions = {"sni_hostname": u.host} if u.scheme == "https" else {}
    return u.copy_with(host=ip), headers, extensions


# --- HTML to text ---------------------------------------------------------

_SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
_BLOCK = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "td", "th", "blockquote", "pre",
}  # fmt: skip


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n\s*\n+")


def html_to_text(html: str) -> str:
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:  # malformed markup: use what we have
        pass
    text = "".join(p.parts)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


# --- fetchers -------------------------------------------------------------

_REDIRECTS = {301, 302, 303, 307, 308}


class HttpFetcher:
    async def fetch(self, url: str) -> FetchResult:
        timeout = get_settings().fetch_timeout_seconds
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"}
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, headers=headers
            ) as client:
                for _hop in range(MAX_REDIRECTS + 1):
                    reason, ip = await vet(url)
                    if reason or ip is None:
                        return FetchResult(False, note=reason or "host not found")
                    if url.lower().split("?")[0].endswith(".pdf"):
                        return FetchResult(False, note=PDF_NOTE)
                    pinned, host_headers, ext = pin(url, ip)
                    async with client.stream(
                        "GET", pinned, headers=host_headers, extensions=ext
                    ) as r:
                        location = r.headers.get("location")
                        if r.status_code in _REDIRECTS and location:
                            url = str(httpx.URL(url).join(location))
                            continue
                        return await _read(r)
                return FetchResult(False, note="too many redirects")
        except httpx.TimeoutException:
            return FetchResult(False, note="timed out")
        except httpx.HTTPError as exc:
            return FetchResult(False, note=f"fetch failed: {exc.__class__.__name__}")


async def _read(r: httpx.Response) -> FetchResult:
    if r.status_code >= 400:
        return FetchResult(False, note=f"HTTP {r.status_code}", status=r.status_code)
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype == "application/pdf":
        return FetchResult(False, note=PDF_NOTE, status=r.status_code)
    if ctype and not (
        ctype.startswith("text/") or "html" in ctype or "xml" in ctype or "json" in ctype
    ):
        return FetchResult(False, note=f"unsupported content type {ctype}", status=r.status_code)
    chunks: list[bytes] = []
    size = 0
    async for chunk in r.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_BYTES:
            break
    raw = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
    looks_html = "html" in ctype or raw.lstrip()[:1] == "<"
    text = html_to_text(raw) if looks_html else _WS.sub(" ", raw).strip()
    if len(text) < MIN_TEXT:
        return FetchResult(
            False, note="page had no readable text (may need JavaScript)", status=r.status_code
        )
    return FetchResult(True, text=text, status=r.status_code)


class FakeFetcher:
    """Scripted pages by URL; anything else fails with the given note."""

    def __init__(self, pages: dict[str, str] | None = None, *, note: str = "HTTP 404") -> None:
        self.pages = dict(pages or {})
        self.note = note
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        if url in self.pages:
            return FetchResult(True, text=self.pages[url], status=200)
        return FetchResult(False, note=self.note)
