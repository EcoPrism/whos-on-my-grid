"""Index one area from `data/regions/us/perception/areas.json`:

    uv run python -m app.perception.index --area new_albany
    uv run python -m app.perception.index --area new_albany --tiles 12 --dry-run

For every tile in the ring: both vintages are fetched (cached under
data/ground/naip), SAM 3.1 segments the concept in each, the masks become
polygons, and the two vintages are diffed. Roofs that are new or much larger
are labelled against the facility database and written to
`data/regions/us/perception/<area>.json` for the brief to read."""

import argparse
import asyncio
import json
import math
import sys
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.ground import get_ground
from app.ground.facilities import compass, haversine_km
from app.ground.types import GroundFacility
from app.perception.diff import (
    Change,
    Roof,
    diff,
    dissolve,
    distance_m,
    mask_to_polygons,
    ring_latlon,
)
from app.perception.fetch import (
    FPAC_SOURCE,
    PC_SOURCE,
    Fpac,
    PlanetaryComputer,
    Tile,
    fetch_pair,
    tiles_for,
)
from app.perception.sam import SamClient

CONCEPT = "building"
IN_DATABASE_M = 400
NEAR_CLUSTER_M = 1500
KM_TO_MI = 0.621371


def load_area(area_id: str) -> dict[str, Any]:
    path = get_settings().perception_path / "areas.json"
    for a in json.loads(path.read_text("utf-8")).get("areas", []):
        if a["id"] == area_id:
            return a
    sys.exit(f"area {area_id!r} is not in {path}")


def qq_date(value: Any) -> str:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, UTC).strftime("%Y-%m-%d")
    return str(value)[:10]


async def segment_tile(
    sam: SamClient, tile: Tile, png: bytes, vintage: str, concept: str
) -> list[Roof]:
    objects = await sam.segment(
        png, concept, size=(tile.px, tile.px), cache_key=f"{tile.id}_{vintage}_{concept}"
    )
    roofs: list[Roof] = []
    for o in objects:
        roofs.extend(
            mask_to_polygons(o.mask, tile, o.confidence if o.confidence is not None else 0.7)
        )
    return roofs


def label(change: Change, facilities: list[GroundFacility], area: dict[str, Any]) -> dict[str, Any]:
    roof = change.roof
    nearest: tuple[float, GroundFacility] | None = None
    for f in facilities:
        d = distance_m(roof.geom, f.lat, f.lon)
        if nearest is None or d < nearest[0]:
            nearest = (d, f)
    in_db = nearest is not None and nearest[0] <= IN_DATABASE_M
    near = nearest is not None and nearest[0] <= NEAR_CLUSTER_M
    facility = nearest[1].name if nearest and near else None
    heading = compass(float(area["lat"]), float(area["lon"]), roof.lat, roof.lon)
    if in_db and change.kind == "expansion":
        text = f"{facility} expansion"
    elif in_db:
        text = f"New roof at {facility}"
    elif near:
        text = f"New large roof beside {facility} (unlisted)"
    else:
        text = f"Large roof to the {heading}, unidentified"
    return {
        "label": text,
        "kind": change.kind,
        "lat": round(roof.lat, 6),
        "lon": round(roof.lon, 6),
        "footprint_acres_then": round(change.acres_then, 1),
        "footprint_acres_now": round(change.acres_now, 1),
        "in_database": in_db,
        "near_cluster": near,
        "facility": facility,
        "nearest_facility_m": round(nearest[0]) if nearest else None,
        "polygon": [list(p) for p in ring_latlon(roof.geom)],
        "confidence": round(roof.confidence, 2),
    }


