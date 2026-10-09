"""Aggregate ATL13 segments to one water-surface elevation per pass.

Group key: ``(date, rgt, beam)`` -- one beam crossing the reservoir on one day.
The representative level is the **median** of ``H_evrs_egg2015_m``; spread is
reported as MAD / NMAD. An along-track slope is fitted to catch non-flat (i.e.
contaminated or non-water) surfaces.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config
from .qc import evaluate_pass

EARTH_RADIUS_KM = 6371.0088

PASS_LEVEL_COLUMNS = [
    "datetime",
    "date",
    "year",
    "rgt",
    "beam",
    "transect",
    "period",
    "n_points",
    "median_wse_evrs_m",
    "mean_wse_evrs_m",
    "std_m",
    "mad_m",
    "nmad_m",
    "p05_m",
    "p95_m",
    "range_m",
    "along_track_slope_m_per_km",
    "track_length_km",
    "mean_stdev_water_surf_m",
    "lat_mean",
    "lon_mean",
    "qc_pass",
    "qc_flags",
]

_NMAD_K = 1.4826  # MAD -> sigma for a normal distribution


def nmad(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return float("nan")
    return _NMAD_K * float(np.median(np.abs(x - np.median(x))))


def mad(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return float("nan")
    return float(np.median(np.abs(x - np.median(x))))


def _haversine_km(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> np.ndarray:
    lat, lon = np.radians(lat), np.radians(lon)
    lat0, lon0 = np.radians(lat0), np.radians(lon0)
    d = (
        np.sin((lat - lat0) / 2) ** 2
        + np.cos(lat0) * np.cos(lat) * np.sin((lon - lon0) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(d))


def along_track_slope(
    lat: np.ndarray, lon: np.ndarray, h: np.ndarray
) -> tuple[float, float]:
    """Fit ``h`` against along-track distance. Returns ``(slope_m_per_km, length_km)``."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    h = np.asarray(h, float)
    ok = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(h)
    lat, lon, h = lat[ok], lon[ok], h[ok]
    if lat.size < 3:
        return float("nan"), 0.0 if lat.size == 0 else float("nan")

    order = np.argsort(lat)  # tracks are near-meridional over this AOI
    lat, lon, h = lat[order], lon[order], h[order]
    dist = _haversine_km(lat, lon, lat[0], lon[0])
    length = float(dist[-1] - dist[0])
    if length <= 0:
        return float("nan"), length
    slope = float(np.polyfit(dist, h, 1)[0])  # m per km
    return slope, length


def pass_level_table(
    evrs: pd.DataFrame, cfg: Config, *, height_col: str = "H_evrs_egg2015_m"
) -> pd.DataFrame:
    """Aggregate the EVRS segment table into the pass-level table.

    ``height_col`` is the height that is aggregated; the output keeps the
    ``*_wse_evrs_m`` column names whatever it is (the service renames them).
    """
    df = evrs.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)

    if "beam" not in df.columns:
        df["beam"] = df.get("gt", pd.Series(index=df.index, dtype="object")).astype("string")

    # On-water segments only.
    if "water_mask_pass" in df.columns:
        df = df[df["water_mask_pass"].fillna(False)]

    df["date"] = df["time"].dt.normalize()
    rows: list[dict] = []
    for (date, rgt, beam), grp in df.groupby(["date", "rgt", "beam"], dropna=False):
        h = grp[height_col].to_numpy(float)
        h = h[np.isfinite(h)]
        if h.size == 0:
            continue
        slope, length = along_track_slope(
            grp["lat"].to_numpy(float), grp["lon"].to_numpy(float),
            grp[height_col].to_numpy(float),
        )
        rgt_i = _maybe_int(rgt)
        period = (
            grp["period"].mode(dropna=True).iloc[0]
            if "period" in grp and not grp["period"].isna().all()
            else cfg.regimes.label_for(pd.Timestamp(date).to_pydatetime())
        )
        stats = {
            "datetime": grp["time"].min(),
            "date": pd.Timestamp(date).date(),
            "year": int(pd.Timestamp(date).year),
            "rgt": rgt_i,
            "beam": beam,
            "transect": f"{rgt_i}_{beam}",
            "period": period,
            "n_points": int(h.size),
            "median_wse_evrs_m": float(np.median(h)),
            "mean_wse_evrs_m": float(np.mean(h)),
            "mad_m": mad(h),
            "nmad_m": nmad(h),
            "std_m": float(np.std(h, ddof=1)) if h.size > 1 else float("nan"),
            "p05_m": float(np.percentile(h, 5)),
            "p95_m": float(np.percentile(h, 95)),
            "range_m": float(np.percentile(h, 95) - np.percentile(h, 5)),
            "along_track_slope_m_per_km": slope,
            "track_length_km": length,
            "mean_stdev_water_surf_m": float(
                np.nanmean(grp["stdev_water_surf_m"].to_numpy(float))
            )
            if "stdev_water_surf_m" in grp
            else float("nan"),
            "lat_mean": float(np.nanmean(grp["lat"].to_numpy(float))),
            "lon_mean": float(np.nanmean(grp["lon"].to_numpy(float))),
        }
        qc_pass, qc_flags = evaluate_pass(stats, cfg.qc)
        stats["qc_pass"] = qc_pass
        stats["qc_flags"] = qc_flags
        rows.append(stats)

    out = pd.DataFrame(rows, columns=PASS_LEVEL_COLUMNS)
    return out.sort_values("datetime").reset_index(drop=True)


def _maybe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v
