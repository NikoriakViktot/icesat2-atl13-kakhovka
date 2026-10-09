"""Phase 3 spatial models — synthetic data, no files, no network."""

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry import spatial_models as sm

# Six controls roughly along the Kakhovka reservoir.
_STATIONS = pd.DataFrame({
    "slug": ["a", "b", "c", "d", "e", "f"],
    "name_en": ["A", "B", "C", "D", "E", "F"],
    "lat": [46.78, 47.18, 47.55, 47.46, 47.77, 47.57],
    "lon": [33.37, 33.93, 34.38, 34.82, 35.15, 35.33],
    "c_station_m": [-0.128, -0.189, -0.208, -0.150, -0.146, -0.217],
})


def test_projection_round_trips_to_metres_and_back():
    proj = sm.local_projection(_STATIONS)
    x, y = proj.forward(_STATIONS["lat"], _STATIONS["lon"])
    lat, lon = proj.inverse(x, y)
    assert np.allclose(lat, _STATIONS["lat"], atol=1e-6)
    assert np.allclose(lon, _STATIONS["lon"], atol=1e-6)
    # spread is tens of km, i.e. real metres not degrees
    assert np.ptp(x) > 100_000 and np.ptp(y) > 50_000


def test_constant_is_the_median():
    m = sm.fit_constant(_STATIONS)
    assert m.predict([47.0], [34.0])[0] == pytest.approx(
        float(np.median(_STATIONS["c_station_m"]))
    )


def test_plane_recovers_an_exact_plane():
    proj = sm.local_projection(_STATIONS)
    x, y = proj.forward(_STATIONS["lat"], _STATIONS["lon"])
    planted = 0.01 + 3e-7 * x - 1e-7 * y
    df = _STATIONS.assign(c_station_m=planted)
    m = sm.fit_plane(df, proj)
    pred = m.predict(_STATIONS["lat"].to_numpy(), _STATIONS["lon"].to_numpy())
    assert np.allclose(pred, planted, atol=1e-9)


def test_idw_returns_the_station_value_at_a_station_node():
    m = sm.fit_idw(_STATIONS, power=2)
    for _, r in _STATIONS.iterrows():
        assert m.predict([r["lat"]], [r["lon"]])[0] == pytest.approx(r["c_station_m"])


def test_linear_is_nan_outside_the_convex_hull():
    m = sm.fit_linear(_STATIONS)
    # far south-west of every control
    assert np.isnan(m.predict([46.0], [32.0])[0])


def test_loso_cv_shapes_and_training_count():
    per_row, summary = sm.leave_one_station_out_cv(_STATIONS)
    assert set(per_row["model"]) == set(sm.MODEL_NAMES)
    assert (per_row["training_station_count"] == 5).all()
    assert len(per_row) == len(sm.MODEL_NAMES) * len(_STATIONS)
    assert list(summary["model"]) == list(
        summary.sort_values("loso_rmse_m")["model"]
    )  # summary is sorted best-first
    # constant's LOSO error is bounded by the spread of the data
    crow = summary[summary["model"] == "constant"].iloc[0]
    assert crow["max_abs_error_m"] < float(np.ptp(_STATIONS["c_station_m"]))


def test_fit_all_reports_failures_without_raising():
    two = _STATIONS.iloc[:2]
    models = sm.fit_all(two)
    assert isinstance(models["plane"], Exception)      # needs >= 3
    assert isinstance(models["constant"], sm._Constant)
