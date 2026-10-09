"""Regions: one ATL13 water body + the spatial clip and conventions applied to it.

The batch pipeline is hard-wired to ``config/kakhovka.yaml`` (the reservoir AOI and
the ``downstream_bodies``). The service works on *any* inland water body, so a
region is a value that can come from that config, from the service's region
registry, or straight from a request:

* water body -- ``coord`` (a point on the water; SlideRule resolves the ATL13
  reference water body from it) and optionally the ATL13 ``refid``;
* clip       -- ``bbox`` or a GeoJSON polygon (``polygon_path`` for files);
* ``kind``   -- ``lake`` / ``reservoir``: still water, full per-pass QC
  (:func:`aggregate.pass_level_table`); ``river``: basic per-pass statistics, the
  track-length / slope checks do not apply;
* ``vertical`` -- ``egg2015``: EVRS normal heights via the EGG2015 quasigeoid
  (Europe only); ``egm2008``: ATL13 ``ht_ortho`` (global);
* ``regimes`` -- label segments with the Kakhovka dam-breach periods
  (``config/kakhovka.yaml::regimes``); otherwise every segment is ``ALL``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Config, DownstreamBody

LAKE = "lake"
RESERVOIR = "reservoir"
RIVER = "river"
KINDS = (LAKE, RESERVOIR, RIVER)
STILL_WATER = (LAKE, RESERVOIR)

EGG2015 = "egg2015"
EGM2008 = "egm2008"
VERTICALS = (EGG2015, EGM2008)

# vertical -> label stored with every height (segments.vertical_datum)
VERTICAL_DATUM_LABEL = {EGG2015: "EVRS_EGG2015", EGM2008: "EGM2008"}

PERIOD_ALL = "ALL"


@dataclass(frozen=True)
class Region:
    slug: str
    name: str
    coord_lon: float | None = None   # ATL13: a point on the water body
    coord_lat: float | None = None
    refid: int | None = None
    kind: str = LAKE
    vertical: str = EGM2008
    regimes: bool = False
    bbox: tuple[float, float, float, float] | None = None
    polygon_path: Path | None = None
    polygon_layer: str | None = None
    # Inline GeoJSON geometry (from an API request / the registry); serialised as a
    # string so the dataclass stays hashable.
    polygon_geojson: str | None = None
    seed_granules_file: Path | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"region kind must be one of {KINDS}, got {self.kind!r}")
        if self.vertical not in VERTICALS:
            raise ValueError(f"region vertical must be one of {VERTICALS}, "
                             f"got {self.vertical!r}")
        if self.bbox is None and self.polygon_path is None and self.polygon_geojson is None:
            raise ValueError(f"region {self.slug!r} needs a bbox or a polygon")

    @property
    def still_water(self) -> bool:
        return self.kind in STILL_WATER

    @property
    def vertical_datum(self) -> str:
        return VERTICAL_DATUM_LABEL[self.vertical]

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

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe definition (the inverse of :func:`region_from_dict`)."""
        d = asdict(self)
        coord = (None if d["coord_lon"] is None
                 else {"lon": d["coord_lon"], "lat": d["coord_lat"]})
        out = {
            "slug": d["slug"], "name": d["name"], "refid": d["refid"], "coord": coord,
            "kind": d["kind"], "vertical": d["vertical"], "regimes": d["regimes"],
            "bbox": list(d["bbox"]) if d["bbox"] else None,
            "polygon": json.loads(d["polygon_geojson"]) if d["polygon_geojson"] else None,
        }
        if self.polygon_path is not None:
            out["polygon_path"] = str(self.polygon_path)
        return out


def reservoir_region(cfg: Config) -> Region:
    """The Kakhovka reservoir exactly as ``scripts/build_evrs.py`` clips it."""
    return Region(
        slug="kakhovka",
        name="Kakhovka reservoir",
        refid=cfg.atl13x.refid,
        coord_lon=cfg.atl13x.coord_lon,
        coord_lat=cfg.atl13x.coord_lat,
        kind=RESERVOIR,
        vertical=EGG2015,
        regimes=True,
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
        vertical=EGG2015,
        regimes=True,
        bbox=body.clip_bbox,
        polygon_path=body.clip_polygon,
        seed_granules_file=body.seed_granules_file,
    )


def configured_regions(cfg: Config) -> dict[str, Region]:
    """All regions declared in ``config/kakhovka.yaml``, keyed by slug."""
    regions = [reservoir_region(cfg)] + [body_region(b) for b in cfg.downstream_bodies]
    return {r.slug: r for r in regions}


def region_from_dict(d: dict[str, Any]) -> Region:
    """Build a region from a request body / registry row (see ``RegionIn`` in the API)."""
    poly = d.get("polygon")
    coord = d.get("coord")
    return Region(
        slug=d["slug"],
        name=d.get("name") or d["slug"],
        refid=int(d["refid"]) if d.get("refid") is not None else None,
        coord_lon=float(coord["lon"]) if coord else None,
        coord_lat=float(coord["lat"]) if coord else None,
        kind=d.get("kind") or LAKE,
        vertical=d.get("vertical") or EGM2008,
        regimes=bool(d.get("regimes", False)),
        bbox=tuple(d["bbox"]) if d.get("bbox") else None,
        polygon_geojson=json.dumps(poly) if poly else None,
    )
