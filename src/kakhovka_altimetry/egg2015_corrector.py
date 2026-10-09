"""Phase 2c — empirical EGG2015 → EVRF2019 corrector from the Kakhovka gauges.

For a still-water ICESat-2 pass near a gauge at time ``t``:

    H_ICESat_EGG2015(t) = ht_water_surf(t) - zeta_EGG2015          ( == H_evrs_egg2015_m )
    H_gauge_EVRF2019(t) = gauge_zero_BS77 + stage_m(t) + delta_EPSG9902(lat, lon)

and the station corrector is

    c_station = median( H_gauge_EVRF2019 - H_ICESat_EGG2015 )   over PRE_BREACH matchups.

The interpretation is ``H_ICESat_EVRF2019_approx = H_ICESat_EGG2015 + c_station``.

``c_station`` is **not** a datum transformation. It absorbs, inseparably from
ICESat + gauges alone:

* the residual mismatch between the EGG2015 realisation and EVRF2019,
* the gauge-zero error (the nominal 12.00 m BS-77 zero is not surveyed truth),
* any systematic ICESat-2 / ATL13 inland-water bias,
* the spatial water-surface gradient across the matchup radius,
* the temporal mismatch between the overpass and the gauge reading.

By construction ``c_station == -delta_unexplained_m`` from :mod:`kakhovka_altimetry.datum`
(nominal zero, same official grid); this module adds the empirical error model
(bootstrap over independent beam-passes, temporal-strategy sensitivity) the
decomposition script does not carry.

Only ``PRE_BREACH`` data (before 2023-06-06) is admissible: afterwards the local
surface is no longer the reservoir.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import official_datum as od
from .aggregate import mad, nmad
from .config import Config, GaugeStation
from .gauges import gauge_value_at
from .local_alignment import (
    CALIBRATION_PERIOD,
    distance_to_station,
    local_pass_levels,
    reservoir_level_by_date,
)

# Radius ladder for the matchup search (km). 2 km is primary.
RADII_KM: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0, 10.0)
PRIMARY_RADIUS_KM = 2.0

# A matchup is an independent statistical unit only if it is one (date, RGT, beam)
# beam-pass. Below this many independent units a result is flagged LOW_SAMPLE.
MIN_INDEPENDENT = 5

# Temporal tolerance (h) to the nearest real gauge reading. Term readings are 12 h
# apart, so 12 h always reaches one; the daily-mean series is one point per day.
MAX_GAP_TERM_H = 12.0
MAX_GAP_DAILY_H = 18.0

BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 20260903

# EPSG:9902's published *operation accuracy* field. This is NOT a standard
# deviation and NOT a 95% CI -- the same EPSG record separately reports SD 0.034 m
# over its 154 determination points. It is carried as its own budget line and is
# never relabelled a sigma, never combined in quadrature.
EPSG9902_OP_ACCURACY_M = 0.068

MATCHUP_COLUMNS = [
    "station_id", "slug", "name_en", "station_lat", "station_lon", "radius_km",
    "date", "datetime", "year", "rgt", "beam", "transect",
    "n_segments", "h_icesat_egg2015_m", "nmad_m", "mad_m", "p05_m", "p95_m",
    "range_m", "mean_distance_km", "min_distance_km",
    "gauge_zero_bs77_m", "delta_epsg9902_m",
    "stage_A_m", "stage_B_m", "stage_C_m",
    "h_gauge_evrf2019_A_m", "h_gauge_evrf2019_B_m", "h_gauge_evrf2019_C_m",
    "c_station_A_m", "c_station_B_m", "c_station_C_m",
    "time_diff_A_h", "gauge_interpolated_A",
]

# ``c_station_A_m`` (interpolated 08-20 stage) is the primary residual column.
PRIMARY_C = "c_station_A_m"


# --------------------------------------------------------------------------- #
# Gauge series                                                                 #
# --------------------------------------------------------------------------- #
def load_daily_mean_series(cfg: Config) -> pd.DataFrame:
    """Daily-mean gauge series (``h_mean``) placed at 12:00 local, in the same
    long schema as :func:`kakhovka_altimetry.gauges.load_gauge_observations`.

    Used only for temporal-sensitivity variant C.
    """
    tz = "Europe/Kyiv" if cfg.gauges.timezone == "kyiv" else "UTC"
    to_m = 0.01 if cfg.gauges.stage_units == "cm" else 1.0
    root = cfg.gauges.raw_dir

    frames: list[pd.DataFrame] = []
    for st in cfg.gauges.stations:
        files = sorted((root / f"post_id={st.id}").glob("year=*.parquet"))
        if not files:
            continue
        daily = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        if "h_mean" not in daily.columns:
            continue
        part = daily[["date", "h_mean"]].dropna()
        ts = (pd.to_datetime(part["date"]) + pd.Timedelta(hours=12)) \
            .dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT") \
            .dt.tz_convert("UTC")
        frames.append(pd.DataFrame({
            "station_id": st.id,
            "datetime": ts,
            "stage_m": pd.to_numeric(part["h_mean"], errors="coerce") * to_m,
            "WSE_baltic_m": np.nan,
        }).dropna(subset=["datetime", "stage_m"]))

    if not frames:
        return pd.DataFrame(columns=["station_id", "datetime", "stage_m", "WSE_baltic_m"])
    return pd.concat(frames, ignore_index=True).sort_values(
        ["station_id", "datetime"]
    ).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Per-station matchups                                                         #
# --------------------------------------------------------------------------- #
def station_matchups(
    evrs: pd.DataFrame,
    term_obs: pd.DataFrame,
    mean_obs: pd.DataFrame,
    station: GaugeStation,
    cfg: Config,
    grid,
    *,
    radii: tuple[float, ...] = RADII_KM,
    reservoir_passes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Every QC-ok local beam-pass within each radius of ``station``, matched to
    the gauge stage under all three temporal strategies.

    One row = one ``(radius, date, RGT, beam)`` — the independent statistical unit
    for the same radius is ``(date, RGT, beam)``.
    """
    zero = station.gauge_zero_baltic_m
    delta_off = float(od.correction_at(grid, float(station.lat), float(station.lon))[0])
    d = distance_to_station(evrs, station)
    level = reservoir_level_by_date(reservoir_passes)

    rows: list[dict] = []
    for r in radii:
        lp = local_pass_levels(
            evrs, station, r, cfg, distance_km=d, reservoir_level=level,
            period=CALIBRATION_PERIOD,
        )
        lp = lp[lp["local_qc_pass"]] if "local_qc_pass" in lp.columns else lp
        for _, p in lp.iterrows():
            when = pd.Timestamp(p["datetime"])
            sA, iA, gA = gauge_value_at(term_obs, station.id, when, column="stage_m",
                                        method="linear", max_gap_hours=MAX_GAP_TERM_H)
            if not np.isfinite(sA):
                continue  # the primary strategy defines the matchup set
            sB, _, _ = gauge_value_at(term_obs, station.id, when, column="stage_m",
                                      method="nearest", max_gap_hours=MAX_GAP_TERM_H)
            if not mean_obs.empty and "station_id" in mean_obs.columns:
                sC, _, _ = gauge_value_at(mean_obs, station.id, when, column="stage_m",
                                          method="linear", max_gap_hours=MAX_GAP_DAILY_H)
            else:
                sC = np.nan
            wse = float(p["median_wse_evrs_m"])

            def _hg(stage, _z=zero, _off=delta_off):
                if _z is None or not np.isfinite(stage):
                    return np.nan
                return _z + float(stage) + _off

            def _c(stage, _w=wse):
                hg = _hg(stage)
                return hg - _w if np.isfinite(hg) else np.nan

            rows.append({
                "station_id": station.id, "slug": station.slug,
                "name_en": station.name_en,
                "station_lat": float(station.lat), "station_lon": float(station.lon),
                "radius_km": float(r),
                "date": p["date"], "datetime": when,
                "year": int(p["year"]), "rgt": int(p["rgt"]), "beam": p["beam"],
                "transect": p["transect"],
                "n_segments": int(p["n_points"]),
                "h_icesat_egg2015_m": wse,
                "nmad_m": float(p["nmad_m"]), "mad_m": float(p["mad_m"]),
                "p05_m": float(p["p05_m"]), "p95_m": float(p["p95_m"]),
                "range_m": float(p["range_m"]),
                "mean_distance_km": float(p["mean_distance_km"]),
                "min_distance_km": float(p["min_distance_km"]),
                "gauge_zero_bs77_m": zero, "delta_epsg9902_m": delta_off,
                "stage_A_m": sA, "stage_B_m": sB, "stage_C_m": sC,
                "h_gauge_evrf2019_A_m": _hg(sA),
                "h_gauge_evrf2019_B_m": _hg(sB),
                "h_gauge_evrf2019_C_m": _hg(sC),
                "c_station_A_m": _c(sA), "c_station_B_m": _c(sB), "c_station_C_m": _c(sC),
                "time_diff_A_h": float(gA), "gauge_interpolated_A": bool(iA),
            })

    return pd.DataFrame(rows, columns=MATCHUP_COLUMNS)


