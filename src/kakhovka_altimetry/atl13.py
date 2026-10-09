"""Thin wrapper around SlideRule's ``atl13x`` endpoint + column normalisation.

The raw SlideRule GeoDataFrame is normalised to the **segments** schema. Nothing
is recomputed here: both native ATL13 heights are carried through verbatim --

    h_wgs84_m   <- ht_water_surf   (ellipsoidal water-surface height, WGS84)
    H_egm2008_m <- ht_ortho        (orthometric water-surface height, EGM2008)

The EVRS chain is built later in :mod:`kakhovka_altimetry.vertical`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import Config

# SlideRule column name -> segments-schema column name.
_COLUMN_MAP = {
    "ht_water_surf": "h_wgs84_m",
    "ht_ortho": "H_egm2008_m",
    "stdev_water_surf": "stdev_water_surf_m",
    "water_depth": "water_depth_m",
    "rgt": "rgt",
    "cycle": "cycle",
    "spot": "spot",
    "gt": "gt",
    "segment_id": "segment_id",
    "segment_id_beg": "segment_id",
    "srcid": "srcid",
    "refid": "refid",
    "region": "region",
}

SEGMENTS_COLUMNS = [
    "time",
    "cycle",
    "rgt",
    "gt",
    "spot",
    "segment_id",
    "lat",
    "lon",
    "h_wgs84_m",
    "H_egm2008_m",
    "stdev_water_surf_m",
    "water_depth_m",
    "srcid",
    "granule",
    "refid",
]

# Ground-track integer -> beam label. ICESat-2 gt values are 10,20,30,40,50,60.
_GT_TO_BEAM = {10: "gt1l", 20: "gt1r", 30: "gt2l", 40: "gt2r", 50: "gt3l", 60: "gt3r"}


def build_parms(cfg: Config, resources: list[str]) -> dict[str, Any]:
    """Assemble the SlideRule ``atl13x`` request parameters."""
    return {
        "atl13": {
            "refid": cfg.atl13x.refid,
            "coord": {"lon": cfg.atl13x.coord_lon, "lat": cfg.atl13x.coord_lat},
        },
        "locks": 1,
        "resources": list(resources),
    }


def run_atl13x(cfg: Config, resources: list[str], *, parms: dict | None = None):
    """Execute the SlideRule request and return the raw GeoDataFrame.

    Import of ``sliderule`` is deferred so that unit tests / offline steps can
    import this module without the dependency.
    """
    from sliderule import sliderule

    init_kw = {}
    if cfg.atl13x.organization:
        init_kw["organization"] = cfg.atl13x.organization
    sliderule.init(cfg.atl13x.domain, **init_kw)
    request = parms or build_parms(cfg, resources)
    return sliderule.run("atl13x", request)


def build_parms_for(refid: int, lon: float, lat: float, resources: list[str]) -> dict[str, Any]:
    """``atl13x`` request parameters for an arbitrary reference water body."""
    return {
        "atl13": {"refid": int(refid), "coord": {"lon": float(lon), "lat": float(lat)}},
        "locks": 1,
        "resources": list(resources),
    }


def raw_frame(gdf) -> pd.DataFrame:
    """The verbatim SlideRule return as a plain, parquet-safe DataFrame.

    The DatetimeIndex becomes a ``time`` column and shapely geometries become
    ``geometry_wkt`` (:func:`normalise` accepts either form).
    """
    rdf = pd.DataFrame(gdf).copy()
    if isinstance(rdf.index, pd.DatetimeIndex):
        rdf = rdf.reset_index()
        rdf = rdf.rename(columns={rdf.columns[0]: "time"})
    if "geometry" in rdf.columns:  # shapely objects don't serialise to plain parquet
        rdf["geometry_wkt"] = rdf["geometry"].astype(str)
        rdf = rdf.drop(columns="geometry")
    return rdf


def normalise(gdf, *, granule: str | None = None) -> pd.DataFrame:
    """Normalise a raw SlideRule frame to the segments schema (plain DataFrame)."""
    # Coordinates from the geometry BEFORE dropping GeoDataFrame-ness. A raw frame
    # read back from parquet carries the geometry as WKT (see :func:`raw_frame`).
    geom = getattr(gdf, "geometry", None)
    if geom is None and "geometry_wkt" in getattr(gdf, "columns", ()):
        import geopandas as gpd

        geom = gpd.GeoSeries.from_wkt(gdf["geometry_wkt"])
    lon = geom.x.to_numpy() if geom is not None else None
    lat = geom.y.to_numpy() if geom is not None else None

    df = pd.DataFrame(gdf).copy()

    # Time: SlideRule 5.x indexes by a DatetimeIndex (named "time" or "time_ns").
    if "time" not in df.columns:
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            df = df.rename(columns={df.columns[0]: "time"}
                           if df.columns[0] in ("index", "time_ns") else {})
        elif "time_ns" in df.columns:
            df["time"] = df["time_ns"]
    if "time" not in df.columns and "time_ns" in df.columns:
        df["time"] = df["time_ns"]
    df["time"] = pd.to_datetime(df["time"], utc=True)

    if lon is not None and ("lon" not in df.columns or "lat" not in df.columns):
        df["lon"] = lon
        df["lat"] = lat

    df = df.rename(columns={k: v for k, v in _COLUMN_MAP.items() if k in df.columns})

    # ATL13 marks invalid measurements with ~FLT_MAX (3.4e38). Mask to NaN so
    # aggregates don't blow up.
    for col in ("h_wgs84_m", "H_egm2008_m", "stdev_water_surf_m", "water_depth_m"):
        if col in df.columns:
            v = pd.to_numeric(df[col], errors="coerce")
            df[col] = v.where(v.abs() < 1e30)

    if "granule" not in df.columns and granule is not None:
        df["granule"] = granule
    if "gt" in df.columns:
        df["beam"] = df["gt"].map(_GT_TO_BEAM).fillna(df["gt"].astype("string"))

    for col in SEGMENTS_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    keep = SEGMENTS_COLUMNS + (["beam"] if "beam" in df.columns else [])
    return df[keep].reset_index(drop=True)
