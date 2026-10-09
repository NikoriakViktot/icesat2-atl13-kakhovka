"""ICESat-2 products the service can ingest, each a thin spec over a SlideRule ``x`` API.

* ATL13 -- ``atl13x``, inland-water segments; ellipsoidal ``h_wgs84_m``
  (``ht_water_surf``), EGM2008 ``H_egm2008_m`` (``ht_ortho``).
* ATL08 -- ``atl08x``, 100 m land/vegetation segments; terrain ``h_te_median_m``,
  canopy ``h_canopy_m`` & co.
* ATL03 -- ``atl03x``, geolocated photons; ``height_m``, ``atl03_cnf``,
  ``atl08_class``.

ATL13 selects its water body with ``coord`` (+ optional ``refid``); ATL08 / ATL03
are cut server-side with the region polygon (``poly``). Every normalised frame has
``time, lat, lon, beam, rgt, cycle`` plus the product columns, and the name of its
ellipsoidal-height column is :attr:`Product.height_col`.

Reference DEMs (Copernicus GLO-30, FABDEM) are sampled locally from their own
tiles (:mod:`kakhovka_altimetry.dem`), not through SlideRule's raster sampling,
whose vertical frame proved inconsistent between regions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from . import atl13

# ICESat-2 ground-track integer -> beam label
_GT_TO_BEAM = {10: "gt1l", 20: "gt1r", 30: "gt2l", 40: "gt2r", 50: "gt3l", 60: "gt3r"}

# ATL08 photon classes accepted by atl03x ``atl08_class``
ATL08_CLASSES = ("atl08_noise", "atl08_ground", "atl08_canopy", "atl08_top_of_canopy",
                 "atl08_unclassified")


@dataclass(frozen=True)
class Product:
    name: str
    api: str
    version: str
    height_col: str          # ellipsoidal (WGS84) height of the normalised frame
    needs_coord: bool        # ATL13: the water body is picked by coord / refid
    points_in_db: bool       # ATL03 photons stay in S3 (too many for PostGIS)
    default_batch: int
    # raster variable -> (column, description)
    dem_variables: dict[str, tuple[str, str]]


PRODUCTS: dict[str, Product] = {
    "ATL13": Product(
        name="ATL13", api="atl13x", version="007", height_col="h_wgs84_m",
        needs_coord=True, points_in_db=True, default_batch=50,
        dem_variables={"wse": ("H_m", "water-surface elevation (orthometric)")},
    ),
    "ATL08": Product(
        name="ATL08", api="atl08x", version="007", height_col="h_te_median_m",
        needs_coord=False, points_in_db=True, default_batch=10,
        dem_variables={
            "dtm": ("H_m", "terrain elevation, ATL08 h_te_median (orthometric)"),
            "chm": ("h_canopy_m", "canopy height above terrain, ATL08 h_canopy"),
        },
    ),
    "ATL03": Product(
        name="ATL03", api="atl03x", version="007", height_col="height_m",
        needs_coord=False, points_in_db=False, default_batch=3,
        dem_variables={"dtm": ("H_m", "photon elevation (orthometric); use atl08_class "
                                      "['atl08_ground'] for a terrain model")},
    ),
}


def get(name: str) -> Product:
    try:
        return PRODUCTS[name.upper()]
    except KeyError:
        raise KeyError(f"unknown product {name!r}; supported: {sorted(PRODUCTS)}") from None


# --------------------------------------------------------------------------- #
# Request parameters                                                           #
# --------------------------------------------------------------------------- #
def request_parms(product: Product, region, granules: list[str],
                  options: dict[str, Any] | None = None) -> dict[str, Any]:
    """SlideRule parameters for one batch of ``granules`` over ``region``."""
    options = options or {}
    if product.name == "ATL13":
        if region.coord_lon is None or region.coord_lat is None:
            raise ValueError("ATL13 needs region.coord: a point on the water body")
        parms = atl13.build_parms_for(region.refid, region.coord_lon, region.coord_lat,
                                      granules)
    else:
        parms = {"poly": sliderule_polygon(region.clip_geometry()), "locks": 1,
                 "resources": list(granules)}
        if product.name == "ATL03":
            a3 = options.get("atl03") or {}
            parms["cnf"] = int(a3.get("cnf", 4))
            if a3.get("atl08_class"):
                bad = set(a3["atl08_class"]) - set(ATL08_CLASSES)
                if bad:
                    raise ValueError(f"unknown atl08_class {sorted(bad)}; use {ATL08_CLASSES}")
                parms["atl08_class"] = list(a3["atl08_class"])
    return parms


def sliderule_polygon(geom) -> list[dict[str, float]]:
    """A geometry as a SlideRule ``poly``: counter-clockwise ring, first point repeated.

    Multi-part or holed clips are sent as their convex hull; the exact clip is
    applied locally after the pull.
    """
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient

    hull = geom if isinstance(geom, Polygon) and not geom.interiors else geom.convex_hull
    ring = orient(hull.simplify(0.0005) if len(hull.exterior.coords) > 200 else hull,
                  sign=1.0).exterior.coords
    return [{"lon": float(x), "lat": float(y)} for x, y in ring]


# --------------------------------------------------------------------------- #
# Normalisation                                                                #
# --------------------------------------------------------------------------- #
def normalise(product: Product, gdf) -> pd.DataFrame:
    if product.name == "ATL13":
        df = atl13.normalise(gdf)
    elif product.name == "ATL08":
        df = _normalise_x(gdf, {
            "h_te_median": "h_te_median_m",
            "h_te_uncertainty": "h_te_uncertainty_m",
            "terrain_slope": "terrain_slope",
            "h_canopy": "h_canopy_m",
            "h_mean_canopy": "h_mean_canopy_m",
            "h_max_canopy": "h_max_canopy_m",
            "h_canopy_uncertainty": "h_canopy_uncertainty_m",
            "canopy_openness": "canopy_openness",
            "n_te_photons": "n_te_photons",
            "n_ca_photons": "n_ca_photons",
            "segment_landcover": "segment_landcover",
            "segment_snowcover": "segment_snowcover",
            "solar_elevation": "solar_elevation",
            "segment_id_beg": "segment_id",
        }, height_cols=("h_te_median_m", "h_te_uncertainty_m", "h_canopy_m",
                        "h_mean_canopy_m", "h_max_canopy_m", "h_canopy_uncertainty_m"))
    elif product.name == "ATL03":
        df = _normalise_x(gdf, {
            "height": "height_m",
            "atl03_cnf": "atl03_cnf",
            "atl08_class": "atl08_class",
            "quality_ph": "quality_ph",
            "ph_index": "ph_index",
            "x_atc": "x_atc",
            "y_atc": "y_atc",
            "segment_id": "segment_id",
            "solar_elevation": "solar_elevation",
            "background_rate": "background_rate",
        }, height_cols=("height_m",))
    else:  # pragma: no cover - registry and normalisers kept in sync by tests
        raise KeyError(product.name)
    return df


def _normalise_x(gdf, columns: dict[str, str], *, height_cols=()) -> pd.DataFrame:
    """Common normaliser for the ``atl0Nx`` dataframes (DatetimeIndex + geometry)."""
    geom = getattr(gdf, "geometry", None)
    if geom is None and "geometry_wkt" in getattr(gdf, "columns", ()):
        import geopandas as gpd

        geom = gpd.GeoSeries.from_wkt(gdf["geometry_wkt"])
    df = pd.DataFrame(gdf).copy()
    if "time" not in df.columns:
        df = df.reset_index()
        df = df.rename(columns={df.columns[0]: "time"})
    df["time"] = pd.to_datetime(df["time"], utc=True)
    out = pd.DataFrame({
        "time": df["time"].to_numpy(),
        "lat": np.asarray(geom.y, float),
        "lon": np.asarray(geom.x, float),
        "rgt": df.get("rgt"),
        "cycle": df.get("cycle"),
        "spot": df.get("spot"),
        "gt": df.get("gt"),
    })
    out["time"] = pd.to_datetime(out["time"], utc=True)
    out["beam"] = out["gt"].map(_GT_TO_BEAM).fillna(out["gt"].astype("string"))
    for src, dst in columns.items():
        if src in df.columns and dst not in out.columns:
            out[dst] = df[src].to_numpy()
    for col in height_cols:  # ICESat-2 marks invalid values with ~FLT_MAX
        if col in out.columns:
            v = pd.to_numeric(out[col], errors="coerce")
            out[col] = v.where(v.abs() < 1e30)
    return out.reset_index(drop=True)