async def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--area", required=True)
    ap.add_argument("--concept", default=CONCEPT, help="SAM concept prompt (one noun phrase)")
    ap.add_argument("--tiles", type=int, help="only the N tiles nearest the centre")
    ap.add_argument("--dry-run", action="store_true", help="fetch imagery, skip SAM and the diff")
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    settings = get_settings()
    area = load_area(args.area)
    lat, lon, radius = float(area["lat"]), float(area["lon"]), float(area["radius_km"])
    then_year = int(area["then"]["year"])
    tiles = tiles_for(lat, lon, radius)
    if args.tiles:
        tiles = tiles[: args.tiles]
    print(
        f"{area['name']}: {len(tiles)} tiles of {tiles[0].px} px, "
        f"{then_year} vs {area['now']['year']}"
    )

    cache = settings.ground_path / "naip" / area["id"]
    pc, fpac = PlanetaryComputer(cache), Fpac(cache)
    sam = (
        None
        if args.dry_run
        else SamClient(
            api_key=settings.meta_api_key,
            base_url=settings.meta_base_url,
            model=settings.sam_model,
            cache=cache / "sam",
            concurrency=args.concurrency,
        )
    )
    sem = asyncio.Semaphore(args.concurrency)
    then_items: dict[str, dict[str, Any]] = {}
    then_roofs: list[Roof] = []
    now_roofs: list[Roof] = []
    stats = {"tiles": 0, "fetched": 0, "missing": 0, "objects_then": 0, "objects_now": 0}

    async def one(tile: Tile) -> None:
        async with sem:
            then_png, items, now_png = await fetch_pair(pc, fpac, tile, then_year)
            stats["tiles"] += 1
            if then_png is None or now_png is None:
                stats["missing"] += 1
                return
            stats["fetched"] += 1
            for it in items:
                then_items.setdefault(it["id"], it)
            if sam is None:
                return
            a, b = await asyncio.gather(
                segment_tile(sam, tile, then_png, str(then_year), args.concept),
                segment_tile(sam, tile, now_png, "now", args.concept),
            )
            stats["objects_then"] += len(a)
            stats["objects_now"] += len(b)
            then_roofs.extend(a)
            now_roofs.extend(b)
            if stats["tiles"] % 10 == 0:
                print(
                    f"  {stats['tiles']}/{len(tiles)} tiles, roofs so far "
                    f"{len(then_roofs)} / {len(now_roofs)}"
                )

    try:
        await asyncio.gather(*(one(t) for t in tiles))
        now_records, catalog_url = await fpac.catalog(lat, lon)
    finally:
        await pc.aclose()
        await fpac.aclose()
    print(
        f"  fetched {stats['fetched']} tile pairs, {stats['missing']} missing; "
        f"objects {stats['objects_then']} / {stats['objects_now']}"
    )
    if sam is None:
        return

    then_d, now_d = dissolve(then_roofs), dissolve(now_roofs)
    changes = diff(then_d, now_d)
    print(f"  roofs after dissolve {len(then_d)} / {len(now_d)}; changes {len(changes)}")

    ground = get_ground(settings)
    assert ground.facilities is not None
    facilities, notes = await ground.facilities.near(lat, lon, radius + 2.0)
    print(f"  facility database: {len(facilities)} within {radius + 2:.0f} km {notes or ''}")

    sites = []
    for n, c in enumerate(changes, start=1):
        s = label(c, facilities, area)
        s["id"] = f"{area['id']}-{n}"
        d = haversine_km(lat, lon, s["lat"], s["lon"])
        if d > radius:
            continue
        sites.append(s)
    counted = [s for s in sites if s["in_database"] or s["near_cluster"]]
    acres = sum(s["footprint_acres_now"] - s["footprint_acres_then"] for s in counted)
    out = {
        "area": area,
        "indexed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": settings.sam_model,
        "concept": args.concept,
        "tiles": len(tiles),
        "tile_m": round(tiles[0].m_per_px * tiles[0].px * math.cos(math.radians(lat))),
        "vintages": {
            "then": {
                "year": then_year,
                "source": PC_SOURCE,
                "items": [
                    {k: v for k, v in it.items() if k in ("id", "date", "url", "title")}
                    for it in sorted(then_items.values(), key=lambda i: i["id"])
                ],
            },
            "now": {
                "year": int(area["now"]["year"]),
                "source": FPAC_SOURCE,
                "items": [
                    {
                        "id": r.get("Name"),
                        "date": qq_date(r.get("QQDATE")),
                        "url": catalog_url,
                        "title": f"NAIP {area['now']['year']} quarter quad {r.get('Name')} "
                        "(USDA FPAC catalog record)",
                    }
                    for r in now_records
                    if r.get("Name")
                ],
            },
        },
        "stats": {
            **stats,
            "roofs_then": len(then_d),
            "roofs_now": len(now_d),
            "changes": len(changes),
            "counted": len(counted),
            "counted_acres": round(acres, 1),
        },
        "sites": sites,
    }
    dest = settings.perception_path / f"{area['id']}.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {dest}: {len(sites)} sites, {len(counted)} counted, {acres:.0f} acres")


if __name__ == "__main__":
    asyncio.run(main())
