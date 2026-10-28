"""SAM 3.1 on the Meta Model API: one concept prompt and one image per
request through the Responses API, decoded with Meta's `meta-sam-parser`
into boxes and binary masks placed in the tile's pixel grid."""

import asyncio
import base64
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.telemetry import log_event


@dataclass(frozen=True)
class SamObject:
    object_id: str
    left: float
    top: float
    right: float
    bottom: float
    confidence: float | None
    mask: np.ndarray  # bool, shape (frame_h, frame_w)


class SamError(Exception):
    pass


class SamClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.meta.ai/v1",
        model: str = "sam-3.1",
        timeout: float = 180.0,
        concurrency: int = 4,
        cache: Path | None = None,
    ) -> None:
        if not api_key:
            raise SamError("GRID_META_API_KEY is not set")
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.cache = cache
        self._sem = asyncio.Semaphore(concurrency)

    async def segment(
        self, png: bytes, concept: str, *, size: tuple[int, int], cache_key: str | None = None
    ) -> list[SamObject]:
        """Objects matching `concept` in the image. The raw model output is
        cached by key so a re-run costs nothing."""
        raw = self._cached(cache_key)
        if raw is None:
            raw = await self._call(png, concept)
            if cache_key and self.cache is not None:
                self.cache.mkdir(parents=True, exist_ok=True)
                (self.cache / f"{cache_key}.txt").write_text(raw, "utf-8")
        return decode(raw, size)

    def _cached(self, key: str | None) -> str | None:
        if not key or self.cache is None:
            return None
        p = self.cache / f"{key}.txt"
        return p.read_text("utf-8") if p.exists() else None

    async def _call(self, png: bytes, concept: str) -> str:
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        body: dict[str, Any] = {
            "model": self.model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": concept},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
            "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        }
        async with self._sem:
            for attempt in range(1, 5):
                try:
                    response = await self.client.responses.create(**body)
                    text = getattr(response, "output_text", None) or _output_text(response)
                    log_event("sam", concept=concept, chars=len(text))
                    return text
                except Exception as exc:  # noqa: BLE001 - retry on anything transient
                    status = getattr(exc, "status_code", None)
                    if attempt == 4 or (
                        status is not None and status not in (429, 500, 502, 503, 504)
                    ):
                        raise SamError(f"SAM call failed: {exc.__class__.__name__}: {exc}") from exc
                    log_event("sam_retry", attempt=attempt, status=status)
                    await asyncio.sleep(2**attempt + random.random())
        raise SamError("unreachable")


def _output_text(response: Any) -> str:
    parts = []
    for item in getattr(response, "output", None) or []:
        for c in getattr(item, "content", None) or []:
            t = getattr(c, "text", None)
            if t:
                parts.append(t)
    return "".join(parts)


def decode(raw: str, size: tuple[int, int]) -> list[SamObject]:
    """Parse the model's special-token text into objects with full-frame
    masks. Empty output means no object matched, not an error."""
    if not raw.strip():
        return []
    from meta_sam_parser import (
        SegmentationBoxRecord,
        SegmentationMaskRecord,
        decode_mask_to_raster,
        image_segmentation_format,
    )

    parser = image_segmentation_format().create_parser()
    parser.push(raw)
    from meta_sam_parser import CompletedOutcome

    finish = parser.finish(CompletedOutcome())
    result = finish.result
    w, h = size
    boxes: dict[str, SegmentationBoxRecord] = {}
    masks: dict[str, SegmentationMaskRecord] = {}
    for rec in result.records:
        if isinstance(rec, SegmentationBoxRecord):
            boxes[rec.object_id] = rec
        elif isinstance(rec, SegmentationMaskRecord):
            masks[rec.object_id] = rec  # latest revision wins
    out = []
    for oid, m in masks.items():
        raster = np.frombuffer(decode_mask_to_raster(m.mask), dtype=np.uint8)
        local = raster.reshape((m.mask.height, m.mask.width)).astype(bool)
        full = np.zeros((h, w), dtype=bool)
        b = m.bounds
        left, top = int(round(b.left)), int(round(b.top))
        right, bottom = int(round(b.right)), int(round(b.bottom))
        bw, bh = max(1, right - left), max(1, bottom - top)
        if local.shape != (bh, bw):
            from PIL import Image

            im = Image.fromarray(local.astype(np.uint8) * 255).resize((bw, bh), Image.NEAREST)
            local = np.asarray(im) > 127
        x0, y0 = max(0, left), max(0, top)
        x1, y1 = min(w, right), min(h, bottom)
        if x1 > x0 and y1 > y0:
            full[y0:y1, x0:x1] = local[y0 - top : y1 - top, x0 - left : x1 - left]
        box = boxes.get(oid)
        conf = m.confidence if m.confidence is not None else (box.confidence if box else None)
        out.append(
            SamObject(
                object_id=oid,
                left=box.left if box else float(left),
                top=box.top if box else float(top),
                right=box.right if box else float(right),
                bottom=box.bottom if box else float(bottom),
                confidence=conf,
                mask=full,
            )
        )
    if result.diagnostics:
        log_event(
            "sam_diagnostics",
            count=len(result.diagnostics),
            first=json.dumps(str(result.diagnostics[0].message))[:160],
        )
    return out
