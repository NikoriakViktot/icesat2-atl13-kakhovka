"""The ICESat-2 pipeline as pure steps, independent of where the data lives.

    candidate_granules -> fetch_batch -> segments_from_raw -> to_heights
        -> pass_levels (ATL13) | reference-DEM comparison | rasters

The batch scripts (``scripts/download_atl13*.py``, ``build_evrs.py``,
``build_pass_levels.py``) and the service worker both call these; only the
reading/writing around them differs (local parquet vs. S3 + PostGIS).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import numpy as np
import pandas as pd

from . import heights, products
from .aggregate import mad, nmad, pass_level_table
from .config import Config
from .discovery import GranuleInfo, cmr_granules
from .products import Product
from .regions import EGG2015, PERIOD_ALL, Region
from .vertical import GeoidGrid, add_evrs_columns

ATL13 = products.PRODUCTS["ATL13"]

BASIC_PASS_LEVEL_COLUMNS = [
    "date", "datetime", "year", "rgt", "beam", "period", "n_points",
    "median_wse_evrs_m", "mean_wse_evrs_m", "nmad_m", "mad_m",
    "p05_m", "p95_m", "range_m", "lat_mean", "lon_mean",
]

# library pass-level names -> datum-neutral names used by the service
GENERIC_WSE_COLUMNS = {"median_wse_evrs_m": "median_wse_m", "mean_wse_evrs_m": "mean_wse_m"}


# --------------------------------------------------------------------------- #
# Discovery                                                                    #
# --------------------------------------------------------------------------- #
def select_granules(
    names: Iterable[str], start: dt.date | None = None, end: dt.date | None = None,
    *, product: str | None = None,
) -> list[str]:
    """Granules whose acquisition date lies in ``[start, end]``, oldest first."""
    infos = sorted((GranuleInfo.parse(n) for n in set(names)),
                   key=lambda i: i.acquisition_time)
    out = []
    for info in infos:
        if product is not None and info.product != product:
            continue
        d = info.acquisition_time.date()
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        out.append(info.granule)
    return out


def candidate_granules(
    cfg: Config,
    region: Region,
    start: dt.date | None = None,
    end: dt.date | None = None,
    *,
    include_cmr: bool = False,
    product: Product = ATL13,
) -> list[str]:
    """The region's curated seed list (ATL13), optionally merged with a CMR search."""
    names = set(region.seed_granules()) if product.name == "ATL13" else set()
    if include_cmr:
        names |= set(cmr_granules(
            region.search_bbox,
            start or cfg.product.start_date,
            end or dt.date.today(),
            short_name=product.name,
            version=product.version,
        ))
    return select_granules(names, start, end, product=product.name)


# --------------------------------------------------------------------------- #
# Acquisition                                                                  #
# --------------------------------------------------------------------------- #
def run_sliderule(cfg: Config, api: str, parms: dict):
    """One SlideRule ``x`` request -> GeoDataFrame."""
    from sliderule import sliderule

    init_kw = {}
    if cfg.atl13x.organization:
        init_kw["organization"] = cfg.atl13x.organization
    sliderule.init(cfg.atl13x.domain, **init_kw)
    return sliderule.run(api, parms)


def fetch_batch(cfg: Config, region: Region, granules: list[str], *,
                product: Product = ATL13, options: dict | None = None):
    """One SlideRule request for ``granules`` over ``region``."""
    parms = products.request_parms(product, region, granules, options)
    return run_sliderule(cfg, product.api, parms)


def granule_lookup(granules: Iterable[str]) -> dict[tuple[int, int], str]:
    """``(rgt, cycle) -> granule``; the first granule wins for a repeated key."""
    out: dict[tuple[int, int], str] = {}
    for info in sorted((GranuleInfo.parse(g) for g in granules),
                       key=lambda i: i.acquisition_time):
        out.setdefault((info.rgt, info.cycle), info.granule)
    return out


def segments_from_raw(raw, granules: Iterable[str], *, product: Product = ATL13) -> pd.DataFrame:
    """Normalise a raw SlideRule frame and attach the granule name via (rgt, cycle)."""
    seg = products.normalise(product, raw)
    gmap = granule_lookup(granules)
    seg["granule"] = [
        gmap.get((int(r), int(c))) if pd.notna(r) and pd.notna(c) else None
        for r, c in zip(seg["rgt"], seg["cycle"], strict=False)
    ]
    return seg.sort_values("time").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Processing                                                                   #
