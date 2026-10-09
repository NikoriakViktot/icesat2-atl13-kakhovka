import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.aggregate import (
    along_track_slope,
    mad,
    nmad,
    pass_level_table,
)
from kakhovka_altimetry.config import load_config


def test_mad_and_nmad():
    x = np.array([10.0, 10.0, 10.0, 10.0, 20.0])  # median 10, |dev| median 0
    assert mad(x) == 0.0
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])       # median 3, devs [2,1,0,1,2] -> mad 1
    assert mad(y) == 1.0
    assert nmad(y) == 1.4826


def test_along_track_slope_flat_water():
    lat = np.linspace(47.0, 47.2, 50)
    lon = np.full_like(lat, 34.0)
    h = np.full_like(lat, 16.0) + np.random.default_rng(0).normal(0, 0.01, lat.size)
    slope, length = along_track_slope(lat, lon, h)
    assert abs(slope) < 0.05          # ~flat, m/km
    assert 20 < length < 25           # ~0.2 deg latitude ~ 22 km


def test_along_track_slope_detects_tilt():
    lat = np.linspace(47.0, 47.2, 50)
    lon = np.full_like(lat, 34.0)
    dist_km = (lat - lat[0]) * 111.0
    h = 16.0 + 0.5 * dist_km          # 0.5 m per km
    slope, _ = along_track_slope(lat, lon, h)
    assert slope == pytest.approx(0.5, rel=0.02)


def test_pass_level_table_groups_and_qc():
    cfg = load_config()
    rng = np.random.default_rng(1)
    lat = np.linspace(47.0, 47.15, 60)
    df = pd.DataFrame(
        {
            "time": pd.Timestamp("2022-05-01T12:00:00Z"),
            "rgt": 545,
            "beam": "gt2r",
            "lat": lat,
            "lon": 34.0,
            "h_wgs84_m": 40.0,
            "H_egm2008_m": 16.1,
            "H_evrs_egg2015_m": 16.0 + rng.normal(0, 0.02, lat.size),
            "stdev_water_surf_m": 0.05,
            "period": "PRE_BREACH",
            "water_mask_pass": True,
        }
    )
    out = pass_level_table(df, cfg)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["n_points"] == 60
    assert row["median_wse_evrs_m"] == pytest.approx(16.0, abs=0.05)
    assert row["period"] == "PRE_BREACH"
    assert row["transect"] == "545_gt2r"
    assert row["year"] == 2022
    assert bool(row["qc_pass"]) is True


def test_pass_level_table_rejects_short_track():
    cfg = load_config()
    df = pd.DataFrame(
        {
            "time": pd.Timestamp("2022-05-01T12:00:00Z"),
            "rgt": 545,
            "beam": "gt2r",
            "lat": np.linspace(47.0, 47.001, 30),   # ~0.1 km
            "lon": 34.0,
            "h_wgs84_m": 40.0,
            "H_egm2008_m": 16.1,
            "H_evrs_egg2015_m": np.full(30, 16.0),
            "stdev_water_surf_m": 0.05,
            "period": "PRE_BREACH",
            "water_mask_pass": True,
        }
    )
    row = pass_level_table(df, cfg).iloc[0]
    assert bool(row["qc_pass"]) is False
    assert "track_too_short" in row["qc_flags"]
