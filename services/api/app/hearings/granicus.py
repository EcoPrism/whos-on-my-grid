"""Granicus, the archive platform behind the first three indexed bodies.

Per clip it publishes a player page (the URL a claim cites), a JSON index
(`JSON.php?clip_id=`) of agenda index points (`type: meta`, seconds into the
recording) and, on newer clips, closed-caption cues (`type: text`, about three
seconds each), and a media redirect (`DownloadFile.php`) to the MP4, with an
MP3 sibling at the same path."""

import html
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.ground.facilities import USER_AGENT

# The media host answers a bare library User-Agent with 403; a browser string
# is what a person downloading the recording sends. Used for --download only.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 WhosOnMyGrid/0.1"
)

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SPEAKER_MARK = re.compile(r">>+\s*")


@dataclass(frozen=True)
class IndexPoint:
    time_s: float
    title: str


@dataclass(frozen=True)
class Caption:
    time_s: float
    text: str


def player_url(site: str, clip_id: int, view_id: int) -> str:
    return f"https://{site}.granicus.com/player/clip/{clip_id}?view_id={view_id}"


def index_url(site: str, clip_id: int) -> str:
    return f"https://{site}.granicus.com/JSON.php?clip_id={clip_id}"


def download_url(site: str, clip_id: int, view_id: int) -> str:
    return f"https://{site}.granicus.com/DownloadFile.php?view_id={view_id}&clip_id={clip_id}"


_APOSTROPHE = re.compile(r"(\w)' (s|t|re|ve|ll|d|m)\b")


def clean(text: str) -> str:
    text = _WS.sub(" ", html.unescape(_TAGS.sub(" ", text or ""))).strip()
    return _APOSTROPHE.sub(r"\1'\2", text)  # captions split "That' s" at the cue boundary


def parse_index(data: Any) -> tuple[list[IndexPoint], list[Caption]]:
    """The JSON is a list of lists of entries; flatten and split by type."""
    entries: list[dict[str, Any]] = []
    for part in data if isinstance(data, list) else []:
        if isinstance(part, list):
            entries.extend(e for e in part if isinstance(e, dict))
        elif isinstance(part, dict):
            entries.append(part)
    points, captions = [], []
    for e in entries:
        try:
            t = float(e.get("time") or 0)
        except (TypeError, ValueError):
            continue
        if e.get("type") == "meta":
            points.append(IndexPoint(t, clean(e.get("title") or e.get("text") or "")))
        elif e.get("type") == "text":
            captions.append(Caption(t, clean(e.get("text") or "")))
    points.sort(key=lambda p: p.time_s)
    captions.sort(key=lambda c: c.time_s)
    return points, captions


async def fetch_index(
    site: str, clip_id: int, timeout: float = 120.0
) -> tuple[list[IndexPoint], list[Caption]]:
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(index_url(site, clip_id))
        r.raise_for_status()
        return parse_index(r.json())


async def media_urls(
    site: str, clip_id: int, view_id: int, timeout: float = 60.0
) -> tuple[str, str] | None:
    """(mp4, mp3) on the archive host, from the DownloadFile redirect."""
    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=False
    ) as client:
        r = await client.head(download_url(site, clip_id, view_id))
        loc = r.headers.get("location")
        if r.status_code not in (301, 302) or not loc:
            return None
        mp4 = loc
        mp3 = re.sub(r"\.mp4(\?.*)?$", ".mp3", mp4)
        return mp4, mp3


# --- captions -> turns -------------------------------------------------------------

MAX_TURN_S = 45.0
GAP_S = 4.0
MIN_TURN_CHARS = 60


def captions_to_turns(
    captions: list[Caption], start_s: float, end_s: float
) -> list[dict[str, Any]]:
    """Three-second cues into speaker turns. Granicus marks a change of
    speaker with '>>'; otherwise a turn ends at a sentence end once it has
    some length, at a long silence, or at MAX_TURN_S. Roles are unknown; the
    role labeller fills them in."""
    turns: list[dict[str, Any]] = []
    buf: list[str] = []
    t0: float | None = None
    last: float | None = None

    def flush(end: float) -> None:
        nonlocal buf, t0
        # The apostrophe fix again: cues split "That'" | "s" across the join.
        text = _APOSTROPHE.sub(r"\1'\2", _WS.sub(" ", " ".join(buf)).strip())
        if text and t0 is not None:
            turns.append(
                {
                    "start_s": round(t0, 1),
                    "end_s": round(end, 1),
                    "speaker": None,
                    "role": "unknown",
                    "name": None,
                    "text": text,
                    "source": "captions",
                }
            )
        buf, t0 = [], None

    for c in captions:
        if c.time_s < start_s or c.time_s > end_s or not c.text:
            continue
        pieces = _SPEAKER_MARK.split(c.text)
        starts_new = bool(_SPEAKER_MARK.match(c.text))
        if last is not None and (c.time_s - last > GAP_S or (t0 and c.time_s - t0 > MAX_TURN_S)):
            flush(last)
        for i, piece in enumerate(pieces):
            piece = piece.strip()
            if i > 0 or (i == 0 and starts_new):
                flush(last if last is not None else c.time_s)
            if not piece:
                continue
            if t0 is None:
                t0 = c.time_s
            buf.append(piece)
        last = c.time_s
        joined = " ".join(buf)
        if len(joined) >= MIN_TURN_CHARS * 4 and joined.rstrip()[-1:] in ".?!":
            flush(c.time_s)
    if buf and last is not None:
        flush(last)
    return [t for t in turns if len(t["text"]) >= 12]


def points_in(points: list[IndexPoint], start_s: float, end_s: float) -> list[dict[str, Any]]:
    return [{"time_s": p.time_s, "title": p.title} for p in points if start_s <= p.time_s <= end_s]
