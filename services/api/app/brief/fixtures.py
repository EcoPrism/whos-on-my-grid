"""BRIEF_SOURCE=fixtures: the five briefs at the repo root are the whole
universe. Served by key (`ashburn`) or by brief id, and matched from a typed
address the same way the UI used to do it."""

import json
from functools import lru_cache
from typing import Any

from app.config import REPO_ROOT

FIXTURES_DIR = REPO_ROOT / "fixtures" / "briefs"


@lru_cache
def all_fixtures() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            out[path.stem] = json.load(f)
    return out


def by_key(key: str) -> dict[str, Any] | None:
    return all_fixtures().get(key)


def by_id(brief_id: str) -> dict[str, Any] | None:
    for b in all_fixtures().values():
        if b["brief_id"] == brief_id:
            return b
    return None


def resolve_address(text: str) -> str | None:
    """Match a typed address to a fixture key: any token of the fixture's
    display line or key appearing in the input. Port of the old TS matcher."""
    q = text.lower()
    if not q.strip():
        return None
    for key, b in all_fixtures().items():
        tokens = [
            key,
            *b["address"]["display"].lower().replace(",", " ").split(),
            b["address"]["zip"],
        ]
        if any(len(t) > 2 and t in q for t in tokens):
            return key
    return None


def examples() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "brief_id": b["brief_id"],
            "display": b["address"]["display"],
            "ai_rent_usd_per_month": b["headline"]["ai_rent_usd_per_month"],
        }
        for key, b in all_fixtures().items()
    ]
