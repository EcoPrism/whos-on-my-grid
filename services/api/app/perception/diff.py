"""From masks to measured change: polygons on the Mercator grid, acreage with
the latitude correction, and the diff between two vintages. Pure functions
over numpy arrays and shapely geometry; no network, no model."""

import math
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from app.perception.fetch import Tile, inverse

SQ_M_PER_ACRE = 4046.8564
MIN_ACRES = 2.0  # a data-center hall; houses and sheds fall out
NEW_IOU = 0.2  # below this overlap with any earlier roof, the roof is new
EXPANSION_GROWTH = 1.3  # a listed roof this much larger than before is an expansion
MAX_VERTICES = 40


@dataclass(frozen=True)
class Roof:
    geom: Polygon  # EPSG:3857 metres
    confidence: float

    @property
    def lat(self) -> float:
        c = self.geom.centroid
        return inverse(c.x, c.y)[0]

    @property
    def lon(self) -> float:
        c = self.geom.centroid
        return inverse(c.x, c.y)[1]

    @property
    def acres(self) -> float:
        return acres(self.geom)


@dataclass(frozen=True)
class Change:
    kind: str  # new | expansion
    roof: Roof
    acres_then: float
    acres_now: float


def acres(geom: Polygon) -> float:
    """Ground acres of a Mercator polygon: the projection stretches lengths by
    1/cos(lat), so areas by 1/cos²(lat)."""
    lat = inverse(geom.centroid.x, geom.centroid.y)[0]
    return round(geom.area * math.cos(math.radians(lat)) ** 2 / SQ_M_PER_ACRE, 2)


def mask_to_polygons(mask: np.ndarray, tile: Tile, confidence: float = 0.8) -> list[Roof]:
    """Connected regions of a binary mask as Mercator polygons."""
    from affine import Affine
    from rasterio import features

    if mask.ndim != 2 or not mask.any():
        return []
    m = tile.m_per_px
    rows, cols = mask.shape
    # The mask may be smaller than the tile (SAM returns a reduced raster).
    sx, sy = (tile.x1 - tile.x0) / cols, (tile.y1 - tile.y0) / rows
    transform = Affine(sx, 0.0, tile.x0, 0.0, -sy, tile.y1)
    out = []
    data = mask.astype(np.uint8)
    for geom, value in features.shapes(data, mask=data.astype(bool), transform=transform):
        if value != 1:
            continue
        poly = shape(geom)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area < (m * m) * 100:  # under 100 px: noise
            continue
        out.append(Roof(poly, confidence))
    return out


def dissolve(roofs: list[Roof], gap_m: float = 3.0) -> list[Roof]:
    """Merge touching or near-touching pieces (tile seams, mask joins) into
    one roof each. Confidence is the area-weighted mean."""
    if not roofs:
        return []
    merged = unary_union([r.geom.buffer(gap_m) for r in roofs]).buffer(-gap_m)
    parts = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
    out = []
    for part in parts:
        if part.is_empty or part.geom_type != "Polygon":
            continue
        inside = [r for r in roofs if r.geom.intersects(part)]
        total = sum(r.geom.area for r in inside) or 1.0
        conf = sum(r.confidence * r.geom.area for r in inside) / total
        out.append(Roof(part, round(conf, 3)))
    return out


def diff(then: list[Roof], now: list[Roof], *, min_acres: float = MIN_ACRES) -> list[Change]:
    """Roofs in `now` of at least min_acres that were not there, or were much
    smaller, in `then`."""
    changes = []
    for roof in now:
        if roof.acres < min_acres:
            continue
        overlapping = [t for t in then if t.geom.intersects(roof.geom)]
        before = unary_union([t.geom for t in overlapping]) if overlapping else None
        inter = roof.geom.intersection(before).area if before is not None else 0.0
        union = roof.geom.union(before).area if before is not None else roof.geom.area
        iou = inter / union if union else 0.0
        if iou < NEW_IOU and inter / roof.geom.area < NEW_IOU:
            changes.append(
                Change(
                    "new",
                    roof,
                    acres(roof.geom.intersection(before)) if before is not None and inter else 0.0,
                    roof.acres,
                )
            )
            continue
        before_acres = acres(before) if before is not None else 0.0
        if before_acres and roof.acres >= EXPANSION_GROWTH * before_acres:
            changes.append(Change("expansion", roof, before_acres, roof.acres))
    changes.sort(key=lambda c: -(c.acres_now - c.acres_then))
    return changes


def ring_latlon(geom: Polygon, max_vertices: int = MAX_VERTICES) -> list[tuple[float, float]]:
    """The outer ring as (lat, lon), simplified until it has few enough points."""
    tol = 1.0
    g = geom
    while len(g.exterior.coords) > max_vertices and tol < 200:
        g = geom.simplify(tol, preserve_topology=True)
        tol *= 1.6
    return [tuple(round(v, 6) for v in inverse(x, y)) for x, y in g.exterior.coords]  # type: ignore[misc]


def distance_m(a: Polygon, lat: float, lon: float) -> float:
    """Ground metres from a point to the polygon edge (0 inside)."""
    from shapely.geometry import Point

    from app.perception.fetch import mercator

    x, y = mercator(lat, lon)
    return a.distance(Point(x, y)) * math.cos(math.radians(lat))
