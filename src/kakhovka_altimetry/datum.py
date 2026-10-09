"""Phase 2 — the empirical vertical alignment constant (NOT a Baltic->EVRS offset).

For a calm still-water pass near a gauge at time t:

    alignment_residual(t) = H_EVRS_ICESat(t) - gauge_stage(t)

and the constant is

    alignment_constant_m = median( alignment_residual )   over calm PRE_BREACH passes.

It is the number to add to a gauge stage series to obtain an
ICESat-2/EGG2015-consistent water-surface elevation:

    H_gauge_aligned(t) = stage(t) + alignment_constant_m

It **incorporates** the gauge zero elevation, the Baltic-1977 -> EVRS datum
difference, and any systematic ICESat-2 / vertical-model bias, and therefore
**must not** be interpreted as a pure Baltic-to-EVRS transformation. Splitting it
needs one external constraint -- see :func:`solve_geodetic_datum_offset`.

This module is not exercised by V1 (ICESat-only). It is kept ready for Phase 2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config
from .stats import residual_stats

DEFAULT_REGIMES = ("PRE_BREACH",)
_RESIDUAL_COL = "alignment_residual_m"


def _residuals(matchups: pd.DataFrame, regimes) -> pd.DataFrame:
    """Rows usable for the estimate: calm regime, with an alignment residual.

    ``alignment_residual_m`` = ``WSE_ICESat_evrs_m - stage_m`` is expected on the
    matchup table; it is recomputed here if the raw columns are present.
    """
    df = matchups[matchups.get("period", matchups.get("regime")).isin(regimes)].copy()
    if _RESIDUAL_COL not in df.columns and {"WSE_ICESat_evrs_m", "stage_m"} <= set(df.columns):
        df[_RESIDUAL_COL] = df["WSE_ICESat_evrs_m"] - df["stage_m"]
    return df.dropna(subset=[_RESIDUAL_COL])


def estimate_empirical_alignment(
    matchups: pd.DataFrame,
    cfg: Config,
    *,
    regimes: tuple[str, ...] = DEFAULT_REGIMES,
    per_station: bool = True,
    reference: str = "ATL13+gauge",
) -> pd.DataFrame:
    """Estimate ``alignment_constant_m`` per station (+ pooled ``ALL`` row).

    Columns: ``station, n_matchups, alignment_constant_m, nmad_m, ci95_low_m,
    ci95_high_m, period, reference``.
    """
    df = _residuals(matchups, regimes)
    period = "+".join(regimes)

    groups: list[tuple[str, pd.DataFrame]] = []
    if per_station and "station_id" in df.columns:
        groups += [(str(sid), g) for sid, g in df.groupby("station_id")]
    groups.append(("ALL", df))

    rows = []
    for name, g in groups:
        st = residual_stats(g[_RESIDUAL_COL].to_numpy(float))
        rows.append({
            "station": name,
            "n_matchups": int(st["n"]) if np.isfinite(st["n"]) else 0,
            "alignment_constant_m": st["bias"],          # median-centred mean; see note
            "nmad_m": st["NMAD"],
            "ci95_low_m": st["ci95_lo"],
            "ci95_high_m": st["ci95_hi"],
            "period": period,
            "reference": reference,
        })
    return pd.DataFrame(rows)


def summarise(estimate: pd.DataFrame) -> str:
    """One-line human summary of the pooled row, with the mandatory caveat."""
    allr = estimate[estimate["station"] == "ALL"]
    if allr.empty or not np.isfinite(allr["alignment_constant_m"].iloc[0]):
        return "No calm-regime matchups available to estimate the alignment constant."
    r = allr.iloc[0]
    return (
        f"alignment_constant_m = {r['alignment_constant_m']:+.3f} m "
        f"(NMAD {r['nmad_m']:.3f} m, n={r['n_matchups']}, "
        f"95% CI [{r['ci95_low_m']:+.3f}, {r['ci95_high_m']:+.3f}]). "
        f"Empirical vertical alignment constant -- incorporates the gauge zero, the "
        f"Baltic-1977 -> EVRS datum difference and systematic ICESat/EGG2015 bias; "
        f"not a pure datum offset."
    )


DECOMPOSITION_COLUMNS = [
    "station_id", "slug", "name", "name_en", "lat", "lon",
    "reported_radius_km", "n_reported",
    "alignment_constant_m", "nominal_zero_m", "delta_empirical_m",
    "delta_official_m", "evrf2019_minus_evrf2007_m", "tide_system_correction_m",
    "delta_unexplained_m", "implied_gauge_zero_baltic_m",
    "official_within_national_range", "notes",
]


def decompose_alignment(summary: pd.DataFrame, grid, cfg: Config) -> pd.DataFrame:
    """Split the empirical constant using the official BS-77 -> EVRF2019 grid.

        delta_empirical   = alignment_constant_m - nominal_zero
        delta_official    = grid(lat, lon)
        delta_unexplained = delta_empirical - delta_official - frame terms
        implied_zero      = alignment_constant_m - delta_official - frame terms
                          == nominal_zero + delta_unexplained

    ``delta_unexplained_m`` still contains the gauge-zero error, EGG2015's model
    error over Ukraine (~0.1 m) and any ATL13 bias. It is **not** a residual of the
    datum transformation.
    """
    from .official_datum import correction_at

    ot = cfg.official_transform
    frame = ot.frame_terms_m
    pub = ot.published_stats
    lo, hi = pub.get("min_m", -np.inf), pub.get("max_m", np.inf)

    df = summary.copy()
    df["delta_official_m"] = correction_at(
        grid, df["lat"].to_numpy(float), df["lon"].to_numpy(float)
    )
    df["nominal_zero_m"] = df["gauge_zero_baltic_m"]
    df["delta_empirical_m"] = df["alignment_constant_m"] - df["nominal_zero_m"]
    df["evrf2019_minus_evrf2007_m"] = ot.evrf2019_minus_evrf2007_m
    df["tide_system_correction_m"] = ot.tide_system_correction_m
    df["delta_unexplained_m"] = (
        df["delta_empirical_m"] - df["delta_official_m"] - frame
    )
    df["implied_gauge_zero_baltic_m"] = (
        df["alignment_constant_m"] - df["delta_official_m"] - frame
    )
    df["official_within_national_range"] = df["delta_official_m"].between(lo, hi)
    if "note" in df.columns:
        df = df.rename(columns={"note": "notes"})
    for c in DECOMPOSITION_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[DECOMPOSITION_COLUMNS].reset_index(drop=True)


def decompose_by(
    matchups: pd.DataFrame, grid, cfg: Config, group_cols: list[str],
    *, station_lat: float, station_lon: float, nominal_zero_m: float,
) -> pd.DataFrame:
    """Same decomposition, grouped (by radius, by RGT, ...) for one station.

    The official correction is evaluated once at the post; only the empirical side
    varies with the grouping, which is the point — ``delta_unexplained_m`` must be
    flat across radii if it is a datum/zero term rather than a radius artefact.
    """
    from .official_datum import correction_at

    ot = cfg.official_transform
    frame = ot.frame_terms_m
    d_off = float(correction_at(grid, station_lat, station_lon)[0])

    rows = []
    for keys, g in matchups.groupby(group_cols, dropna=False):
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        c = g["alignment_constant_m"].to_numpy(float)
        c = c[np.isfinite(c)]
        if c.size == 0:
            continue
        const = float(np.median(c))
        row = dict(zip(group_cols, key_tuple, strict=True))
        row.update({
            "n_matchups": int(c.size),
            "alignment_constant_m": const,
            "nmad_m": _nmad(c),
            "delta_empirical_m": const - nominal_zero_m,
            "delta_official_m": d_off,
            "delta_unexplained_m": const - nominal_zero_m - d_off - frame,
            "implied_gauge_zero_baltic_m": const - d_off - frame,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _nmad(x: np.ndarray) -> float:
    from .aggregate import nmad
    return nmad(x)


def solve_geodetic_datum_offset(cfg: Config, *_args, **_kwargs):
    """Kept for callers that only want to know whether a decomposition is possible.

    Phase 2b implements the real work in :func:`decompose_alignment`; this raises
    only when no official grid is configured.
    """
    if cfg.official_transform.available:
        raise RuntimeError(
            "use decompose_alignment(summary, grid, cfg) — the official grid at "
            f"{cfg.official_transform.path} is available."
        )
    raise NotImplementedError(
        "No official transformation grid configured. Fetch it with "
        "`python scripts/datum_comparison.py --download`, or supply a surveyed "
        "BS-77 gauge zero / a GNSS benchmark height instead."
    )
