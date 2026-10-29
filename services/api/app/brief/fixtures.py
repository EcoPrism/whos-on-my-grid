"""BRIEF_SOURCE=fixtures: the briefs under fixtures/briefs are the whole
universe. Served by key (`ashburn`) or by brief id, and matched from a typed
address the same way the UI used to do it. A fixture's country is its
`locale.country` (none: the US); a region sees only its own country's."""

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


def country_of(b: dict[str, Any]) -> str:
    """A fixture's ISO country: its locale's, else the US (made before locales)."""
    locale = b.get("locale")
    country = locale.get("country") if isinstance(locale, dict) else None
    return country.upper() if isinstance(country, str) and country else "US"


def _of(country: str) -> dict[str, dict[str, Any]]:
    want = country.upper()
    return {k: b for k, b in all_fixtures().items() if country_of(b) == want}


def resolve_address(text: str, *, country: str = "US") -> str | None:
    """Match a typed address to a fixture key of that country: any token of the
    fixture's display line or key appearing in the input. Port of the old TS
    matcher. Only fixtures whose country is `country` are candidates, so Irish
    text never opens a US brief."""
    q = text.lower()
    if not q.strip():
        return None
    for key, b in _of(country).items():
        tokens = [
            key,
            *b["address"]["display"].lower().replace(",", " ").split(),
            b["address"].get("zip") or b["address"].get("postal_code", ""),
        ]
        if any(len(t) > 2 and t in q for t in tokens):
            return key
    return None


def examples(*, country: str = "US") -> list[dict[str, Any]]:
    """The home page's example cards for one country. `ai_rent_usd_per_month`
    keeps its legacy key and is in `currency`."""
    out = []
    for key, b in _of(country).items():
        locale = b.get("locale") if isinstance(b.get("locale"), dict) else {}
        out.append(
            {
                "key": key,
                "brief_id": b["brief_id"],
                "display": b["address"]["display"],
                "ai_rent_usd_per_month": b["headline"]["ai_rent_usd_per_month"],
                "currency": locale.get("currency") or "USD",
                "language": locale.get("language") or "en-US",
            }
        )
    return out
