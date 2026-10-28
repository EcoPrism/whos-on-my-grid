"""Muse Voice Transcribe on the Meta Model API: `POST /v1/asr/transcribe`,
multipart (`request` JSON + `audio` WAV), diarization mode. Returns turns
with start and end in seconds and a per-request speaker label."""

import asyncio
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.hearings.audio import Chunk
from app.telemetry import log_event


@dataclass(frozen=True)
class Turn:
    start_s: float
    end_s: float
    speaker: str | None
    text: str


class TranscribeError(Exception):
    pass


class VoiceTranscribeClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.meta.ai/v1",
        model: str = "muse-voice-transcribe-1.0",
        timeout: float = 600.0,
        concurrency: int = 6,
    ) -> None:
        if not api_key:
            raise TranscribeError("GRID_META_API_KEY is not set")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._sem = asyncio.Semaphore(concurrency)

    async def transcribe_wav(self, path: Path, keywords: list[str]) -> list[Turn]:
        request = {
            "model": self.model,
            "audioEncoding": "WAV",
            "mode": "DIARIZATION",
            "languageBias": ["English"],
        }
        if keywords:
            request["keywords"] = keywords[:50]
        audio = path.read_bytes()
        files = {
            "request": (None, json.dumps(request), "application/json"),
            "audio": (path.name, audio, "audio/wav"),
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        async with self._sem:
            for attempt in range(1, 5):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        r = await client.post(
                            f"{self.base_url}/asr/transcribe", files=files, headers=headers
                        )
                except httpx.HTTPError as exc:
                    if attempt == 4:
                        raise TranscribeError(f"{path.name}: {exc.__class__.__name__}") from exc
                    await asyncio.sleep(2**attempt + random.random())
                    continue
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                    log_event("transcribe_retry", status=r.status_code, attempt=attempt)
                    await asyncio.sleep(2**attempt + random.random())
                    continue
                if r.status_code != 200:
                    raise TranscribeError(f"{path.name}: HTTP {r.status_code} {r.text[:200]}")
                body = r.json()
                break
        turns = [
            Turn(
                start_s=float(t.get("startMs", 0)) / 1000,
                end_s=float(t.get("endMs", 0)) / 1000,
                speaker=t.get("speaker"),
                text=str(t.get("transcript") or "").strip(),
            )
            for t in body.get("turns") or []
        ]
        if not turns and body.get("transcript"):
            turns = [
                Turn(0.0, float(body.get("audioDurationMs", 0)) / 1000, None, body["transcript"])
            ]
        log_event(
            "transcribe",
            file=path.name,
            seconds=float(body.get("audioDurationMs", 0)) / 1000,
            turns=len(turns),
        )
        return [t for t in turns if t.text]


async def transcribe_chunks(
    client: VoiceTranscribeClient, chunks: list[Chunk], keywords: list[str], overlap_s: float
) -> list[dict[str, Any]]:
    """Every chunk in parallel; turns shifted to recording time. Speaker
    labels are per request, so they are prefixed with the chunk index. A turn
    that starts inside the overlap of a later chunk is dropped: the earlier
    chunk already heard it."""
    results = await asyncio.gather(*(client.transcribe_wav(c.path, keywords) for c in chunks))
    out: list[dict[str, Any]] = []
    for i, (chunk, turns) in enumerate(zip(chunks, results, strict=True)):
        for t in turns:
            if i > 0 and t.start_s < overlap_s * 0.6:
                continue
            out.append(
                {
                    "start_s": round(chunk.offset_s + t.start_s, 1),
                    "end_s": round(chunk.offset_s + t.end_s, 1),
                    "speaker": f"{i}:{t.speaker}" if t.speaker else f"{i}:?",
                    "role": "unknown",
                    "name": None,
                    "text": t.text,
                    "source": "transcribe",
                }
            )
    out.sort(key=lambda t: t["start_s"])
    return out


def agreement(transcript: list[dict[str, Any]], captions: list[dict[str, Any]]) -> float | None:
    """Token F1 between what the model heard and what the archive captioned,
    over the same window. None without captions."""
    if not captions or not transcript:
        return None
    a = _tokens(" ".join(t["text"] for t in transcript))
    b = _tokens(" ".join(t["text"] for t in captions))
    if not a or not b:
        return None
    from collections import Counter

    common = sum((Counter(a) & Counter(b)).values())
    if common == 0:
        return 0.0
    p, r = common / len(a), common / len(b)
    return round(2 * p * r / (p + r), 3)


def _tokens(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9']+", text.lower())


# Common words a readable English transcript is mostly made of. Machine captions that drop
# characters ("Goodernoon chaeffeon the member theboard") score low because even these break.
_COMMON = set(
    [
        "the",
        "of",
        "and",
        "to",
        "a",
        "in",
        "that",
        "is",
        "it",
        "for",
        "on",
        "with",
        "as",
        "this",
        "be",
        "are",
        "we",
        "have",
        "not",
        "you",
        "i",
        "they",
        "at",
        "our",
        "from",
        "by",
        "or",
        "an",
        "was",
        "will",
        "what",
        "all",
        "can",
        "so",
        "if",
        "there",
        "about",
        "would",
        "been",
        "has",
        "their",
        "one",
        "which",
        "do",
        "your",
        "when",
        "who",
        "more",
        "no",
        "out",
        "up",
        "them",
        "than",
        "then",
        "some",
        "into",
        "could",
        "time",
        "these",
        "just",
        "also",
        "like",
        "only",
        "other",
        "how",
        "its",
        "my",
        "very",
        "because",
        "any",
        "over",
        "such",
        "where",
        "after",
        "most",
        "should",
        "think",
        "know",
        "going",
        "here",
        "want",
        "make",
        "going",
        "say",
        "said",
        "get",
        "go",
        "see",
        "need",
        "going",
        "people",
        "county",
        "board",
        "center",
        "centers",
        "data",
        "year",
        "years",
        "project",
        "public",
        "staff",
        "motion",
        "vote",
        "supervisor",
        "supervisors",
        "chair",
        "thank",
        "question",
        "support",
        "oppose",
        "resolution",
        "amendment",
        "power",
        "water",
        "energy",
        "residents",
        "community",
    ]
)


def caption_quality(turns: list[dict[str, Any]]) -> float | None:
    """Share of word tokens that are common English words. Readable text sits
    around 0.45 to 0.6; garbled captions fall under 0.3."""
    words = _tokens(" ".join(t["text"] for t in turns))
    if len(words) < 50:
        return None
    return round(sum(1 for w in words if w in _COMMON) / len(words), 3)
