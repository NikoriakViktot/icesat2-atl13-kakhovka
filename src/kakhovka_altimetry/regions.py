"""Regions: one ATL13 reference water body + the spatial clip applied to it.

The batch pipeline is hard-wired to ``config/kakhovka.yaml`` (the reservoir AOI and
the ``downstream_bodies``). The service needs the same thing as a value it can take
from a request, so both are expressed here as a :class:`Region`:

* ``kind="reservoir"`` -- full per-pass QC (:func:`aggregate.pass_level_table`);
* ``kind="river"``     -- the basic per-pass statistics used for the bodies below
  the dam, where track-length / slope checks do not apply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config, DownstreamBody

RESERVOIR = "reservoir"
RIVER = "river"
KINDS = (RESERVOIR, RIVER)


@dataclass(frozen=True)
class Region:
    slug: str
    name: str
    refid: int
    coord_lon: float
    coord_lat: float
    kind: str = RIVER
    bbox: tuple[float, float, float, float] | None = None
    polygon_path: Path | None = None
    polygon_layer: str | None = None
    # Inline GeoJSON geometry (from an API request); serialised as a string so the
    # dataclass stays hashable.
    polygon_geojson: str | None = None
    seed_granules_file: Path | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"region kind must be one of {KINDS}, got {self.kind!r}")
        if self.bbox is None and self.polygon_path is None and self.polygon_geojson is None:
            raise ValueError(f"region {self.slug!r} needs a bbox or a polygon")

    def clip_geometry(self):
        """The clip as a shapely geometry in EPSG:4326 (polygon wins over bbox)."""
        from shapely.geometry import box, shape

        if self.polygon_geojson is not None:
            return shape(json.loads(self.polygon_geojson))
        if self.polygon_path is not None and Path(self.polygon_path).exists():
            import geopandas as gpd

            read_kw = {}
            if Path(self.polygon_path).suffix.lower() in (".gpkg", ".gdb") and self.polygon_layer:
                read_kw["layer"] = self.polygon_layer
            gdf = gpd.read_file(self.polygon_path, **read_kw).to_crs("EPSG:4326")
            return gdf.union_all() if hasattr(gdf, "union_all") else gdf.unary_union
        if self.bbox is not None:
            return box(*self.bbox)
        raise FileNotFoundError(f"region {self.slug!r}: polygon {self.polygon_path} missing "
                                f"and no bbox fallback")

    @property
    def search_bbox(self) -> tuple[float, float, float, float]:
        """Bounding box for the CMR granule search."""
        if self.bbox is not None:
            return tuple(self.bbox)  # type: ignore[return-value]
        return tuple(float(v) for v in self.clip_geometry().bounds)  # type: ignore[return-value]

    def seed_granules(self) -> list[str]:
        if self.seed_granules_file is None or not Path(self.seed_granules_file).exists():
            return []
        return sorted({
            ln.strip()
            for ln in Path(self.seed_granules_file).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        })


def reservoir_region(cfg: Config) -> Region:
    """The Kakhovka reservoir exactly as ``scripts/build_evrs.py`` clips it."""
    return Region(
        slug="kakhovka",
        name="Kakhovka reservoir",
        refid=cfg.atl13x.refid,
        coord_lon=cfg.atl13x.coord_lon,
        coord_lat=cfg.atl13x.coord_lat,
        kind=RESERVOIR,
        bbox=tuple(cfg.aoi_bbox),  # type: ignore[arg-type]
        polygon_path=cfg.aoi_polygon if cfg.aoi_polygon.exists() else None,
        polygon_layer=cfg.aoi_polygon_layer,
        seed_granules_file=cfg.seed_granules_file,
    )


def body_region(body: DownstreamBody) -> Region:
    return Region(
        slug=body.slug,
        name=body.name,
        refid=body.refid,
        coord_lon=body.coord_lon,
        coord_lat=body.coord_lat,
        kind=RIVER,
        bbox=body.clip_bbox,
        polygon_path=body.clip_polygon,
        seed_granules_file=body.seed_granules_file,
    )


def configured_regions(cfg: Config) -> dict[str, Region]:
    """All regions declared in ``config/kakhovka.yaml``, keyed by slug."""
    regions = [reservoir_region(cfg)] + [body_region(b) for b in cfg.downstream_bodies]
    return {r.slug: r for r in regions}


def region_from_dict(d: dict[str, Any]) -> Region:
    """Build a region from a request body (see ``service.schemas.RegionIn``)."""
    poly = d.get("polygon")
    return Region(
        slug=d["slug"],
        name=d.get("name") or d["slug"],
        refid=int(d["refid"]),
        coord_lon=float(d["coord"]["lon"]),
        coord_lat=float(d["coord"]["lat"]),
        kind=d.get("kind", RIVER),
        bbox=tuple(d["bbox"]) if d.get("bbox") else None,
        polygon_geojson=json.dumps(poly) if poly else None,
    )
