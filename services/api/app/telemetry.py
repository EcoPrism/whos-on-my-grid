"""Structured event logging: one JSON line per event, ``EVT {"evt": ...}``.

Never log an address. Events carry the brief id (a hash), section ids,
durations and token counts only.
"""

import json
import logging
import time

_start = time.monotonic()

logger = logging.getLogger("grid.telemetry")


def uptime_ms() -> int:
    return int((time.monotonic() - _start) * 1000)


def log_event(event: str, **fields: object) -> None:
    logger.info("EVT %s", json.dumps({"evt": event, **fields}, default=str, separators=(",", ":")))
