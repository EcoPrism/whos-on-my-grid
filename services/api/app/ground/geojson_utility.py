"""Serving network operator from a curated GeoJSON map, point in polygon. The
map is a committed file (data/regions/<id>/utilities/*.geojson) whose features
carry the operator's name and the page that names it, so the claim cites that
page and quotes it, never the map. Pure Python: the API does not install shapely.

A point inside no feature returns None (the brief says it is outside the map);
a point just outside the generalised boundary but in the map's country still
matches, within `tolerance_deg`. A file that cannot be read raises from `locate`,
which gather_ground turns into `failure_note`."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.ground.types import Utility

if TYPE_CHECKING:
    from app.geocode import GeocodeResult

Ring = list[tuple[float, float]]  # (lon, lat)
EDGE_TOLERANCE_DEG = 0.003
ESB_FAILURE_NOTE = (
    "The ESB Networks map file could not be read; the serving network operator is not known."
)


@dataclass(frozen=True)
class _Polygon:
    outer: Ring
    holes: tuple[Ring, ...]
    bbox: tuple[float, float, float, float]  # min lon, min lat, max lon, max lat


@dataclass(frozen=True)
class _Feature:
    props: dict[str, Any]
    polygons: tuple[_Polygon, ...]


def _ring(coords: Any) -> Ring:
    ring = [(float(p[0]), float(p[1])) for p in coords]
    if len(ring) < 3:
        raise ValueError("ring with fewer than 3 points")
    return ring


def _polygon(rings: Any) -> _Polygon:
    outer = _ring(rings[0])
    lons = [p[0] for p in outer]
    lats = [p[1] for p in outer]
    return _Polygon(
        outer, tuple(_ring(r) for r in rings[1:]), (min(lons), min(lats), max(lons), max(lats))
    )


def _polygons(geometry: dict[str, Any]) -> tuple[_Polygon, ...]:
    kind = geometry.get("type")
    if kind == "Polygon":
        return (_polygon(geometry["coordinates"]),)
    if kind == "MultiPolygon":
        return tuple(_polygon(p) for p in geometry["coordinates"])
    raise ValueError(f"unsupported geometry {kind!r}")


def load_features(path: Path) -> list[_Feature]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    feats = raw.get("features") if raw.get("type") == "FeatureCollection" else [raw]
    out = [_Feature(dict(ft.get("properties") or {}), _polygons(ft["geometry"])) for ft in feats]
    if not out:
        raise ValueError("map has no features")
    return out


def _in_ring(lon: float, lat: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polygon(lon: float, lat: float, p: _Polygon) -> bool:
    x0, y0, x1, y1 = p.bbox
    if not (x0 <= lon <= x1 and y0 <= lat <= y1):
        return False
    return _in_ring(lon, lat, p.outer) and not any(_in_ring(lon, lat, h) for h in p.holes)


def _segment_dist(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _edge_dist(lon: float, lat: float, p: _Polygon, limit: float) -> float:
    """Distance in degrees from the point to the polygon's outer edge, or inf
    when the bounding box is already farther than `limit`."""
    x0, y0, x1, y1 = p.bbox
    if lon < x0 - limit or lon > x1 + limit or lat < y0 - limit or lat > y1 + limit:
        return math.inf
    ring = p.outer
    return min(_segment_dist(lon, lat, ring[i - 1], ring[i]) for i in range(len(ring)))


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _utility(props: dict[str, Any], candidates: int) -> Utility:
    return Utility(
        name=str(props["name"]),
        raw_name=str(props.get("raw_name") or props["name"]),
        kind=str(props.get("kind") or "DSO"),
        customers=_int(props.get("customers")),
        holding=props.get("holding"),
        source_url=str(props["source_url"]),
        candidates=candidates,
        website=props.get("website"),
        source_title=props.get("source_title"),
        quote=props.get("quote"),
        claim_text=props.get("claim"),
    )


class GeoJsonUtility:
    """A UtilityProvider over one curated GeoJSON file. Overlapping features:
    the one with the most customers wins and `candidates` says how many held the point."""

    name = "geojson-utility"
    failure_note = ESB_FAILURE_NOTE

    def __init__(
        self,
        path: Path,
        *,
        country: str = "IE",
        tolerance_deg: float = EDGE_TOLERANCE_DEG,
        failure_note: str | None = None,
    ) -> None:
        self.path = path
        self.country = country.upper()
        self.tolerance_deg = tolerance_deg
        if failure_note is not None:
            self.failure_note = failure_note
        self._features: list[_Feature] | None = None

    def features(self) -> list[_Feature]:
        if self._features is None:
            self._features = load_features(self.path)
        return self._features

    def match(self, lat: float, lon: float, country: str | None = None) -> Utility | None:
        feats = self.features()
        inside = [f for f in feats if any(_in_polygon(lon, lat, p) for p in f.polygons)]
        if not inside and (country or "").upper() == self.country and self.tolerance_deg > 0:
            near = [
                (min(_edge_dist(lon, lat, p, self.tolerance_deg) for p in f.polygons), f)
                for f in feats
            ]
            near = [(d, f) for d, f in near if d <= self.tolerance_deg]
            if near:
                inside = [min(near, key=lambda x: x[0])[1]]
        if not inside:
            return None
        best = max(inside, key=lambda f: _int(f.props.get("customers")) or -1)
        return _utility(best.props, len(inside))

    async def locate(self, geo: "GeocodeResult") -> Utility | None:
        return self.match(geo.lat, geo.lon, geo.country)
