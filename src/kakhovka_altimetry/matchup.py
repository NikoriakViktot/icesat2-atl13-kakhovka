"""Phase 2 — match each ICESat-2 pass level to the nearest gauge stage.

    alignment_residual_m = WSE_ICESat_evrs_m - stage_m

One row per (pass, station) within the configured time and distance windows.
The residual feeds :func:`kakhovka_altimetry.datum.estimate_empirical_alignment`.
Not used by V1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .aggregate import _haversine_km
from .config import Config
from .gauges import gauge_value_at

MATCHUP_COLUMNS = [
    "datetime",
    "rgt",
    "beam",
    "transect",
    "period",
    "station_id",
    "WSE_ICESat_evrs_m",
    "icesat_nmad_m",
    "n_points",
    "stage_m",
    "WSE_gauge_baltic_m",
    "alignment_residual_m",
    "adopted_constant_m",
    "time_difference_hours",
    "distance_to_gauge_km",
    "gauge_interpolated",
]


def build_matchups(
    pass_levels: pd.DataFrame,
    obs: pd.DataFrame,
    cfg: Config,
    *,
    qc_only: bool = True,
) -> pd.DataFrame:
    """Join pass levels to gauge stage observations. Returns the matchup table."""
    passes = pass_levels.copy()
    if qc_only and "qc_pass" in passes.columns:
        passes = passes[passes["qc_pass"].fillna(False)]
    passes["datetime"] = pd.to_datetime(passes["datetime"], utc=True)
    period_col = "period" if "period" in passes.columns else "regime"

    method = cfg.matchup.gauge_interpolation
    max_dt = cfg.matchup.max_time_difference_hours
    max_km = cfg.matchup.max_distance_to_gauge_km

    rows: list[dict] = []
    for _, p in passes.iterrows():
        period = p[period_col]
        for st in cfg.gauges.stations:
            if not st.complete:
                continue
            if st.active_regimes and period not in st.active_regimes:
                continue
            dist_km = float(
                _haversine_km(
                    np.array([p["lat_mean"]]), np.array([p["lon_mean"]]),
                    st.lat, st.lon,
                )[0]
            )
            if dist_km > max_km:
                continue

            stage, interpolated, gap_h = gauge_value_at(
                obs, st.id, p["datetime"], column="stage_m",
                method=method, max_gap_hours=max_dt,
            )
            if not np.isfinite(stage) or gap_h > max_dt:
                continue
            g_baltic, _, _ = gauge_value_at(
                obs, st.id, p["datetime"], column="WSE_baltic_m",
                method=method, max_gap_hours=max_dt,
            )

            icesat_wse = float(p["median_wse_evrs_m"])
            adopted = cfg.alignment.constant_for(st.id)
            rows.append({
                "datetime": p["datetime"],
                "rgt": p["rgt"],
                "beam": p["beam"],
                "transect": p.get("transect", f"{p['rgt']}_{p['beam']}"),
                "period": period,
                "station_id": st.id,
                "WSE_ICESat_evrs_m": icesat_wse,
                "icesat_nmad_m": float(p.get("nmad_m", np.nan)),
                "n_points": int(p.get("n_points", 0)),
                "stage_m": float(stage),
                "WSE_gauge_baltic_m": float(g_baltic),
                "alignment_residual_m": icesat_wse - float(stage),
                "adopted_constant_m": float(adopted) if adopted is not None else np.nan,
                "time_difference_hours": float(gap_h),
                "distance_to_gauge_km": dist_km,
                "gauge_interpolated": bool(interpolated),
            })

    return pd.DataFrame(rows, columns=MATCHUP_COLUMNS).sort_values(
        ["datetime", "station_id"]
    ).reset_index(drop=True)
