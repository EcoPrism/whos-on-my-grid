"""What SAM 3.1 measured on two NAIP vintages, read from the perception index
(`data/perception/<area>.json`, written offline by `app.perception.index`).
No network and no model call per brief: the index is a committed data
product, so the brief says the same thing on every machine."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.ground.facilities import haversine_km
from app.ground.types import (
    FIVE_MILES_KM,
    ConstructionSite,
    ImageryItem,
    ImageryResult,
    ImageryVintage,
)

PERCEPTION_DIR = REPO_ROOT / "data" / "perception"
SAM_MODEL_ID = "sam-3.1"
MAX_SITES = 12


def _vintage(raw: dict[str, Any]) -> ImageryVintage:
    return ImageryVintage(
        year=int(raw["year"]),
        source=raw["source"],
        items=tuple(
            ImageryItem(id=i["id"], date=i["date"], url=i["url"], title=i["title"])
            for i in raw.get("items", [])
        ),
    )


def _site(raw: dict[str, Any]) -> ConstructionSite:
    return ConstructionSite(
        id=raw["id"],
        label=raw["label"],
        kind=raw.get("kind", "new"),
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        distance_km=0.0,
        footprint_acres_then=float(raw.get("footprint_acres_then", 0.0)),
        footprint_acres_now=float(raw["footprint_acres_now"]),
        in_database=bool(raw.get("in_database", False)),
        near_cluster=bool(raw.get("near_cluster", False)),
        facility=raw.get("facility"),
        polygon=tuple((float(p[0]), float(p[1])) for p in raw.get("polygon", [])),
        confidence=float(raw.get("confidence", 0.8)),
    )


class ImageryIndex:
    def __init__(self, directory: Path = PERCEPTION_DIR) -> None:
        self.dir = directory
        self._areas: list[dict[str, Any]] | None = None

    def areas(self) -> list[dict[str, Any]]:
        if self._areas is None:
            out = []
            if self.dir.exists():
                for path in sorted(self.dir.glob("*.json")):
                    if path.name == "areas.json":
                        continue
                    with open(path, encoding="utf-8") as f:
                        out.append(json.load(f))
            self._areas = out
        return self._areas

    def near(
        self, lat: float, lon: float, radius_km: float = FIVE_MILES_KM
    ) -> ImageryResult | None:
        """The indexed area whose own ring contains this address, with the
        sites inside this address's ring, nearest first. None when no area
        covers the address: the section then says imagery is not indexed."""
        best: tuple[float, dict[str, Any]] | None = None
        for area in self.areas():
            a = area["area"]
            d = haversine_km(lat, lon, float(a["lat"]), float(a["lon"]))
            # The index covers the area's ring; an address this close to its
            # centre has most of its own ring inside it.
            if d <= float(a.get("radius_km", FIVE_MILES_KM)) * 0.6 and (
                best is None or d < best[0]
            ):
                best = (d, area)
        if best is None:
            return None
        area = best[1]
        sites = []
        for raw in area.get("sites", []):
            s = _site(raw)
            dist = round(haversine_km(lat, lon, s.lat, s.lon), 2)
            if dist <= radius_km:
                sites.append(replace(s, distance_km=dist))
        sites.sort(key=lambda s: (not s.counted, s.distance_km))
        return ImageryResult(
            area_id=area["area"]["id"],
            area_name=area["area"]["name"],
            model=area.get("model", SAM_MODEL_ID),
            then=_vintage(area["vintages"]["then"]),
            now=_vintage(area["vintages"]["now"]),
            sites=tuple(sites[:MAX_SITES]),
            indexed_at=area.get("indexed_at", ""),
        )


class FakeImageryIndex:
    def __init__(self, result: ImageryResult | None = None) -> None:
        self.result = result
        self.calls = 0

    def near(
        self, lat: float, lon: float, radius_km: float = FIVE_MILES_KM
    ) -> ImageryResult | None:
        self.calls += 1
        return self.result
