"""Phase 2a — local vertical alignment between one gauge and ICESat-2/EGG2015.

Reservoir-wide pass levels average ATL13 over ~130 km of pool, so they are the
wrong input for a tie at a single post. This module works from the **point-level**
EVRS table, selects segments by distance to the gauge, rebuilds *local* pass
levels, and matches those to the gauge stage series:

    alignment_constant_m = median( H_EVRS_ICESat(local pass) - stage(t) )

`alignment_constant_m` is the number to add to a gauge stage series to obtain an
ICESat-2/EGG2015-consistent water-surface elevation. It **incorporates** the gauge
zero elevation, the Baltic-1977 -> EVRS datum difference, and any systematic
ICESat-2 / vertical-model bias, so it must **not** be read as a Baltic-to-EVRS
datum transformation.

`evrs_minus_bs77_m = H_EVRS_ICESat - (gauge_zero_baltic_m + stage)` is reported as
the *empirical EVRS-BS77 difference*. Note it is exactly
`alignment_constant_m - gauge_zero_baltic_m`: the nominal zero is only a shift, so
this column is derived, not independent evidence.

Only ``PRE_BREACH`` data is admissible: after 2023-06-06 the local surface is no
longer the reservoir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .aggregate import _haversine_km, mad, nmad
from .config import Config, GaugeStation
from .gauges import gauge_value_at
from .stats import residual_stats

CALIBRATION_PERIOD = "PRE_BREACH"

LOCAL_PASS_COLUMNS = [
    "date", "datetime", "year", "rgt", "beam", "transect", "period",
    "n_points", "median_wse_evrs_m", "mean_wse_evrs_m", "std_m", "mad_m",
    "nmad_m", "p05_m", "p95_m", "range_m",
    "mean_distance_km", "min_distance_km", "radius_km",
    "reservoir_level_m", "deviation_from_reservoir_m",
    "local_qc_pass", "local_qc_flags",
]

# Median of n samples has SE ~= 1.2533 * sigma / sqrt(n) for normal data; we use
# NMAD as the robust sigma so the interval matches the median point estimate.
_MEDIAN_SE_K = 1.2533

MATCHUP_COLUMNS = LOCAL_PASS_COLUMNS + [
    "station_id", "stage_m", "H_bs77_m", "alignment_constant_m",
    "evrs_minus_bs77_m", "time_difference_hours", "gauge_interpolated",
]

RADIUS_LADDER_COLUMNS = [
    "radius_km", "n_matchups", "n_dates", "n_rgts", "rgts",
    "alignment_constant_m", "nmad_m", "std_m", "ci95_low_m", "ci95_high_m",
    "evrs_minus_bs77_m", "indicative",
]

PER_RGT_COLUMNS = [
    "rgt", "radius_km", "n_matchups", "icesat_median_wse_m",
    "gauge_median_stage_m", "alignment_constant_m", "nmad_m",
    "bias_relative_to_pooled_m",
]


# --------------------------------------------------------------------------- #
# Geometry                                                                     #
# --------------------------------------------------------------------------- #
def distance_to_station(evrs: pd.DataFrame, station: GaugeStation) -> np.ndarray:
    """Great-circle distance (km) from each segment to the gauge."""
    return _haversine_km(
        evrs["lat"].to_numpy(dtype=float),
        evrs["lon"].to_numpy(dtype=float),
        float(station.lat),
        float(station.lon),
    )


# --------------------------------------------------------------------------- #
# Local pass levels                                                            #
# --------------------------------------------------------------------------- #
def reservoir_level_by_date(reservoir_passes: pd.DataFrame | None) -> pd.Series:
    """ICESat-only reservoir level per date: median of QC-ok reservoir pass levels.

    Used as the reference for the plausibility gate. The gauge plays no part.
    """
    if reservoir_passes is None or reservoir_passes.empty:
        return pd.Series(dtype=float)
    df = reservoir_passes
    if "qc_pass" in df.columns:
        df = df[df["qc_pass"].fillna(False)]
    if df.empty:
        return pd.Series(dtype=float)
    return df.groupby("date")["median_wse_evrs_m"].median()


def local_pass_levels(
    evrs: pd.DataFrame,
    station: GaugeStation,
    radius_km: float,
    cfg: Config,
    *,
    min_points: int | None = None,
    period: str = CALIBRATION_PERIOD,
    distance_km: np.ndarray | None = None,
    reservoir_level: pd.Series | None = None,
) -> pd.DataFrame:
    """Aggregate ATL13 segments within ``radius_km`` of the gauge to one level per
    ``(date, rgt, beam)``.

    Local QC is deliberately independent of the reservoir-wide ``qc.*`` thresholds
    (track length / along-track slope are meaningless inside a few-km circle):

    * ``n_points >= min_points``
    * ``nmad_m <= max_local_nmad_m`` — the pass is an internally flat surface
    * ``|median_wse_evrs_m - reservoir_level(date)| <= max_deviation_from_reservoir_m``
      — the surface is at a plausible water level. Without this a bank/land return
      can be perfectly flat and still pass; ``reservoir_level`` comes from the
      reservoir-wide ICESat pass levels on the same date, never from the gauge.
    """
    la = cfg.local_alignment
    min_points = la.min_points_per_local_pass if min_points is None else min_points

    df = evrs
    d = distance_to_station(df, station) if distance_km is None else distance_km
    keep = d <= float(radius_km)
    if "water_mask_pass" in df.columns:
        keep &= df["water_mask_pass"].fillna(False).to_numpy(dtype=bool)
    if period is not None:
        keep &= (df["period"] == period).to_numpy(dtype=bool)

    df = df.loc[keep].copy()
    df["_d_km"] = d[keep]
    if df.empty:
        return pd.DataFrame(columns=LOCAL_PASS_COLUMNS)

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["date"] = df["time"].dt.date

    rows: list[dict] = []
    for (date, rgt, beam), grp in df.groupby(["date", "rgt", "beam"], dropna=False):
        h = grp["H_evrs_egg2015_m"].to_numpy(float)
        h = h[np.isfinite(h)]
        if h.size == 0:
            continue
        rgt_i = int(rgt)
        p05, p95 = float(np.percentile(h, 5)), float(np.percentile(h, 95))
        row = {
            "date": date,
            "datetime": grp["time"].min(),
            "year": int(pd.Timestamp(date).year),
            "rgt": rgt_i,
            "beam": beam,
            "transect": f"{rgt_i}_{beam}",
            "period": grp["period"].iloc[0] if "period" in grp else period,
            "n_points": int(h.size),
            "median_wse_evrs_m": float(np.median(h)),
            "mean_wse_evrs_m": float(np.mean(h)),
            "std_m": float(np.std(h, ddof=1)) if h.size > 1 else float("nan"),
            "mad_m": mad(h),
            "nmad_m": nmad(h),
            "p05_m": p05,
            "p95_m": p95,
            "range_m": p95 - p05,
            "mean_distance_km": float(grp["_d_km"].mean()),
            "min_distance_km": float(grp["_d_km"].min()),
            "radius_km": float(radius_km),
        }

        level = (
            float(reservoir_level.get(date, np.nan))
            if reservoir_level is not None and len(reservoir_level) else np.nan
        )
        dev = row["median_wse_evrs_m"] - level if np.isfinite(level) else np.nan
        row["reservoir_level_m"] = level
        row["deviation_from_reservoir_m"] = dev

        flags = []
        if row["n_points"] < min_points:
            flags.append("too_few_points")
        if pd.isna(row["nmad_m"]) or row["nmad_m"] > la.max_local_nmad_m:
            flags.append("nmad_too_large")
        if np.isfinite(dev) and abs(dev) > la.max_deviation_from_reservoir_m:
            flags.append("implausible_level")
        row["local_qc_pass"] = len(flags) == 0
        row["local_qc_flags"] = "|".join(flags)
        rows.append(row)

    out = pd.DataFrame(rows, columns=LOCAL_PASS_COLUMNS)
    return out.sort_values("datetime").reset_index(drop=True)


def attach_reservoir_qc(
    local_passes: pd.DataFrame, reservoir_passes: pd.DataFrame
) -> pd.DataFrame:
    """Left-join the reservoir-wide ``qc_pass`` for the same (date, rgt, beam)."""
    if local_passes.empty or reservoir_passes is None or reservoir_passes.empty:
        out = local_passes.copy()
        out["reservoir_qc_pass"] = pd.NA
        return out
    key = reservoir_passes[["date", "rgt", "beam", "qc_pass"]].rename(
        columns={"qc_pass": "reservoir_qc_pass"}
    )
    return local_passes.merge(key, on=["date", "rgt", "beam"], how="left")


# --------------------------------------------------------------------------- #
# Matchup with the gauge stage series                                          #
# --------------------------------------------------------------------------- #
def match_local(
    local_passes: pd.DataFrame,
    obs: pd.DataFrame,
    station: GaugeStation,
    cfg: Config,
    *,
    qc_only: bool = True,
) -> pd.DataFrame:
    """Attach the gauge stage at each local pass time and form the residuals."""
    if local_passes.empty:
        return pd.DataFrame(columns=MATCHUP_COLUMNS)

    passes = local_passes
    if qc_only and "local_qc_pass" in passes.columns:
        passes = passes[passes["local_qc_pass"]]
    if passes.empty:
        return pd.DataFrame(columns=MATCHUP_COLUMNS)

    method = cfg.matchup.gauge_interpolation
    max_dt = cfg.matchup.max_time_difference_hours
    zero = station.gauge_zero_baltic_m

    rows: list[dict] = []
    for _, p in passes.iterrows():
        stage, interpolated, gap_h = gauge_value_at(
            obs, station.id, p["datetime"], column="stage_m",
            method=method, max_gap_hours=max_dt,
        )
        if not np.isfinite(stage) or gap_h > max_dt:
            continue
        wse = float(p["median_wse_evrs_m"])
        row = p.to_dict()
        row.update({
            "station_id": station.id,
            "stage_m": float(stage),
            "H_bs77_m": (zero + float(stage)) if zero is not None else np.nan,
            "alignment_constant_m": wse - float(stage),
            "evrs_minus_bs77_m": (wse - (zero + float(stage)))
            if zero is not None else np.nan,
            "time_difference_hours": float(gap_h),
            "gauge_interpolated": bool(interpolated),
        })
        rows.append(row)

    cols = MATCHUP_COLUMNS + (
        ["reservoir_qc_pass"] if "reservoir_qc_pass" in passes.columns else []
    )
    out = pd.DataFrame(rows)
    for c in cols:
        if c not in out.columns:
            out[c] = pd.NA
    return out[cols].sort_values("datetime").reset_index(drop=True) if not out.empty \
        else pd.DataFrame(columns=cols)


# --------------------------------------------------------------------------- #
# Aggregation across radii and RGTs                                            #
# --------------------------------------------------------------------------- #
def _summarise(matchups: pd.DataFrame, radius_km: float, cfg: Config) -> dict:
    c = matchups["alignment_constant_m"].to_numpy(float)
    st = residual_stats(c)
    n = int(st["n"]) if np.isfinite(st["n"]) else 0
    rgts = sorted(int(r) for r in matchups["rgt"].dropna().unique()) if n else []

    median = float(np.median(c[np.isfinite(c)])) if n else float("nan")
    # CI around the MEDIAN (the reported estimate), from the robust NMAD -- not the
    # mean-based interval, which a single gross outlier would blow up.
    half = (
        _MEDIAN_SE_K * st["NMAD"] / np.sqrt(n) * 1.96
        if n > 1 and np.isfinite(st["NMAD"]) else float("nan")
    )
    return {
        "radius_km": float(radius_km),
        "n_matchups": n,
        "n_dates": int(matchups["date"].nunique()) if n else 0,
        "n_rgts": len(rgts),
        "rgts": ",".join(str(r) for r in rgts),
        "alignment_constant_m": median,
        "nmad_m": st["NMAD"],
        "std_m": st["std"],
        "ci95_low_m": median - half,
        "ci95_high_m": median + half,
        "evrs_minus_bs77_m": float(
            np.median(matchups["evrs_minus_bs77_m"].dropna().to_numpy(float))
        ) if matchups["evrs_minus_bs77_m"].notna().any() else float("nan"),
        "indicative": n < cfg.local_alignment.min_matchups_for_confidence,
    }


def radius_ladder(
    evrs: pd.DataFrame,
    obs: pd.DataFrame,
    station: GaugeStation,
    cfg: Config,
    *,
    radii: tuple[float, ...] | None = None,
    reservoir_passes: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the whole chain at each radius.

    Returns ``(ladder, all_matchups)`` where ``all_matchups`` carries a
    ``radius_km`` column so every radius can be inspected from one table.
    """
    radii = tuple(radii) if radii is not None else cfg.local_alignment.radii_km
    d = distance_to_station(evrs, station)
    level = reservoir_level_by_date(reservoir_passes)

    ladder_rows, frames = [], []
    for r in radii:
        lp = local_pass_levels(
            evrs, station, r, cfg, distance_km=d, reservoir_level=level
        )
        if reservoir_passes is not None:
            lp = attach_reservoir_qc(lp, reservoir_passes)
        m = match_local(lp, obs, station, cfg)
        ladder_rows.append(_summarise(m, r, cfg))
        if not m.empty:
            frames.append(m)

    ladder = pd.DataFrame(ladder_rows, columns=RADIUS_LADDER_COLUMNS)
    matchups = (
        pd.concat(frames, ignore_index=True) if frames
        else pd.DataFrame(columns=MATCHUP_COLUMNS)
    )
    return ladder, matchups