# --------------------------------------------------------------------------- #
# Bootstrap over independent beam-passes                                       #
# --------------------------------------------------------------------------- #
def bootstrap_median_ci(
    x: np.ndarray, *, n: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the median. ``x`` must already be one value per
    independent unit (one beam-pass), never one per ATL13 segment.
    """
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if x.size < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(n, x.size))
    meds = np.median(x[idx], axis=1)
    lo, hi = np.percentile(meds, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(lo), float(hi))


def _empirical(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = x.size
    if n == 0:
        return dict.fromkeys(
            ("n", "median", "mean", "std", "mad", "nmad", "p05", "p95", "iqr",
             "boot_lo", "boot_hi"), float("nan")
        ) | {"n": 0}
    q05, q25, q75, q95 = np.percentile(x, [5, 25, 75, 95])
    lo, hi = bootstrap_median_ci(x)
    return {
        "n": int(n),
        "median": float(np.median(x)),
        "mean": float(np.mean(x)),
        "std": float(np.std(x, ddof=1)) if n > 1 else float("nan"),
        "mad": mad(x), "nmad": nmad(x),
        "p05": float(q05), "p95": float(q95), "iqr": float(q75 - q25),
        "boot_lo": lo, "boot_hi": hi,
    }


# --------------------------------------------------------------------------- #
# Aggregation                                                                  #
# --------------------------------------------------------------------------- #
def by_radius(matchups: pd.DataFrame) -> pd.DataFrame:
    """One row per (station, radius): the corrector and its empirical spread."""
    rows = []
    for (sid, name, slug, r), g in matchups.groupby(
        ["station_id", "name_en", "slug", "radius_km"], dropna=False
    ):
        e = _empirical(g[PRIMARY_C].to_numpy(float))
        rgts = sorted(int(x) for x in g["rgt"].dropna().unique())
        rows.append({
            "station_id": sid, "name_en": name, "slug": slug, "radius_km": float(r),
            "n_matchups": e["n"], "n_beampasses": e["n"],
            "n_dates": int(g["date"].nunique()),
            "n_rgts": len(rgts), "rgts": ",".join(map(str, rgts)),
            "median_h_icesat_egg2015_m": float(np.median(g["h_icesat_egg2015_m"])),
            "c_station_m": e["median"],
            "empirical_nmad_m": e["nmad"], "empirical_std_m": e["std"],
            "bootstrap_ci95_low_m": e["boot_lo"], "bootstrap_ci95_high_m": e["boot_hi"],
            "flag": "LOW_SAMPLE" if e["n"] < MIN_INDEPENDENT else "OK",
        })
    return pd.DataFrame(rows).sort_values(["station_id", "radius_km"]).reset_index(drop=True)


def reported_radius(ladder_station: pd.DataFrame) -> float | None:
    """Nearest radius to :data:`PRIMARY_RADIUS_KM` reaching :data:`MIN_INDEPENDENT`
    independent matchups (2 km itself wins ties)."""
    ok = ladder_station[ladder_station["n_matchups"] >= MIN_INDEPENDENT]
    if ok.empty:
        return None
    r = ok["radius_km"].to_numpy(float)
    return float(r[np.argmin(np.abs(r - PRIMARY_RADIUS_KM) + 1e-6 * (r < PRIMARY_RADIUS_KM))])


def by_station(matchups: pd.DataFrame, ladder: pd.DataFrame) -> pd.DataFrame:
    """One row per station at its reported radius, all three temporal strategies."""
    rows = []
    for (sid, name, slug), g_all in matchups.groupby(
        ["station_id", "name_en", "slug"], dropna=False
    ):
        lad = ladder[ladder["station_id"] == sid]
        rep_r = reported_radius(lad)
        g = g_all[np.isclose(g_all["radius_km"], rep_r)] if rep_r is not None else g_all.iloc[:0]
        eA = _empirical(g[PRIMARY_C].to_numpy(float))
        eB = _empirical(g["c_station_B_m"].to_numpy(float))
        eC = _empirical(g["c_station_C_m"].to_numpy(float))
        temporal_spread = (
            float(np.nanmax([eA["median"], eB["median"], eC["median"]])
                  - np.nanmin([eA["median"], eB["median"], eC["median"]]))
            if eA["n"] else float("nan")
        )
        rgts = sorted(int(x) for x in g["rgt"].dropna().unique())
        rows.append({
            "station_id": sid, "name_en": name, "slug": slug,
            "lat": float(g_all["station_lat"].iloc[0]),
            "lon": float(g_all["station_lon"].iloc[0]),
            "gauge_zero_bs77_m": float(g_all["gauge_zero_bs77_m"].iloc[0]),
            "delta_epsg9902_m": float(g_all["delta_epsg9902_m"].iloc[0]),
            "reported_radius_km": rep_r if rep_r is not None else float("nan"),
            "n_matchups": eA["n"], "n_dates": int(g["date"].nunique()) if eA["n"] else 0,
            "n_rgts": len(rgts), "rgts": ",".join(map(str, rgts)),
            "median_h_icesat_egg2015_m": float(np.median(g["h_icesat_egg2015_m"]))
            if eA["n"] else float("nan"),
            "c_station_m": eA["median"],
            "empirical_nmad_m": eA["nmad"], "empirical_std_m": eA["std"],
            "bootstrap_ci95_low_m": eA["boot_lo"], "bootstrap_ci95_high_m": eA["boot_hi"],
            "c_station_B_nearest_m": eB["median"], "c_station_C_dailymean_m": eC["median"],
            "temporal_spread_m": temporal_spread,
            "flag": "LOW_SAMPLE" if eA["n"] < MIN_INDEPENDENT else "OK",
        })
    return pd.DataFrame(rows).sort_values("lon").reset_index(drop=True)


def by_rgt(matchups: pd.DataFrame, ladder: pd.DataFrame) -> pd.DataFrame:
    """Per-RGT corrector at each station's reported radius, plus the RGT bias."""
    rows = []
    for sid, g_all in matchups.groupby("station_id", dropna=False):
        lad = ladder[ladder["station_id"] == sid]
        rep_r = reported_radius(lad)
        if rep_r is None:
            continue
        g = g_all[np.isclose(g_all["radius_km"], rep_r)]
        c_all = float(np.median(g[PRIMARY_C].to_numpy(float)))
        for rgt, gr in g.groupby("rgt"):
            e = _empirical(gr[PRIMARY_C].to_numpy(float))
            rows.append({
                "station_id": sid, "name_en": gr["name_en"].iloc[0],
                "radius_km": float(rep_r), "rgt": int(rgt),
                "n_matchups": e["n"], "n_dates": int(gr["date"].nunique()),
                "correction_m": e["median"],
                "mad_m": e["mad"], "nmad_m": e["nmad"],
                "ci95_low_m": e["boot_lo"], "ci95_high_m": e["boot_hi"],
                "c_station_all_m": c_all,
                "rgt_bias_m": e["median"] - c_all,
                "flag": "LOW_SAMPLE" if e["n"] < MIN_INDEPENDENT else "OK",
            })
    return pd.DataFrame(rows).sort_values(["station_id", "rgt"]).reset_index(drop=True)


def uncertainty_table(matchups: pd.DataFrame, ladder: pd.DataFrame) -> pd.DataFrame:
    """Empirical precision + the separate systematic-budget columns, per station."""
    rows = []
    for sid, g_all in matchups.groupby("station_id", dropna=False):
        lad = ladder[ladder["station_id"] == sid]
        rep_r = reported_radius(lad)
        g = g_all[np.isclose(g_all["radius_km"], rep_r)] if rep_r is not None else g_all.iloc[:0]
        e = _empirical(g[PRIMARY_C].to_numpy(float))
        eB = _empirical(g["c_station_B_m"].to_numpy(float))
        eC = _empirical(g["c_station_C_m"].to_numpy(float))
        temporal = (
            float(np.nanmax([e["median"], eB["median"], eC["median"]])
                  - np.nanmin([e["median"], eB["median"], eC["median"]]))
            if e["n"] else float("nan")
        )
        lad_ok = lad[lad["n_matchups"] >= MIN_INDEPENDENT]
        radius_spread = (
            float(lad_ok["c_station_m"].max() - lad_ok["c_station_m"].min())
            if len(lad_ok) > 1 else float("nan")
        )
        rows.append({
            "station_id": sid, "name_en": g_all["name_en"].iloc[0],
            "reported_radius_km": rep_r if rep_r is not None else float("nan"),
            "n_independent_beampasses": e["n"],
            # --- 1. empirical precision / repeatability ---
            "correction_m": e["median"],
            "empirical_median_residual_m": e["median"],
            "empirical_mad_m": e["mad"], "empirical_nmad_m": e["nmad"],
            "empirical_std_m": e["std"],
            "p05_m": e["p05"], "p95_m": e["p95"], "iqr_m": e["iqr"],
            "bootstrap_ci95_low_m": e["boot_lo"], "bootstrap_ci95_high_m": e["boot_hi"],
            # --- 2. systematic budget, kept separate, NOT combined in quadrature ---
            # published operation accuracy, not a sigma -- see the constant's note
            "epsg9902_op_accuracy_m": EPSG9902_OP_ACCURACY_M,
            "sigma_gauge_zero_m": "not independently constrained",
            "sigma_egg2015_model_m": "unresolved (not inferred from these gauges)",
            "sigma_atl13_bias_m": "unresolved (see rgt_bias diagnostics)",
            "temporal_mismatch_spread_m": temporal,
            "radius_ladder_spread_m": radius_spread,
            "flag": "LOW_SAMPLE" if e["n"] < MIN_INDEPENDENT else "OK",
        })
    return pd.DataFrame(rows).reset_index(drop=True)


def cross_station(station_tbl: pd.DataFrame) -> dict:
    """Is one Kakhovka-wide corrector justified? Diagnostics only.

    **Read ``fit_vs_delta_epsg9902_COUPLED`` with care.** By construction

        c_station = gauge_zero + stage + delta_EPSG9902 - H_ICESat_EGG2015

    so ``delta_epsg9902_m`` is one of ``c``'s own additive constituents. The
    regression of ``c`` on it is therefore *algebraically coupled* and cannot be
    read causally, however good its R^2 looks — it is descriptive only. The
    genuinely independent version of this test needs an external quasigeoid
    (УКГ2025), where ``c_geodetic = zeta_EGG2015 - zeta_UKG2025`` is computed
    without touching the gauges at all.

    ``fit_vs_lon``, ``fit_vs_lat`` and ``fit_vs_icesat_level`` are not coupled in
    this way and can be read normally.
    """
    ok = station_tbl[station_tbl["flag"] == "OK"].copy()
    usable = station_tbl[np.isfinite(station_tbl["c_station_m"])].copy()
    if usable.empty:
        return {"n_stations": 0}

    def _lin(x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() < 3:
            return {"slope": float("nan"), "intercept": float("nan"), "r2": float("nan"),
                    "n": int(m.sum())}
        s, b = np.polyfit(x[m], y[m], 1)
        pred = s * x[m] + b
        ss_res = float(np.sum((y[m] - pred) ** 2))
        ss_tot = float(np.sum((y[m] - y[m].mean()) ** 2))
        return {"slope": float(s), "intercept": float(b),
                "r2": 1 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
                "n": int(m.sum())}

    c = usable["c_station_m"].to_numpy(float)
    return {
        "n_stations": int(len(usable)),
        "n_stations_ok": int(len(ok)),
        "median_c_m": float(np.median(c)),
        "station_to_station_nmad_m": nmad(c),
        "station_to_station_std_m": float(np.std(c, ddof=1)) if len(c) > 1 else float("nan"),
        "range_m": float(c.max() - c.min()),
        "min_c_m": float(c.min()), "max_c_m": float(c.max()),
        "median_bootstrap_ci_halfwidth_m": float(np.median(
            (usable["bootstrap_ci95_high_m"] - usable["bootstrap_ci95_low_m"]) / 2
        )),
        "fit_vs_lon": _lin(usable["lon"], c),
        "fit_vs_lat": _lin(usable["lat"], c),
        # NB: coupled — delta_epsg9902_m is an additive constituent of c (docstring)
        "fit_vs_delta_epsg9902_COUPLED": _lin(usable["delta_epsg9902_m"], c),
        "fit_vs_icesat_level": _lin(usable["median_h_icesat_egg2015_m"], c),
    }
