"""The ATL13 pipeline as pure steps, independent of where the data lives.

    candidate_granules -> fetch_batch -> segments_from_raw -> to_evrs -> pass_levels

The batch scripts (``scripts/download_atl13*.py``, ``build_evrs.py``,
``build_pass_levels.py``) and the service worker both call these; only the
reading/writing around them differs (local parquet vs. S3 + PostGIS).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

import numpy as np
import pandas as pd

from . import atl13
from .aggregate import mad, nmad, pass_level_table
from .config import Config
from .discovery import GranuleInfo, cmr_granules
from .regions import RESERVOIR, Region
from .vertical import GeoidGrid, add_evrs_columns

BASIC_PASS_LEVEL_COLUMNS = [
    "date", "datetime", "year", "rgt", "beam", "period", "n_points",
    "median_wse_evrs_m", "mean_wse_evrs_m", "nmad_m", "mad_m",
    "p05_m", "p95_m", "range_m", "lat_mean", "lon_mean",
]


# --------------------------------------------------------------------------- #
# Discovery                                                                    #
# --------------------------------------------------------------------------- #
def select_granules(
    names: Iterable[str], start: dt.date | None = None, end: dt.date | None = None
) -> list[str]:
    """Granules whose acquisition date lies in ``[start, end]``, oldest first."""
    infos = sorted((GranuleInfo.parse(n) for n in set(names)),
                   key=lambda i: i.acquisition_time)
    out = []
    for info in infos:
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
) -> list[str]:
    """The region's curated seed list, optionally merged with a live CMR search."""
    names = set(region.seed_granules())
    if include_cmr:
        names |= set(cmr_granules(
            region.search_bbox,
            start or cfg.product.start_date,
            end or dt.date.today(),
            short_name=cfg.product.short_name,
            version=cfg.product.version,
        ))
    return select_granules(names, start, end)


# --------------------------------------------------------------------------- #
# Acquisition                                                                  #
# --------------------------------------------------------------------------- #
def fetch_batch(cfg: Config, region: Region, granules: list[str]):
    """One SlideRule ``atl13x`` request for ``granules`` over ``region``."""
    parms = atl13.build_parms_for(region.refid, region.coord_lon, region.coord_lat, granules)
    return atl13.run_atl13x(cfg, granules, parms=parms)


def granule_lookup(granules: Iterable[str]) -> dict[tuple[int, int], str]:
    """``(rgt, cycle) -> granule``; the first granule wins for a repeated key."""
    out: dict[tuple[int, int], str] = {}
    for info in sorted((GranuleInfo.parse(g) for g in granules),
                       key=lambda i: i.acquisition_time):
        out.setdefault((info.rgt, info.cycle), info.granule)
    return out


def segments_from_raw(raw, granules: Iterable[str]) -> pd.DataFrame:
    """Normalise a raw SlideRule frame and attach the granule name via (rgt, cycle)."""
    seg = atl13.normalise(raw)
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
    """Boolean mask: segment (lon, lat) falls inside ``geom``."""
    import geopandas as gpd

    pts = gpd.GeoSeries(
        gpd.points_from_xy(df["lon"].astype(float), df["lat"].astype(float)),
        crs="EPSG:4326",
    )
    return pts.within(geom).to_numpy()


def to_evrs(
    segments: pd.DataFrame, cfg: Config, region: Region, *, geoid: GeoidGrid | None = None
) -> pd.DataFrame:
    """Segments + ``water_mask_pass`` (inside the region clip) + the EVRS columns."""
    df = segments.copy()
    df["water_mask_pass"] = within(df, region.clip_geometry()) if len(df) else []
    return add_evrs_columns(df, cfg, geoid=geoid)


def pass_levels(evrs: pd.DataFrame, cfg: Config, region: Region) -> pd.DataFrame:
    """One level per (date, rgt, beam): full QC for a reservoir, basic stats otherwise."""
    if region.kind == RESERVOIR:
        return pass_level_table(evrs, cfg)
    return basic_pass_levels(evrs, region.clip_geometry())


def basic_pass_levels(evrs: pd.DataFrame, geom) -> pd.DataFrame:
    """Per-pass statistics inside ``geom`` without the reservoir QC gates."""
    df = evrs.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["date"] = df["time"].dt.date
    df = df[np.isfinite(df["H_evrs_egg2015_m"]) & within(df, geom)]
    rows = []
    for (date, rgt, beam), g in df.groupby(["date", "rgt", "beam"], dropna=False):
        h = g["H_evrs_egg2015_m"].to_numpy(float)
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
