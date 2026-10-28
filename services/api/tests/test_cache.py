"""The brief cache is keyed by address but stamped with the engine that made
the brief, so a code or data change regenerates rather than serves stale."""

import json

from app.brief.cache import BriefCache, engine_fingerprint


def test_engine_fingerprint_is_short_hex_and_stable() -> None:
    fp = engine_fingerprint()
    assert len(fp) == 12
    int(fp, 16)
    assert fp == engine_fingerprint()


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
