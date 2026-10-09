import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.datum import (
    estimate_empirical_alignment,
    solve_geodetic_datum_offset,
    summarise,
)


def _matchups(c_true=12.31, n=40, seed=0):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2020-04-01", periods=n, freq="9D", tz="UTC")
    stage = 3.4 + rng.normal(0, 0.1, n)
    icesat = stage + c_true + rng.normal(0, 0.03, n)
    return pd.DataFrame({
        "datetime": t,
        "station_id": 80959,
        "period": "PRE_BREACH",
        "WSE_ICESat_evrs_m": icesat,
        "stage_m": stage,
        "alignment_residual_m": icesat - stage,
        "time_difference_hours": rng.uniform(0, 6, n),
        "distance_to_gauge_km": rng.uniform(1, 20, n),
    })


def test_estimate_recovers_alignment_constant():
    cfg = load_config()
    est = estimate_empirical_alignment(_matchups(c_true=12.31), cfg)
    row = est[est["station"] == "ALL"].iloc[0]
    assert row["alignment_constant_m"] == pytest.approx(12.31, abs=0.02)
    assert row["n_matchups"] == 40
    assert row["period"] == "PRE_BREACH"
    assert row["reference"] == "ATL13+gauge"
    assert set(est.columns) == {
        "station", "n_matchups", "alignment_constant_m", "nmad_m",
        "ci95_low_m", "ci95_high_m", "period", "reference",
    }


def test_residual_recomputed_when_missing():
    cfg = load_config()
    m = _matchups().drop(columns="alignment_residual_m")
    est = estimate_empirical_alignment(m, cfg)
    assert est[est["station"] == "ALL"].iloc[0]["alignment_constant_m"] == pytest.approx(
        12.31, abs=0.02
    )


def test_summary_string_and_empty():
    cfg = load_config()
    s = summarise(estimate_empirical_alignment(_matchups(), cfg))
    assert "alignment_constant_m" in s
    assert "not a pure datum offset" in s
    empty = _matchups().iloc[0:0]
    assert "No calm-regime" in summarise(estimate_empirical_alignment(empty, cfg))


def test_geodetic_solver_requires_a_grid():
    """Phase 2b implements the real decomposition; the wrapper only routes."""
    cfg = load_config()
    expected = RuntimeError if cfg.official_transform.available else NotImplementedError
    with pytest.raises(expected):
        solve_geodetic_datum_offset(cfg)
