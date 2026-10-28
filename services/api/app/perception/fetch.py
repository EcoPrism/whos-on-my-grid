"""Tiles of NAIP imagery on one Web-Mercator grid from two keyless sources.

Earlier vintage: Microsoft Planetary Computer's `naip` STAC collection (ends
at 2023), through its data API crop endpoint, one item at a time. Latest
vintage: USDA FPAC's `conus_naip` image service (latest NAIP only; 2025 for
OH, VA and AZ). Both are asked for the same ground square, so pixel (row,
col) means the same place in both; at 1.2 km the difference between the
crop's lat/lon grid and the Mercator grid is far below a pixel."""

import asyncio
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.ground.facilities import USER_AGENT

R = 6378137.0
TILE_M = 1200
OVERLAP_M = 100
PX = 1200  # 1 m per pixel

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
STAC_ITEM = "https://planetarycomputer.microsoft.com/api/stac/v1/collections/naip/items/{id}"
PC_CROP = "https://planetarycomputer.microsoft.com/api/data/v1/item/crop/{bbox}/{w}x{h}.png"
FPAC = "https://apps.geo.fpac.usda.gov/geo-imagery/rest/services/naip/conus_naip/ImageServer"
PC_SOURCE = "USDA NAIP via Microsoft Planetary Computer"
FPAC_SOURCE = "USDA NAIP via the USDA FPAC imagery service"


def mercator(lat: float, lon: float) -> tuple[float, float]:
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def inverse(x: float, y: float) -> tuple[float, float]:
    return math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2), math.degrees(x / R)


