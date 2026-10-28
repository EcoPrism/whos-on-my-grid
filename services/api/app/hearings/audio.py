"""Cut a window of a meeting recording into the WAV chunks Voice Transcribe
accepts: mono, 16-bit PCM, 16 kHz, at most ten minutes each. ffmpeg comes
from the `imageio-ffmpeg` wheel so nothing needs installing on the machine."""

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

CHUNK_S = 600.0  # the API's ten-minute cap
OVERLAP_S = 5.0
RATE = 16_000


@dataclass(frozen=True)
class Chunk:
    path: Path
    offset_s: float  # where this chunk starts in the recording
    duration_s: float


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        found = shutil.which("ffmpeg")
        if not found:
            raise RuntimeError(
                "ffmpeg not found: `uv sync --group index` installs imageio-ffmpeg"
            ) from None
        return found


async def cut_chunks(
    source: Path,
    start_s: float,
    end_s: float,
    out_dir: Path,
    *,
    chunk_s: float = CHUNK_S,
    overlap_s: float = OVERLAP_S,
    rate: int = RATE,
) -> list[Chunk]:
    """Chunks covering [start_s, end_s], each `chunk_s` long with `overlap_s`
    carried into the next so a sentence cut at the boundary is heard whole once."""
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = ffmpeg_exe()
    chunks: list[Chunk] = []
    t = start_s
    n = 0
    while t < end_s:
        dur = min(chunk_s, end_s - t)
        path = out_dir / f"{source.stem}_{int(t):06d}.wav"
        if not path.exists():
            cmd = [
                exe, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{t:.2f}", "-t", f"{dur:.2f}", "-i", str(source),
                "-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", "-map_metadata", "-1",
                str(path),
            ]  # fmt: skip
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed on {source.name} at {t:.0f}s: {err.decode()[:300]}"
                )
        chunks.append(Chunk(path, t, dur))
        n += 1
        if t + dur >= end_s:
            break
        t += chunk_s - overlap_s
    return chunks
