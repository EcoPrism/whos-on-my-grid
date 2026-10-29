"""The brief cache is keyed by address but stamped with the engine that made
the brief, so a code or data change regenerates rather than serves stale.
The engine is per region: one region's curated-data edit leaves another's
briefs and cards alone. Non-US briefs age out after `ttl_days`, on read and
by the sweep."""

import hashlib
import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.brief import cache as cache_mod
from app.brief.cache import (
    BriefCache,
    code_fingerprint,
    engine_fingerprint,
    region_of,
)

US_ID, IE_ID, IE_FRESH_ID, OLD_ID = (
    "0123456789abcdef",
    "ffefa78202dceea9",
    "aaaaaaaaaaaaaaaa",
    "bbbbbbbbbbbbbbbb",
)
IE_LOCALE = {"country": "IE", "currency": "EUR", "units": "metric", "language": "en-IE"}
US_LOCALE = {"country": "US", "currency": "USD", "units": "us", "language": "en-US"}


def test_engine_fingerprint_is_short_hex_and_stable() -> None:
    fp = engine_fingerprint()
    assert len(fp) == 12
    int(fp, 16)
    assert fp == engine_fingerprint() == engine_fingerprint("us")


def test_cache_skips_a_brief_made_by_another_engine(tmp_path) -> None:
    cache = BriefCache(tmp_path)
    cache.put({"brief_id": "0123456789abcdef", "x": 1})
    fresh = cache.get("0123456789abcdef", current_only=True)
    assert fresh is not None and fresh["engine"] == engine_fingerprint()

    old = {"brief_id": "fedcba9876543210", "engine": "000000000000"}
    cache.path("fedcba9876543210").write_text(json.dumps(old), encoding="utf-8")
    # An old link still opens the brief it was made for...
    assert cache.get("fedcba9876543210") is not None
    # ...but a new request for that address regenerates it.
    assert cache.get("fedcba9876543210", current_only=True) is None


# --- per-region fingerprints, on a temporary repo tree ---------------------------


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A repo with code, the shared files and US curated data only."""
    root = tmp_path / "repo"
    _write(root, "services/api/app/x.py", "x = 1\n")
    _write(root, "schema/brief.schema.json", "{}")
    _write(root, "schema/scenario.schema.json", "{}")
    _write(root, "data/equivalences.json", '{"constants": []}')
    _write(root, "data/regions/us/tariffs.json", '{"entries": []}')
    _write(root, "data/regions/us/hearings/sources.json", "{}")
    _write(root, "data/regions/us/perception/index.json", "{}")
    _write(root, "data/regions/us/hearings/audio/a.mp3", "not hashed")
    monkeypatch.setattr(cache_mod, "REPO_ROOT", root)
    engine_fingerprint.cache_clear()
    code_fingerprint.cache_clear()
    yield root
    engine_fingerprint.cache_clear()
    code_fingerprint.cache_clear()


def _step5_fingerprint(root: Path) -> str:
    """Step 5's single fingerprint, inline: one hash over these globs."""
    globs = (
        "services/api/app/**/*.py",
        "schema/brief.schema.json",
        "schema/scenario.schema.json",
        "data/equivalences.json",
        "data/regions/*/*.json",
        "data/regions/*/hearings/**/*.json",
        "data/regions/*/perception/*.json",
        "data/regions/*/**/*.geojson",
    )
    h = hashlib.sha256()
    for pattern in globs:
        for p in sorted(root.glob(pattern)):
            if p.is_file():
                h.update(p.relative_to(root).as_posix().encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _fresh(region: str = "us") -> str:
    engine_fingerprint.cache_clear()
    code_fingerprint.cache_clear()
    return engine_fingerprint(region)


def test_us_fingerprint_equals_the_step5_digest_with_us_data_only(tree: Path) -> None:
    assert engine_fingerprint("us") == _step5_fingerprint(tree)


def test_an_irish_edit_changes_ie_only(tree: Path) -> None:
    us_before = _fresh("us")
    _write(tree, "data/regions/ie/tariffs.json", '{"entries": []}')
    ie_before = _fresh("ie")
    assert _fresh("us") == us_before
    _write(tree, "data/regions/ie/tariffs.json", '{"entries": [1]}')
    assert _fresh("us") == us_before
    assert _fresh("ie") != ie_before
    _write(tree, "data/regions/ie/utilities/ie.geojson", '{"type": "FeatureCollection"}')
    assert _fresh("us") == us_before


def test_a_us_edit_changes_us_only_and_code_changes_both(tree: Path) -> None:
    _write(tree, "data/regions/ie/tariffs.json", "{}")
    us, ie, code = _fresh("us"), _fresh("ie"), code_fingerprint()
    _write(tree, "data/regions/us/tariffs.json", '{"entries": [1]}')
    assert _fresh("us") != us and _fresh("ie") == ie and code_fingerprint() == code
    us = _fresh("us")
    _write(tree, "services/api/app/x.py", "x = 2\n")
    assert _fresh("us") != us and _fresh("ie") != ie and code_fingerprint() != code


def test_both_regions_stay_cached(tree: Path) -> None:
    engine_fingerprint("us")
    engine_fingerprint("ie")
    engine_fingerprint("us")
    info = engine_fingerprint.cache_info()
    assert info.currsize == 2 and info.hits == 1 and info.maxsize is None


def test_bad_region_id_is_refused() -> None:
    with pytest.raises(ValueError):
        engine_fingerprint("../us")


def test_region_of() -> None:
    assert region_of({}) == "us"
    assert region_of({"locale": None}) == "us"
    assert region_of({"locale": US_LOCALE}) == "us"
    assert region_of({"locale": {"country": "us"}}) == "us"
    assert region_of({"locale": IE_LOCALE}) == "ie"
    assert region_of({"locale": {"country": ""}}) == "us"


def test_put_stamps_the_briefs_own_region(tmp_path: Path) -> None:
    cache = BriefCache(tmp_path)
    cache.put({"brief_id": IE_ID, "locale": IE_LOCALE})
    cache.put({"brief_id": US_ID})
    assert cache.get(IE_ID)["engine"] == engine_fingerprint("ie")
    assert cache.get(US_ID)["engine"] == engine_fingerprint("us")
    assert cache.get(IE_ID, current_only=True) is not None


# --- retention: TTL on read and the sweep ----------------------------------------


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store(cache: BriefCache, brief_id: str, days_ago: float, locale: dict | None) -> None:
    brief = {"brief_id": brief_id, "generated_at": _iso(days_ago)}
    if locale is not None:
        brief["locale"] = locale
    cache.put(brief)


def _cards(cards: Path, brief_id: str) -> list[Path]:
    out = []
    for name in (f"{brief_id}.abc123-def.png", f"{brief_id}.abc123.png"):
        p = cards / "brief" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"png")
        out.append(p)
    return out


