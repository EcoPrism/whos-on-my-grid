"""Brief cache: one JSON file per brief id under data/briefs. The id is a hash
of the address; the address appears only inside the brief's `display` line,
shortened to street and city. Plus an in-process registry so two requests
for the same address during generation share one run."""

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.telemetry import log_event

_ID = re.compile(r"^[0-9a-f]{16}$")

# Everything that shapes a brief besides the address and the models' answers:
# the code and shared files every region reads...
_CORE_GLOBS = (
    "services/api/app/**/*.py",
    "schema/brief.schema.json",
    "schema/scenario.schema.json",
    "data/equivalences.json",
)
# ...and one region's curated data, `{region}` filled with its id. JSON (and
# GeoJSON) only: recordings and imagery tiles stay out of the image
# (.dockerignore), so a broader glob would give the container a different
# fingerprint from the machine that built it.
_REGION_GLOBS = (
    "data/regions/{region}/*.json",
    "data/regions/{region}/hearings/**/*.json",
    "data/regions/{region}/perception/*.json",
    "data/regions/{region}/**/*.geojson",
)
# Every file any region's fingerprint can hash (the fingerprint coverage test).
_ENGINE_GLOBS = _CORE_GLOBS + tuple(g.format(region="*") for g in _REGION_GLOBS)
_REGION_ID = re.compile(r"^[a-z]{2,8}$")


def _hash(patterns: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for pattern in patterns:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if p.is_file():
                h.update(p.relative_to(REPO_ROOT).as_posix().encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:12]


@cache
def engine_fingerprint(region_id: str = "us") -> str:
    """A hash of the code, the shared files and one region's curated data: what
    makes that region's briefs. A cached brief made by a different engine is
    regenerated on request, so a code change can never serve a stale brief; an
    edit to another region's data leaves this region's briefs alone. The brief
    id, and so its link, is unchanged. With only US data on disk the US value
    equals the single fingerprint of step 5."""
    if not _REGION_ID.match(region_id):
        raise ValueError(f"bad region id {region_id!r}")
    return _hash(_CORE_GLOBS + tuple(g.format(region=region_id) for g in _REGION_GLOBS))


@cache
def code_fingerprint() -> str:
    """The code and shared files alone, no region's data."""
    return _hash(_CORE_GLOBS)


def region_of(brief: dict[str, Any]) -> str:
    """The region that made a brief: "us" for a brief with no locale (made
    before regions) or a US one, else its country in lower case ("ie")."""
    locale = brief.get("locale")
    country = locale.get("country") if isinstance(locale, dict) else None
    if not isinstance(country, str) or not country or country.upper() == "US":
        return "us"
    return country.lower()


class BriefCache:
    # The field that names the file; ScenarioCache uses "scenario_id".
    id_field = "brief_id"
    kind = "brief"

    def __init__(self, directory: Path, *, ttl_days: int = 0) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        # Non-US briefs older than this many days are removed (sweep) and not
        # served (get). 0 keeps every brief. US briefs are never aged out.
        self.ttl_days = ttl_days

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
        if self.expired(brief, p):
            # Past the region's retention: not served, and the sweep removes it.
            log_event(f"{self.kind}_cache_expired", **{self.id_field: brief_id})
            return None
        if current_only and brief.get("engine") != engine_fingerprint(region_of(brief)):
            log_event(
                f"{self.kind}_cache_stale", **{self.id_field: brief_id}, engine=brief.get("engine")
            )
            return None
        return brief

    def put(self, brief: dict[str, Any]) -> None:
        p = self.path(brief[self.id_field])
        if p is None:
            raise ValueError("bad brief id")
        brief["engine"] = engine_fingerprint(region_of(brief))
        # A unique temp name: two writers of the same id never share a file.
        tmp = p.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)

    def expired(self, brief: dict[str, Any], path: Path) -> bool:
        """A non-US brief made more than `ttl_days` ago. Its age is its
        `generated_at`, else the file's modification time. US briefs, and every
        brief while ttl_days is 0, never expire."""
        if self.ttl_days <= 0 or region_of(brief) == "us":
            return False
        made = _timestamp(brief.get("generated_at"))
        if made is None:
            try:
                made = path.stat().st_mtime
            except OSError:
                return False
        return time.time() - made > self.ttl_days * 86_400

    def sweep(self, cards_dir: Path | None = None) -> int:
        """Remove non-US briefs older than `ttl_days`, and their card PNGs under
        cards_dir/brief/. Returns how many briefs were removed. Retention is
        enforced on disk here, not only by `get` refusing to serve. Logs ids only."""
        if self.ttl_days <= 0:
            return 0
        removed = 0
        for p in sorted(self.dir.glob("*.json")):
            if not _ID.match(p.stem):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    brief = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(brief, dict) or not self.expired(brief, p):
                continue
            try:
                p.unlink()
            except FileNotFoundError:
                continue
            removed += 1
            if cards_dir is not None:
                for card in (cards_dir / "brief").glob(f"{p.stem}.*.png"):
                    card.unlink(missing_ok=True)
        cards = self._sweep_cards(cards_dir) if cards_dir is not None else 0
        if removed or cards:
            log_event(
                f"{self.kind}_cache_swept", removed=removed, cards=cards, ttl_days=self.ttl_days
            )
        return removed

    def _sweep_cards(self, cards_dir: Path) -> int:
        """Card PNGs older than `ttl_days` whose brief is not a US one: a card from
        an earlier generation of a brief that has since been regenerated (a new
        engine, or an expired brief asked for again), or one whose brief is gone.
        Such a card outlives its brief's retention otherwise, since the sweep above
        only sees the brief's current `generated_at`. A card is rendered after its
        brief, so a current card is never older than its unexpired brief."""
        limit = time.time() - self.ttl_days * 86_400
        regions: dict[str, str | None] = {}
        removed = 0
        for card in sorted((cards_dir / "brief").glob("*.png")):
            brief_id = card.name.split(".", 1)[0]
            if not _ID.match(brief_id):
                continue
            try:
                if card.stat().st_mtime >= limit:
                    continue
            except OSError:
                continue
            if brief_id not in regions:
                regions[brief_id] = self._region_on_disk(brief_id)
            if regions[brief_id] == "us":
                continue
            card.unlink(missing_ok=True)
            removed += 1
        return removed

    def _region_on_disk(self, brief_id: str) -> str | None:
        """The region of the cached brief by this id; None when it is gone or
        unreadable (its card is then an orphan, and aged out like a non-US one)."""
        p = self.path(brief_id)
        if p is None:
            return None
        try:
            with open(p, encoding="utf-8") as f:
                brief = json.load(f)
        except (OSError, ValueError):
            return None
        return region_of(brief) if isinstance(brief, dict) else None


def _timestamp(value: Any) -> float | None:
    """An ISO 8601 date-time as epoch seconds; None when absent or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


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
