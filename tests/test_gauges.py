import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.gauges import OBS_COLUMNS, gauge_value_at


def _obs():
    times = pd.to_datetime(
        ["2022-05-01T06:00:00Z", "2022-05-01T18:00:00Z", "2022-05-02T06:00:00Z"]
    )
    return pd.DataFrame(
        {
            "station_id": "nikopol",
            "datetime": times,
            "stage_m": [1.0, 1.2, 1.4],
            "WSE_baltic_m": [16.0, 16.2, 16.4],
            "WSE_evrs_m": [16.1, 16.3, 16.5],
            "baltic_to_evrs_offset_m": 0.1,
            "datum_to_evrs_known": True,
        }
    )[OBS_COLUMNS]


def test_linear_interpolation_midpoint():
    val, interp, gap = gauge_value_at(
        _obs(), "nikopol", pd.Timestamp("2022-05-01T12:00:00Z"),
        column="WSE_baltic_m", method="linear",
    )
    assert val == pytest.approx(16.1)      # halfway between 16.0 and 16.2
    assert interp is True
    assert gap == pytest.approx(6.0)       # nearest obs is 6 h away


def test_nearest_method():
    val, interp, _ = gauge_value_at(
        _obs(), "nikopol", pd.Timestamp("2022-05-01T13:00:00Z"),
        column="WSE_baltic_m", method="nearest",
    )
    assert val == pytest.approx(16.2)
    assert interp is False


def test_gap_beyond_limit_returns_nan():
    val, _, gap = gauge_value_at(
        _obs(), "nikopol", pd.Timestamp("2022-05-10T00:00:00Z"),
        column="WSE_baltic_m", max_gap_hours=12,
    )
    assert np.isnan(val)
    assert gap > 12


def test_unknown_station_returns_nan():
    val, _, _ = gauge_value_at(_obs(), "ghost", pd.Timestamp("2022-05-01T12:00:00Z"))
    assert np.isnan(val)


def test_wse_arithmetic():
    # WSE_baltic = zero + stage ; WSE_evrs = WSE_baltic + offset
    zero, stage, offset = 15.0, 1.25, 0.1
    assert (zero + stage) == pytest.approx(16.25)
    assert (zero + stage + offset) == pytest.approx(16.35)