def test_ttl_on_read(tmp_path: Path) -> None:
    cache = BriefCache(tmp_path, ttl_days=30)
    _store(cache, IE_ID, 31, IE_LOCALE)
    _store(cache, IE_FRESH_ID, 29, IE_LOCALE)
    _store(cache, US_ID, 400, US_LOCALE)
    _store(cache, OLD_ID, 400, None)
    assert cache.get(IE_ID) is None and cache.get(IE_ID, current_only=True) is None
    assert cache.get(IE_FRESH_ID) is not None
    # US briefs, and briefs made before locales, are never aged out.
    assert cache.get(US_ID) is not None and cache.get(OLD_ID) is not None
    # With ttl 0 the same old Irish brief is served.
    assert BriefCache(tmp_path).get(IE_ID) is not None


def test_ttl_falls_back_to_the_file_time(tmp_path: Path) -> None:
    cache = BriefCache(tmp_path, ttl_days=30)
    cache.put({"brief_id": IE_ID, "locale": IE_LOCALE})
    assert cache.get(IE_ID) is not None
    old = time.time() - 31 * 86_400
    os.utime(cache.path(IE_ID), (old, old))
    assert cache.get(IE_ID) is None


def test_sweep_removes_old_irish_briefs_and_their_cards(tmp_path: Path) -> None:
    briefs, cards = tmp_path / "briefs", tmp_path / "cards"
    cache = BriefCache(briefs, ttl_days=30)
    _store(cache, IE_ID, 31, IE_LOCALE)
    _store(cache, IE_FRESH_ID, 1, IE_LOCALE)
    _store(cache, US_ID, 400, US_LOCALE)
    _store(cache, OLD_ID, 400, None)
    old_cards = _cards(cards, IE_ID)
    kept_cards = _cards(cards, IE_FRESH_ID) + _cards(cards, US_ID)
    (briefs / "notes.json").write_text("{}", encoding="utf-8")  # not a brief id: left alone

    assert cache.sweep(cards) == 1
    assert not cache.path(IE_ID).exists()
    assert not any(p.exists() for p in old_cards)
    assert all(p.exists() for p in kept_cards)
    for kept in (IE_FRESH_ID, US_ID, OLD_ID):
        assert cache.path(kept).exists(), kept
    assert (briefs / "notes.json").exists()
    assert cache.sweep(cards) == 0


def test_sweep_ages_out_cards_of_an_earlier_generation(tmp_path: Path) -> None:
    """A brief regenerated on day 20 is not expired on day 31, but the card drawn
    from its day-0 generation is past retention and goes. US cards stay; a card
    whose brief is gone goes once it is past the TTL, not before."""
    briefs, cards = tmp_path / "briefs", tmp_path / "cards"
    cache = BriefCache(briefs, ttl_days=30)
    _store(cache, IE_ID, 11, IE_LOCALE)  # regenerated: the current generation is young
    _store(cache, US_ID, 400, US_LOCALE)
    old = time.time() - 31 * 86_400
    stale_ie = cards / "brief" / f"{IE_ID}.engA-v0.png"
    current_ie = cards / "brief" / f"{IE_ID}.engB-v1.png"
    us_card = cards / "brief" / f"{US_ID}.engA-v0.png"
    orphan_old = cards / "brief" / f"{OLD_ID}.engA-v0.png"
    orphan_new = cards / "brief" / f"{IE_FRESH_ID}.engA-v0.png"
    for p in (stale_ie, current_ie, us_card, orphan_old, orphan_new):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"png")
    for p in (stale_ie, us_card, orphan_old):
        os.utime(p, (old, old))

    assert cache.sweep(cards) == 0  # no brief expired
    assert not stale_ie.exists() and not orphan_old.exists()
    assert current_ie.exists() and us_card.exists() and orphan_new.exists()
    assert cache.path(IE_ID).exists() and cache.path(US_ID).exists()


def test_sweep_without_cards_dir_and_with_ttl_zero(tmp_path: Path) -> None:
    keep = BriefCache(tmp_path)
    _store(keep, IE_ID, 999, IE_LOCALE)
    assert keep.sweep(tmp_path / "cards") == 0
    assert keep.path(IE_ID).exists()
    assert BriefCache(tmp_path, ttl_days=30).sweep() == 1
    assert not keep.path(IE_ID).exists()


def test_sweep_skips_unreadable_files(tmp_path: Path) -> None:
    cache = BriefCache(tmp_path, ttl_days=1)
    cache.path(IE_ID).write_text("{not json", encoding="utf-8")
    assert cache.sweep() == 0 and cache.path(IE_ID).exists()
