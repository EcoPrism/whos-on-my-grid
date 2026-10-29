"""The cited constants a scenario's arithmetic runs on. data/equivalences.json
first (the home page's figures), then data/scenario_constants.json, merged by
id into one table. Each row names the page it comes from and quotes it
verbatim, so a constant can back a claim the verifier checks like any other.

A file that is absent, or a row that is incomplete, is skipped: the model
leaves out what it cannot cite rather than guess."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.telemetry import log_event

EQUIVALENCES_PATH = REPO_ROOT / "data" / "equivalences.json"
SCENARIO_CONSTANTS_PATH = REPO_ROOT / "data" / "scenario_constants.json"
_REQUIRED = ("id", "value", "unit", "source_title", "source_url", "quote")


@dataclass(frozen=True)
class Constant:
    id: str
    value: float
    unit: str
    as_of: str
    source_title: str
    source_url: str
    quote: str
    checked: str | None = None  # YYYY-MM-DD the quote was last read on the page
    claim: str = ""  # one sentence restating only what the quote says; "" when not curated

    def source(self, now_iso: str) -> dict[str, Any]:
        """The schema's `source` def. retrieved_at is when the quote was last
        checked on the page, as a date-time; now when that is not recorded."""
        checked = self.checked or ""
        retrieved = f"{checked}T00:00:00Z" if len(checked) == 10 else now_iso
        return {
            "title": self.source_title,
            "url": self.source_url,
            "retrieved_at": retrieved,
            "quote": self.quote,
        }


Constants = dict[str, Constant]


def _row(raw: Any) -> Constant | None:
    if not isinstance(raw, dict) or any(not raw.get(k) and raw.get(k) != 0 for k in _REQUIRED):
        return None
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not str(raw["source_url"]).startswith(("https://", "http://")):
        return None
    return Constant(
        id=str(raw["id"]),
        value=float(value),
        unit=str(raw["unit"]),
        as_of=str(raw.get("as_of") or ""),
        source_title=str(raw["source_title"]),
        source_url=str(raw["source_url"]),
        quote=str(raw["quote"]),
        checked=str(raw["checked"]) if raw.get("checked") else None,
        claim=str(raw.get("claim") or ""),
    )


def _read(path: Path) -> list[Constant]:
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("constants", [])
    except (OSError, ValueError, AttributeError) as exc:
        log_event("constants_unreadable", file=path.name, reason=str(exc)[:160])
        return []
    out = []
    for raw in rows if isinstance(rows, list) else []:
        c = _row(raw)
        if c is None:
            log_event("constant_skipped", file=path.name, id=str((raw or {}).get("id", "?"))[:60])
            continue
        out.append(c)
    return out


def load(
    paths: tuple[Path, ...] = (EQUIVALENCES_PATH, SCENARIO_CONSTANTS_PATH),
) -> Constants:
    """Later files override earlier ones by id."""
    table: Constants = {}
    for p in paths:
        for c in _read(p):
            table[c.id] = c
    return table


@lru_cache(maxsize=1)
def default() -> Constants:
    """The committed table, read once per process (a change is a new deploy)."""
    return load()
