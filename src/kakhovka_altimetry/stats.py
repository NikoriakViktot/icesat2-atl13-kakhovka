"""Residual statistics for the ICESat-2 vs gauge comparison."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .aggregate import nmad


def residual_stats(residuals: np.ndarray) -> dict[str, float]:
    """Summary statistics of a residual vector (ICESat - gauge), in metres."""
    r = np.asarray(residuals, float)
    r = r[np.isfinite(r)]
    n = r.size
    if n == 0:
        return {k: float("nan") for k in
                ("n", "bias", "MAE", "RMSE", "std", "NMAD", "ci95_lo", "ci95_hi")}
    bias = float(np.mean(r))
    std = float(np.std(r, ddof=1)) if n > 1 else float("nan")
    sem = std / np.sqrt(n) if n > 1 else float("nan")
    return {
        "n": float(n),
        "bias": bias,
        "MAE": float(np.mean(np.abs(r))),
        "RMSE": float(np.sqrt(np.mean(r**2))),
        "std": std,
        "NMAD": nmad(r),
        "ci95_lo": bias - 1.96 * sem if n > 1 else float("nan"),
        "ci95_hi": bias + 1.96 * sem if n > 1 else float("nan"),
    }


def agreement(icesat: np.ndarray, gauge: np.ndarray) -> dict[str, float]:
    """R^2 and slope/intercept of ICESat vs gauge WSE."""
    x = np.asarray(gauge, float)
    y = np.asarray(icesat, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 3:
        return {"n": float(x.size), "r2": float("nan"), "slope": float("nan"),
                "intercept": float("nan")}
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"n": float(x.size), "r2": r2, "slope": float(slope),
            "intercept": float(intercept)}


def stats_by(matchups: pd.DataFrame, group_cols: list[str],
             *, residual_col: str = "alignment_residual_m") -> pd.DataFrame:
    """Residual statistics grouped by ``group_cols`` (e.g. ['regime'] or ['station_id'])."""
    out = []
    for keys, grp in matchups.groupby(group_cols, dropna=False):
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_cols, key_tuple, strict=True))
        row.update(residual_stats(grp[residual_col].to_numpy(float)))
        out.append(row)
    return pd.DataFrame(out)
