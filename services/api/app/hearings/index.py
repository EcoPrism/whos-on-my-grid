"""Index one meeting from `data/regions/us/hearings/sources.json`:

    uv run python -m app.hearings.index --meeting loudoun-2025-03-18 --captions-only
    uv run python -m app.hearings.index --meeting pwc-2023-12-12 \
        --audio data/regions/us/hearings/audio/pwcgov_3410.mp3
    uv run python -m app.hearings.index --meeting pwc-2023-12-12 --download

Writes `data/regions/us/hearings/<body>/<meeting>.json`: the transcript turns for the
meeting's windows (Muse Voice Transcribe on the recording, or the archive's
captions with --captions-only), speaker roles labelled by Muse Spark, the
agreement between transcript and captions where both exist, and the agenda
index points inside the windows."""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.brief.fetch import blocked_reason
from app.config import DRAFT_MODEL_ID, get_settings
from app.ground.hearings import HearingIndex
from app.hearings.audio import OVERLAP_S, cut_chunks
from app.hearings.granicus import (
    BROWSER_UA,
    captions_to_turns,
    fetch_index,
    media_host_ok,
    media_urls,
    points_in,
)
from app.hearings.roles import apply_roles, label_roles
from app.hearings.transcribe import (
    VoiceTranscribeClient,
    agreement,
    caption_quality,
    transcribe_chunks,
)

MIN_QUALITY = 0.35  # share of common words; readable text is 0.45+, garbled captions under 0.3