STATION_SUMMARY_COLUMNS = [
    "station_id", "slug", "name", "name_en", "lat", "lon",
    "gauge_zero_baltic_m", "distance_from_dam_km",
    "main_radius_km", "n_main", "alignment_constant_m", "nmad_m",
    "ci95_low_m", "ci95_high_m", "evrs_minus_bs77_m",
    "reported_radius_km", "n_reported", "sufficient_at_main", "note",
]

# Kakhovka dam (Nova Kakhovka) — chainage origin for the longitudinal profile.
DAM_LAT, DAM_LON = 46.775432, 33.374615


def smallest_sufficient_radius(ladder: pd.DataFrame, cfg: Config) -> float | None:
    """Smallest radius in the ladder reaching ``min_matchups_for_confidence``."""
    ok = ladder[ladder["n_matchups"] >= cfg.local_alignment.min_matchups_for_confidence]
    return float(ok["radius_km"].min()) if not ok.empty else None


def station_summary(
    station: GaugeStation, ladder: pd.DataFrame, cfg: Config
) -> dict:
    """One row describing the tie at a station: the main radius, and — when the
    main radius is too thin — the smallest radius that does reach confidence."""
    main_r = cfg.local_alignment.main_radius_km
    main = ladder[np.isclose(ladder["radius_km"], main_r)]
    main_row = main.iloc[0] if not main.empty else None
    n_main = int(main_row["n_matchups"]) if main_row is not None else 0
    enough = n_main >= cfg.local_alignment.min_matchups_for_confidence

    rep_r = main_r if enough else smallest_sufficient_radius(ladder, cfg)
    rep = (
        ladder[np.isclose(ladder["radius_km"], rep_r)].iloc[0]
        if rep_r is not None else None
    )

    if rep is None:
        note = (
            f"no radius reaches {cfg.local_alignment.min_matchups_for_confidence} "
            f"matchups — no usable tie"
        )
    elif enough:
        note = ""
    else:
        note = f"main radius too thin (n={n_main}); reported at {rep_r:g} km"

    return {
        "station_id": station.id,
        "slug": station.slug,
        "name": station.name,
        "name_en": station.name_en,
        "lat": station.lat,
        "lon": station.lon,
        "gauge_zero_baltic_m": station.gauge_zero_baltic_m,
        "distance_from_dam_km": float(
            _haversine_km(np.array([station.lat]), np.array([station.lon]),
                          DAM_LAT, DAM_LON)[0]
        ),
        "main_radius_km": main_r,
        "n_main": n_main,
        "alignment_constant_m": float(rep["alignment_constant_m"]) if rep is not None
        else float("nan"),
        "nmad_m": float(rep["nmad_m"]) if rep is not None else float("nan"),
        "ci95_low_m": float(rep["ci95_low_m"]) if rep is not None else float("nan"),
        "ci95_high_m": float(rep["ci95_high_m"]) if rep is not None else float("nan"),
        "evrs_minus_bs77_m": float(rep["evrs_minus_bs77_m"]) if rep is not None
        else float("nan"),
        "reported_radius_km": rep_r if rep_r is not None else float("nan"),
        "n_reported": int(rep["n_matchups"]) if rep is not None else 0,
        "sufficient_at_main": bool(enough),
        "note": note,
    }


