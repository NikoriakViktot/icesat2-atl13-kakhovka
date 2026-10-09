"""Per-pass hydrological quality control.

A "pass" is one beam crossing the water on one date: group key
``(date, rgt, beam)``. QC works on the aggregated statistics produced by
:mod:`kakhovka_altimetry.aggregate`, not on raw statistics alone -- the intent is
to reject shoreline contamination, too-short tracks and non-flat surfaces, not
merely to sigma-clip.
"""

from __future__ import annotations

import pandas as pd

from .config import QCConfig

# Individual flag names, in evaluation order.
FLAG_TOO_FEW_POINTS = "too_few_points"
FLAG_MAD_TOO_LARGE = "mad_too_large"
FLAG_RANGE_TOO_LARGE = "range_too_large"
FLAG_TRACK_TOO_SHORT = "track_too_short"
FLAG_STDEV_TOO_LARGE = "stdev_too_large"
FLAG_SLOPE_TOO_STEEP = "slope_too_steep"


def evaluate_pass(stats: pd.Series | dict, qc: QCConfig) -> tuple[bool, str]:
    """Return ``(qc_pass, qc_flags)`` for one aggregated pass.

    ``qc_flags`` is a ``"|"``-joined list of the tripped flags (empty when clean).
    """
    g = stats.get if isinstance(stats, dict) else stats.__getitem__
    flags: list[str] = []

    if _lt(g("n_points"), qc.min_points_per_pass):
        flags.append(FLAG_TOO_FEW_POINTS)
    if _gt(g("mad_m"), qc.max_mad_m):
        flags.append(FLAG_MAD_TOO_LARGE)
    if _gt(g("range_m"), qc.max_range_m):
        flags.append(FLAG_RANGE_TOO_LARGE)
    if _lt(g("track_length_km"), qc.min_track_length_km):
        flags.append(FLAG_TRACK_TOO_SHORT)
    if _gt(g("mean_stdev_water_surf_m"), qc.max_stdev_water_surf_m):
        flags.append(FLAG_STDEV_TOO_LARGE)
    # Along-track slope is only meaningful once the track is long enough; a steep
    # fit over a short clip is noise, not a tilted surface.
    if (
        not _lt(g("track_length_km"), qc.min_track_length_km)
        and _gt(abs_or_nan(g("along_track_slope_m_per_km")), qc.max_along_track_slope_m_per_km)
    ):
        flags.append(FLAG_SLOPE_TOO_STEEP)

    return (len(flags) == 0, "|".join(flags))


def abs_or_nan(x):
    try:
        return abs(x)
    except TypeError:
        return float("nan")


def _lt(value, threshold) -> bool:
    return pd.notna(value) and value < threshold


def _gt(value, threshold) -> bool:
    return pd.notna(value) and value > threshold
