"""Brief cache: one JSON file per brief id under data/briefs. The id is a hash
of the address; the address appears only inside the brief's `display` line,
shortened to street and city. Plus an in-process registry so two requests
for the same address during generation share one run."""

import asyncio
import hashlib
import json
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.telemetry import log_event

_ID = re.compile(r"^[0-9a-f]{16}$")

# Everything that shapes a brief besides the address and the models' answers.
_ENGINE_GLOBS = (
    "services/api/app/**/*.py",
    "schema/brief.schema.json",
    "schema/scenario.schema.json",
    "data/equivalences.json",
    # Each region's curated data. JSON (and GeoJSON) only: recordings and imagery
    # tiles stay out of the image (.dockerignore), so a broader glob would give
    # the container a different fingerprint from the machine that built it.
    "data/regions/*/*.json",
    "data/regions/*/hearings/**/*.json",
    "data/regions/*/perception/*.json",
    "data/regions/*/**/*.geojson",
)


@lru_cache(maxsize=1)
def engine_fingerprint() -> str:
    """A hash of the code and curated data that make a brief. A cached brief
    made by a different engine is regenerated on request, so a code change
    can never serve a stale brief. The brief id, and so its link, is unchanged."""
    h = hashlib.sha256()
    for pattern in _ENGINE_GLOBS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if p.is_file():
                h.update(p.relative_to(REPO_ROOT).as_posix().encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:12]


class BriefCache:
    # The field that names the file; ScenarioCache uses "scenario_id".
    id_field = "brief_id"
    kind = "brief"

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, brief_id: str) -> Path | None:
        if not _ID.match(brief_id):
            return None
        return self.dir / f"{brief_id}.json"

    def get(self, brief_id: str, *, current_only: bool = False) -> dict[str, Any] | None:
        """The cached brief. With current_only, a brief made by an older engine
        is treated as absent (the caller regenerates it); without, any brief by
        that id is returned, so an old link still opens."""
        p = self.path(brief_id)
        if p is None or not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            brief = json.load(f)
        if current_only and brief.get("engine") != engine_fingerprint():
            log_event(
                f"{self.kind}_cache_stale", **{self.id_field: brief_id}, engine=brief.get("engine")
            )
            return None
        return brief

    def put(self, brief: dict[str, Any]) -> None:
        p = self.path(brief[self.id_field])
        if p is None:
            raise ValueError("bad brief id")
        brief["engine"] = engine_fingerprint()
        # A unique temp name: two writers of the same id never share a file.
        tmp = p.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)


class Inflight:
    """Join an already-running generation for the same key."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

    def running(self, key: str) -> bool:
        return key in self._tasks

    def start(
        self, key: str, make: Callable[[], Awaitable[dict[str, Any]]]
    ) -> tuple[asyncio.Task[dict[str, Any]], bool]:
        """The running task for `key`, or a new one; True when this call
        started it. Synchronous, so a check just before it cannot race."""
        task = self._tasks.get(key)
        if task is not None:
            return task, False
        task = asyncio.ensure_future(make())
        self._tasks[key] = task
        task.add_done_callback(lambda _t: self._tasks.pop(key, None))
        return task, True

    async def run(self, key: str, make: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        task, _ = self.start(key, make)
        return await asyncio.shield(task)
