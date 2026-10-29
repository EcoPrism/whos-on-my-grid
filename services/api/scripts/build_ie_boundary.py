"""Build data/regions/ie/utilities/ie.geojson: ESB Networks' service area as one
MultiPolygon, the union of the four provinces of Ireland (Ulster here is the three
Republic counties, so Northern Ireland is outside by construction).

Source: Tailte Éireann, "Provinces - National Statutory Boundaries - 2019 -
Generalised 20m" (ArcGIS item 1b341039d3344c74b95293012312f44d), CC BY 4.0,
© Tailte Éireann. Generalised boundaries, for reference purposes only.

    cd services/api && uv run --group index python scripts/build_ie_boundary.py

Steps: FeatureServer query (outSR=4326, geometryPrecision=5), make_valid + buffer(0),
unary_union, simplify(0.002, preserve_topology=True), drop parts of 0.00007 deg²
or less (about 0.5 km²: rocks and small islets), set_precision(1e-5). Never
substitute another boundary (Natural Earth and the like are too coarse at the
border). `--source FILE` reads a saved FeatureServer response instead of the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from shapely import make_valid, set_precision
from shapely.geometry import MultiPolygon, Point, mapping, shape
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT = REPO_ROOT / "data" / "regions" / "ie" / "utilities" / "ie.geojson"
SOURCE_URL = (
    "https://services-eu1.arcgis.com/FH5XCsx8rYXqnjF5/arcgis/rest/services/"
    "Provinces___OSi_National_Statutory_Boundaries___Generalised_20m/FeatureServer/0/query"
    "?where=1%3D1&outFields=PROVINCE&outSR=4326&geometryPrecision=5&f=geojson"
)
USER_AGENT = "WhosOnMyGrid/0.1 (+https://github.com/EcoPrism/whos-on-my-grid)"
TOLERANCE = 0.002
MIN_PART_AREA = 0.00007
PRECISION = 1e-5

PROPERTIES = {
    "name": "ESB Networks",
    "raw_name": "ESB Networks DAC",
    "kind": "DSO",
    "customers": 2500000,
    "customers_year": 2025,
    "holding": "ESB Group",
    "website": "https://www.esbnetworks.ie",
    "source_url": "https://www.esbnetworks.ie/about-us/company/publication-scheme/about-esb-networks-dac",
    "source_title": "ESB Networks, About ESB Networks DAC",
    "quote": (
        "ESB Networks DAC, a ringfenced subsidiary within ESB Group, is the licensed "
        "Distribution System Operator (DSO) for Ireland."
    ),
    "claim": "ESB Networks DAC is the licensed Distribution System Operator (DSO) for Ireland.",
    "customers_source_url": "https://www.esbnetworks.ie/about-us/company",
    "customers_quote": (
        "We connected around 43,471 new customers (homes & businesses) in 2025, to make a "
        "total of roughly 2.5 million customers connected."
    ),
    "boundary_source": (
        "Tailte Éireann, Provinces - National Statutory Boundaries - 2019 - Generalised 20m "
        "(ArcGIS item 1b341039d3344c74b95293012312f44d)"
    ),
    "boundary_licence": "CC BY 4.0",
    "boundary_attribution": "© Tailte Éireann",
    "boundary_note": (
        "Generalised boundaries, for reference purposes only; simplified at 0.002 degrees."
    ),
    "simplify_tolerance_deg": TOLERANCE,
}

# (lat, lon): must be inside / outside the result.
INSIDE = {
    "Dublin": (53.3498, -6.2603),
    "Cork": (51.8985, -8.4756),
    "Galway": (53.2707, -9.0568),
    "Dundalk": (54.0090, -6.4049),
    "Clones": (54.1797, -7.2318),
    "Lifford": (54.8337, -7.4797),
}
OUTSIDE = {
    "Belfast": (54.5973, -5.9301),
    "Derry": (54.9966, -7.3086),
    "Strabane": (54.8270, -7.4633),
    "Newry": (54.1751, -6.3402),
}


def fetch() -> dict:
    r = httpx.get(SOURCE_URL, headers={"User-Agent": USER_AGENT}, timeout=120)
    r.raise_for_status()
    return r.json()


def build(fc: dict) -> MultiPolygon:
    feats = fc.get("features") or []
    if len(feats) != 4:
        sys.exit(f"expected 4 provinces, got {len(feats)}")
    merged = unary_union([make_valid(shape(f["geometry"])).buffer(0) for f in feats])
    simple = merged.simplify(TOLERANCE, preserve_topology=True)
    parts = [p for p in getattr(simple, "geoms", [simple]) if p.area > MIN_PART_AREA]
    out = set_precision(MultiPolygon(parts), PRECISION)
    if out.geom_type == "Polygon":
        out = MultiPolygon([out])
    return out


def _rounded(geom: MultiPolygon) -> dict:
    """GeoJSON with coordinates written to 5 decimals (the grid set_precision snapped to)."""
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [[[round(x, 5), round(y, 5)] for x, y in ring] for ring in poly]
            for poly in mapping(geom)["coordinates"]
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, help="a saved FeatureServer GeoJSON response")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    fc = json.loads(args.source.read_text("utf-8")) if args.source else fetch()
    geom = build(fc)
    if not geom.is_valid:
        sys.exit("result is not valid")
    bad = [k for k, (lat, lon) in INSIDE.items() if not geom.contains(Point(lon, lat))]
    bad += [k for k, (lat, lon) in OUTSIDE.items() if geom.contains(Point(lon, lat))]
    if bad:
        sys.exit(f"point checks failed: {bad}")
    doc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": PROPERTIES, "geometry": _rounded(geom)}],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.out} ({len(text.encode('utf-8')):,} bytes, {len(geom.geoms)} parts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