@dataclass(frozen=True)
class Tile:
    id: str
    x0: float
    y0: float
    x1: float
    y1: float
    px: int = PX

    @property
    def bbox4326(self) -> tuple[float, float, float, float]:
        lat0, lon0 = inverse(self.x0, self.y0)
        lat1, lon1 = inverse(self.x1, self.y1)
        return lon0, lat0, lon1, lat1

    @property
    def m_per_px(self) -> float:
        return (self.x1 - self.x0) / self.px

    def latlon(self, row: float, col: float) -> tuple[float, float]:
        return inverse(self.x0 + col * self.m_per_px, self.y1 - row * self.m_per_px)

    @property
    def centre(self) -> tuple[float, float]:
        return inverse((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


def tiles_for(
    lat: float, lon: float, radius_km: float, *, tile_m: int = TILE_M, overlap_m: int = OVERLAP_M
) -> list[Tile]:
    """Square tiles covering the ring, stepping tile_m - overlap_m so a roof on
    a seam is whole in one of them."""
    cx, cy = mercator(lat, lon)
    k = 1 / math.cos(math.radians(lat))  # Mercator metres per ground metre here
    r = radius_km * 1000 * k
    step = (tile_m - overlap_m) * k
    size = tile_m * k
    n = math.ceil(r / step)
    out = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x0 = cx + j * step - size / 2
            y0 = cy + i * step - size / 2
            tcx, tcy = x0 + size / 2, y0 + size / 2
            if math.hypot(tcx - cx, tcy - cy) > r + size / 2:
                continue
            out.append(Tile(f"r{i:+03d}c{j:+03d}", x0, y0, x0 + size, y0 + size))
    out.sort(key=lambda t: math.hypot((t.x0 + t.x1) / 2 - cx, (t.y0 + t.y1) / 2 - cy))
    return out


# --- Planetary Computer -------------------------------------------------------------


class PlanetaryComputer:
    def __init__(self, cache: Path, *, timeout: float = 120.0) -> None:
        self.cache = cache
        self.client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._items: dict[str, list[dict[str, Any]]] = {}

    async def items(
        self, bbox: tuple[float, float, float, float], year: int
    ) -> list[dict[str, Any]]:
        key = f"{year}:{','.join(f'{v:.4f}' for v in bbox)}"
        if key not in self._items:
            r = await self.client.post(
                STAC_SEARCH,
                json={
                    "collections": ["naip"],
                    "bbox": list(bbox),
                    "query": {"naip:year": {"eq": str(year)}},
                    "limit": 10,
                },
            )
            r.raise_for_status()
            self._items[key] = r.json().get("features") or []
        return self._items[key]

    async def tile(self, tile: Tile, year: int) -> tuple[bytes | None, list[dict[str, Any]]]:
        """RGB PNG for the tile from the items covering it (composited when
        the tile straddles quads), and the item records used."""
        path = self.cache / str(year) / f"{tile.id}.png"
        meta = path.with_suffix(".json")
        if path.exists() and meta.exists():
            return path.read_bytes(), json.loads(meta.read_text("utf-8"))
        items = await self.items(tile.bbox4326, year)
        if not items:
            return None, []
        lon0, lat0, lon1, lat1 = tile.bbox4326
        layers: list[tuple[bytes, dict[str, Any]]] = []
        for item in items[:3]:
            url = PC_CROP.format(bbox=f"{lon0},{lat0},{lon1},{lat1}", w=tile.px, h=tile.px)
            r = await self.client.get(
                url,
                params={
                    "collection": "naip",
                    "item": item["id"],
                    "assets": "image",
                    "asset_bidx": "image|1,2,3",
                },
            )
            if r.status_code != 200:
                continue
            layers.append((r.content, item))
        if not layers:
            return None, []
        png, used = composite(layers)
        records = [
            {
                "id": it["id"],
                "date": it["properties"]["datetime"][:10],
                "url": STAC_ITEM.format(id=it["id"]),
                "title": f"NAIP item {it['id']} (Planetary Computer STAC record)",
                "gsd": it["properties"].get("gsd"),
            }
            for it in used
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        meta.write_text(json.dumps(records), "utf-8")
        return png, records

    async def aclose(self) -> None:
        await self.client.aclose()


def composite(layers: list[tuple[bytes, dict[str, Any]]]) -> tuple[bytes, list[dict[str, Any]]]:
    """Stack RGBA crops, most coverage first, filling transparent (no data)
    pixels from the next. Returns an opaque RGB PNG and the items it used."""
    from PIL import Image

    images = [(Image.open(io.BytesIO(b)).convert("RGBA"), it) for b, it in layers]
    images.sort(key=lambda im: -_coverage(im[0]))
    base, used = images[0][0].copy(), [images[0][1]]
    for im, it in images[1:]:
        if _coverage(base) >= 0.999:
            break
        hole = base.split()[3].point(lambda a: 255 if a < 128 else 0)
        base.paste(im, (0, 0), hole)
        used.append(it)
    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue(), used


def _coverage(im: Any) -> float:
    alpha = im.split()[3]
    hist = alpha.histogram()
    opaque = sum(hist[128:])
    return opaque / (im.width * im.height)


# --- USDA FPAC ------------------------------------------------------------------------


class Fpac:
    def __init__(self, cache: Path, *, timeout: float = 120.0) -> None:
        self.cache = cache
        self.client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})

    async def catalog(self, lat: float, lon: float) -> tuple[list[dict[str, Any]], str]:
        """The latest NAIP records at a point: Name (quarter quad, resolution,
        date) and QQDATE. Returns the records and the URL a claim can cite."""
        params = {
            "geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
            "spatialRel": "esriSpatialRelIntersects",
            "where": "Name LIKE 'm_%'",
            "outFields": "Name,ST,QQDATE",
            "returnGeometry": "false",
            "f": "json",
        }
        r = await self.client.get(f"{FPAC}/query", params=params)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"FPAC: {body['error']}")
        records = [f.get("attributes", {}) for f in body.get("features") or []]
        return records, str(r.url)

    async def tile(self, tile: Tile) -> bytes | None:
        path = self.cache / "latest" / f"{tile.id}.png"
        if path.exists():
            return path.read_bytes()
        params = {
            "bbox": f"{tile.x0},{tile.y0},{tile.x1},{tile.y1}",
            "bboxSR": "3857",
            "imageSR": "3857",
            "size": f"{tile.px},{tile.px}",
            "format": "png",
            "f": "image",
        }
        r = await self.client.get(f"{FPAC}/exportImage", params=params)
        if r.status_code != 200 or r.headers.get("content-type", "").startswith("application/json"):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return r.content

    async def aclose(self) -> None:
        await self.client.aclose()


async def fetch_pair(
    pc: PlanetaryComputer, fpac: Fpac, tile: Tile, then_year: int
) -> tuple[bytes | None, list[dict[str, Any]], bytes | None]:
    then, now = await asyncio.gather(pc.tile(tile, then_year), fpac.tile(tile))
    return then[0], then[1], now
