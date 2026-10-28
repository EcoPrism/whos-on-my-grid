"""The perception indexer's pure parts: the tile grid, masks to acres, and
the diff between two vintages. No network, no model."""

import numpy as np
import pytest

pytest.importorskip("shapely")
pytest.importorskip("rasterio")

from app.ground.imagery import ImageryIndex  # noqa: E402
from app.perception.diff import acres, diff, dissolve, mask_to_polygons, ring_latlon  # noqa: E402
from app.perception.fetch import Tile, inverse, mercator, tiles_for  # noqa: E402

LAT, LON = 40.08, -82.753


def tile_at(lat: float, lon: float, size_m: float = 1200) -> Tile:
    x, y = mercator(lat, lon)
    k = 1 / np.cos(np.radians(lat))
    s = size_m * k
    return Tile("t", x - s / 2, y - s / 2, x + s / 2, y + s / 2)


def test_tiles_cover_the_ring_and_overlap() -> None:
    tiles = tiles_for(LAT, LON, 8.05)
    assert 180 <= len(tiles) <= 260
    # The first tile is centred on the address; its corners are 1.2 km apart on the ground.
    t = tiles[0]
    clat, clon = t.centre
    assert abs(clat - LAT) < 1e-4 and abs(clon - LON) < 1e-4
    lon0, lat0, lon1, lat1 = t.bbox4326
    assert abs((lat1 - lat0) * 111_320 - 1200) < 5
    # Neighbouring tiles share 100 m.
    xs = sorted({round(t.x0) for t in tiles})
    assert abs((xs[1] - xs[0]) * np.cos(np.radians(LAT)) - 1100) < 2
    assert inverse(*mercator(LAT, LON)) == pytest.approx((LAT, LON))


def test_mask_becomes_a_polygon_with_ground_acres() -> None:
    tile = tile_at(LAT, LON)
    mask = np.zeros((1200, 1200), dtype=bool)
    mask[500:600, 300:500] = True  # 100 m x 200 m = 20,000 m² = 4.94 acres
    roofs = mask_to_polygons(mask, tile)
    assert len(roofs) == 1
    assert roofs[0].acres == pytest.approx(4.94, abs=0.05)
    assert abs(roofs[0].lat - LAT) < 0.01 and abs(roofs[0].lon - LON) < 0.01
    ring = ring_latlon(roofs[0].geom)
    assert 5 <= len(ring) <= 40 and all(len(p) == 2 for p in ring)


def test_small_reduced_masks_scale_to_the_tile() -> None:
    tile = tile_at(LAT, LON)
    mask = np.zeros((300, 300), dtype=bool)  # SAM may return a quarter-size raster
    mask[100:125, 100:150] = True  # 100 m x 200 m on the ground
    roofs = mask_to_polygons(mask, tile)
    assert len(roofs) == 1 and roofs[0].acres == pytest.approx(4.94, abs=0.1)


def test_diff_finds_new_and_expanded_roofs_only() -> None:
    tile = tile_at(LAT, LON)

    def roof(r0, r1, c0, c1):
        m = np.zeros((1200, 1200), dtype=bool)
        m[r0:r1, c0:c1] = True
        return mask_to_polygons(m, tile)[0]

    then = [roof(100, 200, 100, 300), roof(600, 700, 600, 800)]
    now = [
        roof(100, 200, 100, 300),  # unchanged
        roof(600, 700, 600, 1000),  # doubled: expansion
        roof(900, 1000, 100, 300),  # new 4.9 acres
        roof(900, 905, 900, 920),  # tiny: ignored
    ]
    changes = diff(then, now)
    kinds = sorted((c.kind, round(c.acres_then), round(c.acres_now)) for c in changes)
    assert kinds == [("expansion", 5, 10), ("new", 0, 5)]


def test_dissolve_merges_pieces_across_a_seam() -> None:
    tile = tile_at(LAT, LON)
    a = np.zeros((1200, 1200), dtype=bool)
    a[100:200, 100:200] = True
    b = np.zeros((1200, 1200), dtype=bool)
    b[100:200, 201:300] = True  # one pixel gap
    roofs = dissolve(mask_to_polygons(a, tile) + mask_to_polygons(b, tile))
    assert len(roofs) == 1 and roofs[0].acres == pytest.approx(acres(roofs[0].geom))
    assert roofs[0].acres == pytest.approx(4.9, abs=0.2)


def test_imagery_index_reads_an_area_file(tmp_path) -> None:
    import json

    area = {
        "area": {"id": "x", "name": "X", "state": "OH", "county": "Licking", "lat": LAT, "lon": LON, "radius_km": 8.05},
        "indexed_at": "2026-10-28T00:00:00Z",
        "model": "sam-3.1",
        "vintages": {
            "then": {"year": 2023, "source": "PC", "items": [{"id": "a", "date": "2023-05-21", "url": "https://example.org/a", "title": "A"}]},
            "now": {"year": 2025, "source": "FPAC", "items": [{"id": "b", "date": "2025-07-05", "url": "https://example.org/b", "title": "B"}]},
        },
        "sites": [
            {"id": "s1", "label": "Near", "kind": "new", "lat": LAT + 0.01, "lon": LON, "footprint_acres_then": 0, "footprint_acres_now": 12.0, "in_database": False, "near_cluster": True, "facility": None, "polygon": [[LAT, LON], [LAT, LON + 0.001], [LAT + 0.001, LON]]},
            {"id": "s2", "label": "Far", "kind": "new", "lat": LAT + 0.2, "lon": LON, "footprint_acres_then": 0, "footprint_acres_now": 30.0, "in_database": False, "near_cluster": False, "facility": None, "polygon": []},
            {"id": "s3", "label": "Other", "kind": "new", "lat": LAT - 0.02, "lon": LON, "footprint_acres_then": 0, "footprint_acres_now": 3.0, "in_database": False, "near_cluster": False, "facility": None, "polygon": []},
        ],
    }  # fmt: skip
    (tmp_path / "x.json").write_text(json.dumps(area), "utf-8")
    (tmp_path / "areas.json").write_text("{}", "utf-8")
    idx = ImageryIndex(tmp_path)
    r = idx.near(LAT, LON)
    assert r is not None and r.vintages == (2023, 2025)
    assert [s.label for s in r.sites] == ["Near", "Other"]  # Far is 22 km out; counted first
    assert r.sites[0].distance_km == pytest.approx(1.11, abs=0.02)
    assert r.new_acres == 12.0
    # An address well outside the area is not covered.
    assert idx.near(LAT + 0.1, LON) is None