# --------------------------------------------------------------------------- #
def within(df: pd.DataFrame, geom) -> np.ndarray:
    """Boolean mask: point (lon, lat) falls inside ``geom``."""
    import geopandas as gpd

    if len(df) == 0:
        return np.zeros(0, bool)
    pts = gpd.GeoSeries(
        gpd.points_from_xy(df["lon"].astype(float), df["lat"].astype(float)),
        crs="EPSG:4326",
    )
    return pts.within(geom).to_numpy()


def to_heights(
    seg: pd.DataFrame, cfg: Config, region: Region, *, product: Product = ATL13,
    geoid: GeoidGrid | None = None,
) -> pd.DataFrame:
    """Clip flag + orthometric heights + period for any product.

    ATL13 keeps every segment with ``water_mask_pass`` (inside the clip); ATL08 /
    ATL03 drop points outside the clip (SlideRule cut them with a convex hull).
    ATL13 over an ``egg2015`` region also gets the reservoir pipeline's EVRS columns
    (``zeta_egg2015_m``, ``H_evrs_egg2015_m``, ``egm2008_minus_evrs_m``).
    """
    df = seg.copy()
    inside = within(df, region.clip_geometry())
    if product.name == "ATL13":
        df["water_mask_pass"] = inside
        if region.vertical == EGG2015:
            df = add_evrs_columns(df, cfg, geoid=geoid)
    else:
        df = df[inside].reset_index(drop=True)
    df = heights.add_heights(
        df, product.height_col, region.vertical, geoid=geoid,
        egm2008_col="H_egm2008_m" if product.name == "ATL13" else None,
    )
    if region.regimes:
        dates = pd.to_datetime(df["time"], utc=True).dt.date
        df["period"] = [cfg.regimes.label_for(d) for d in dates]
    else:
        df["period"] = PERIOD_ALL
    return df


def to_evrs(
    segments: pd.DataFrame, cfg: Config, region: Region, *, geoid: GeoidGrid | None = None
) -> pd.DataFrame:
    """ATL13 segments + ``water_mask_pass`` + heights (the reservoir pipeline's step)."""
    return to_heights(segments, cfg, region, product=ATL13, geoid=geoid)


def pass_levels(evrs: pd.DataFrame, cfg: Config, region: Region) -> pd.DataFrame:
    """ATL13: one level per (date, rgt, beam) of ``H_m`` in the region's datum.

    Still water (lake / reservoir) gets the full QC; rivers basic statistics. Columns
    use datum-neutral names (``median_wse_m``, ``mean_wse_m``) + ``vertical_datum``.
    """
    if region.still_water:
        out = pass_level_table(evrs, cfg, height_col="H_m")
    else:
        out = basic_pass_levels(evrs, region.clip_geometry(), height_col="H_m")
    out = out.rename(columns=GENERIC_WSE_COLUMNS)
    out["vertical_datum"] = region.vertical_datum
    return out


def basic_pass_levels(evrs: pd.DataFrame, geom, *,
                      height_col: str = "H_evrs_egg2015_m") -> pd.DataFrame:
    """Per-pass statistics inside ``geom`` without the reservoir QC gates."""
    df = evrs.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["date"] = df["time"].dt.date
    df = df[np.isfinite(df[height_col]) & within(df, geom)]
    rows = []
    for (date, rgt, beam), g in df.groupby(["date", "rgt", "beam"], dropna=False):
        h = g[height_col].to_numpy(float)
        p05, p95 = np.percentile(h, [5, 95])
        rows.append({
            "date": date, "datetime": g["time"].min(),
            "year": int(pd.Timestamp(date).year),
            "rgt": int(rgt), "beam": beam, "period": g["period"].iloc[0],
            "n_points": int(h.size),
            "median_wse_evrs_m": float(np.median(h)), "mean_wse_evrs_m": float(np.mean(h)),
            "nmad_m": nmad(h), "mad_m": mad(h),
            "p05_m": float(p05), "p95_m": float(p95), "range_m": float(p95 - p05),
            "lat_mean": float(g["lat"].mean()), "lon_mean": float(g["lon"].mean()),
        })
    if not rows:
        return pd.DataFrame(columns=BASIC_PASS_LEVEL_COLUMNS)
    return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)


def dem_mask(df: pd.DataFrame, product: Product) -> np.ndarray:
    """Points that enter DEM statistics/rasters (ATL13: on-water segments only)."""
    if product.name == "ATL13" and "water_mask_pass" in df:
        return df["water_mask_pass"].to_numpy(bool)
    return np.ones(len(df), bool)