def find(sources: dict[str, Any], meeting_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for body in sources.get("bodies", []):
        for meeting in body.get("meetings", []):
            if meeting["id"] == meeting_id:
                return body, meeting
    sys.exit(f"meeting {meeting_id!r} is not in sources.json")


MAX_AUDIO_BYTES = 3 << 30  # a 27-hour meeting at 128 kbps is about 1.5 GB


async def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  audio already here: {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
        return dest
    if not media_host_ok(url):
        sys.exit(f"refusing to download from outside the archive host: {url}")
    reason = await blocked_reason(url)
    if reason:
        sys.exit(f"refusing to download: {reason}")
    print(f"  downloading {url}")
    tmp = dest.with_suffix(".part")
    async with (
        httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, read=600.0),
            headers={"User-Agent": BROWSER_UA},
            follow_redirects=False,  # the vetted URL is the one that is read
        ) as client,
        client.stream("GET", url) as r,
    ):
        r.raise_for_status()
        size = 0
        with open(tmp, "wb") as f:
            async for chunk in r.aiter_bytes(1 << 20):
                f.write(chunk)
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    sys.exit(f"download exceeded {MAX_AUDIO_BYTES >> 30} GB; stopped")
                if size % (50 << 20) < (1 << 20):
                    print(f"    {size / 1e6:.0f} MB")
    tmp.replace(dest)
    print(f"  saved {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
    return dest


def minutes(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


async def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--meeting", required=True, help="meeting id from sources.json")
    ap.add_argument(
        "--audio",
        type=Path,
        help="local recording (mp3/mp4); default: <hearings dir>/audio/<site>_<clip>.mp3",
    )
    ap.add_argument(
        "--download",
        action="store_true",
        help="fetch the MP3 from the archive if the local file is missing",
    )
    ap.add_argument(
        "--captions-only",
        action="store_true",
        help="skip audio; turns come from the archive's captions",
    )
    ap.add_argument("--no-roles", action="store_true", help="skip the Spark role labeller")
    ap.add_argument("--out", type=Path, help="hearings directory (default GRID_HEARINGS_DIR)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    hearings_dir = args.out or settings.hearings_path
    index = HearingIndex(hearings_dir)
    body, meeting = find(index.sources(), args.meeting)
    archive = body["archive"]
    site, view_id, clip_id = archive["site"], int(archive["view_id"]), int(meeting["clip_id"])
    windows = meeting.get("windows") or []
    if not windows:
        sys.exit("the meeting has no windows; add [{item, start_s, end_s}] to sources.json")
    print(f"{body['name']} · {meeting['date']} · clip {clip_id} · {len(windows)} window(s)")

    points, captions = await fetch_index(site, clip_id)
    recording_s = max([p.time_s for p in points] + [c.time_s for c in captions] + [0.0])
    print(
        f"  index: {len(points)} index points, {len(captions)} caption cues, "
        f"recording ~{minutes(recording_s)}"
    )

    caption_turns: dict[int, list[dict[str, Any]]] = {
        i: captions_to_turns(captions, float(w["start_s"]), float(w["end_s"]))
        for i, w in enumerate(windows)
    }
    turns: list[dict[str, Any]] = []
    agreements: list[float] = []
    transcribe_model: str | None = None

    if args.captions_only:
        if not any(caption_turns.values()):
            sys.exit("no captions on this clip; run with audio instead")
        for i, _ in enumerate(windows):
            turns.extend(caption_turns[i])
        # Captions carry no speaker labels: each turn gets its own, in groups
        # of forty so the role labeller sees a stretch of the meeting at once.
        for n, t in enumerate(turns):
            t["speaker"] = f"{n // 40}:t{n}"
    else:
        audio = args.audio or (hearings_dir / "audio" / f"{site}_{clip_id}.mp3")
        if not audio.exists():
            if not args.download:
                sys.exit(
                    f"no audio at {audio}. Download the MP3 from the archive page in a browser "
                    f"({meeting['page_url']}) into that path, or pass --download."
                )
            urls = await media_urls(site, clip_id, view_id)
            if urls is None:
                sys.exit("the archive gave no media redirect for this clip")
            await download(urls[1], audio)
        client = VoiceTranscribeClient(
            api_key=settings.meta_api_key,
            base_url=settings.meta_base_url,
            model=settings.transcribe_model,
        )
        transcribe_model = settings.transcribe_model
        chunk_dir = hearings_dir / "audio" / "chunks" / f"{site}_{clip_id}"
        for i, w in enumerate(windows):
            start, end = float(w["start_s"]), float(w["end_s"])
            chunks = await cut_chunks(audio, start, end, chunk_dir)
            print(f"  window {w['item']!r} {minutes(end - start)}: {len(chunks)} chunks")
            got = await transcribe_chunks(client, chunks, meeting.get("keywords") or [], OVERLAP_S)
            print(f"    {len(got)} turns")
            a = agreement(got, caption_turns[i])
            if a is not None:
                agreements.append(a)
                print(f"    agreement with captions: {a:.2f}")
            turns.extend(got)

    roles_model: str | None = None
    if not args.no_roles and turns:
        if settings.llm_provider != "openai" or not settings.openai_api_key:
            print("  roles: no Spark key configured; roles stay unknown")
        else:
            from app.llm import get_draft_provider

            labels = await label_roles(
                get_draft_provider(),
                turns,
                body=body["name"],
                date=meeting["date"],
                subject=meeting.get("subject", ""),
            )
            apply_roles(turns, labels)
            roles_model = DRAFT_MODEL_ID
            known = sum(1 for t in turns if t["role"] != "unknown")
            print(f"  roles: {known} of {len(turns)} turns labelled")

    quality = caption_quality(turns)
    usable = quality is None or quality >= MIN_QUALITY
    if not usable:
        print(
            f"  WARNING: text quality {quality:.2f} is below {MIN_QUALITY}; these captions are "
            "garbled. The file is written as unusable: the brief will cite the agenda index "
            "only until the recording is transcribed from audio."
        )
    covered = sum(float(w["end_s"]) - float(w["start_s"]) for w in windows)
    items = ", ".join(str(w["item"]) for w in windows)
    coverage = f"{items} ({minutes(covered)} of a {minutes(recording_s)} recording)"
    out = {
        "meeting_id": meeting["id"],
        "body_id": body["id"],
        "body": body["name"],
        "date": meeting["date"],
        "clip_id": clip_id,
        "page_url": meeting["page_url"],
        "subject": meeting.get("subject", ""),
        "indexed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models": {"transcribe": transcribe_model, "roles": roles_model},
        "captions": bool(captions),
        "agreement": round(sum(agreements) / len(agreements), 3) if agreements else None,
        "quality": quality,
        "usable": usable,
        "coverage": coverage,
        "windows": windows,
        "index_points": [
            p for w in windows for p in points_in(points, float(w["start_s"]), float(w["end_s"]))
        ],
        "turns": turns,
    }
    dest = hearings_dir / body["id"] / f"{meeting['id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {dest}: {len(turns)} turns, coverage {coverage}")


if __name__ == "__main__":
    asyncio.run(main())
