"""Brief cache: one JSON file per brief id under data/briefs. The id is a hash
of the address; the address appears only inside the brief's `display` line,
shortened to street and city. Plus an in-process registry so two requests
for the same address during generation share one run."""

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[0-9a-f]{16}$")


class BriefCache:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, brief_id: str) -> Path | None:
        if not _ID.match(brief_id):
            return None
        return self.dir / f"{brief_id}.json"

    def get(self, brief_id: str) -> dict[str, Any] | None:
        p = self.path(brief_id)
        if p is None or not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def put(self, brief: dict[str, Any]) -> None:
        p = self.path(brief["brief_id"])
        if p is None:
            raise ValueError("bad brief id")
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)


class Inflight:
    """Join an already-running generation for the same key."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

    async def run(self, key: str, make: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        task = self._tasks.get(key)
        if task is None:
            task = asyncio.ensure_future(make())
            self._tasks[key] = task
            task.add_done_callback(lambda _t: self._tasks.pop(key, None))
        return await asyncio.shield(task)
