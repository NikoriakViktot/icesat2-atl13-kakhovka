"""Decide whether each ATL13 segment falls on water *on its acquisition date*.

V1 uses the static reservoir polygon (``data/aoi/kakhovka_reservoir.gpkg``). The
hook :func:`date_water_mask` is where per-date Sentinel-2 / Dynamic World masks
plug in later; if no such mask is available it falls back to the polygon, so the
column is always populated.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config


def _load_aoi_polygon(cfg: Config):
    import geopandas as gpd
    from shapely.geometry import box

    path = cfg.aoi_polygon
    if path.exists():
        # `layer` only applies to multi-layer formats (GeoPackage); GeoJSON/shp ignore it.
        read_kw = {}
        if path.suffix.lower() in (".gpkg", ".gdb") and cfg.aoi_polygon_layer:
            read_kw["layer"] = cfg.aoi_polygon_layer
        gdf = gpd.read_file(path, **read_kw).to_crs("EPSG:4326")
        return gdf.union_all() if hasattr(gdf, "union_all") else gdf.unary_union
    lon_min, lat_min, lon_max, lat_max = cfg.aoi_bbox
    return box(lon_min, lat_min, lon_max, lat_max)


def date_water_mask(date: pd.Timestamp, cfg: Config) -> Path | None:
    """Return a path to a per-date water-mask raster, or None if unavailable.

    Placeholder: wire in Sentinel-2 / Dynamic World composites here. When it
    returns None, callers fall back to the static AOI polygon.
    """
    return None


def add_water_mask_column(segments: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Add boolean ``water_mask_pass`` (segment is on water on its date)."""
    import geopandas as gpd

    df = segments.copy()
    poly = _load_aoi_polygon(cfg)

    pts = gpd.GeoSeries(
        gpd.points_from_xy(df["lon"].astype(float), df["lat"].astype(float)),
        crs="EPSG:4326",
    )
    in_aoi = pts.within(poly).to_numpy()

    # Per-date refinement, when a mask is available for that day.
    mask = np.array(in_aoi, dtype=bool)
    dates = pd.to_datetime(df["time"], utc=True).dt.normalize()
    for day, idx in df.groupby(dates).groups.items():
        raster = date_water_mask(pd.Timestamp(day), cfg)
        if raster is None:
            continue
        mask[df.index.get_indexer(idx)] &= _sample_binary_raster(
            raster, df.loc[idx, "lon"].to_numpy(float), df.loc[idx, "lat"].to_numpy(float)
        )

    df["water_mask_pass"] = mask
    return df


def _sample_binary_raster(path: Path, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    import rasterio

    with rasterio.open(path) as ds:
        vals = np.array(list(ds.sample(np.column_stack([lon, lat]))), dtype=float)
    return (vals[:, 0] > 0)