def per_rgt(matchups: pd.DataFrame, radius_km: float) -> pd.DataFrame:
    """Per-RGT constant and its bias relative to the pooled value at one radius."""
    sub = matchups[np.isclose(matchups["radius_km"].astype(float), float(radius_km))]
    if sub.empty:
        return pd.DataFrame(columns=PER_RGT_COLUMNS)

    pooled = float(np.median(sub["alignment_constant_m"].to_numpy(float)))
    rows = []
    for rgt, g in sub.groupby("rgt"):
        c = g["alignment_constant_m"].to_numpy(float)
        rows.append({
            "rgt": int(rgt),
            "radius_km": float(radius_km),
            "n_matchups": int(len(g)),
            "icesat_median_wse_m": float(np.median(g["median_wse_evrs_m"].to_numpy(float))),
            "gauge_median_stage_m": float(np.median(g["stage_m"].to_numpy(float))),
            "alignment_constant_m": float(np.median(c)),
            "nmad_m": nmad(c),
            "bias_relative_to_pooled_m": float(np.median(c)) - pooled,
        })
    rows.append({
        "rgt": "ALL",
        "radius_km": float(radius_km),
        "n_matchups": int(len(sub)),
        "icesat_median_wse_m": float(np.median(sub["median_wse_evrs_m"].to_numpy(float))),
        "gauge_median_stage_m": float(np.median(sub["stage_m"].to_numpy(float))),
        "alignment_constant_m": pooled,
        "nmad_m": nmad(sub["alignment_constant_m"].to_numpy(float)),
        "bias_relative_to_pooled_m": 0.0,
    })
    return pd.DataFrame(rows, columns=PER_RGT_COLUMNS)
