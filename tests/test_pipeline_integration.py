"""End-to-end exercise of the transform chain on synthetic data (no network/files)."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.aggregate import pass_level_table
from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.datum import estimate_empirical_alignment
from kakhovka_altimetry.gauges import OBS_COLUMNS
from kakhovka_altimetry.matchup import build_matchups
from kakhovka_altimetry.vertical import GeoidGrid, add_evrs_columns


def _synthetic_segments(n_passes=6, n_per_pass=60, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    base_date = pd.Timestamp("2021-05-01T12:00:00Z")
    true_wse_evrs = 16.0
    zeta = 25.0  # constant quasigeoid over the toy AOI
    for k in range(n_passes):
        t = base_date + pd.Timedelta(days=30 * k)
        lat = np.linspace(47.20, 47.40, n_per_pass)
        h_evrs = true_wse_evrs + 0.02 * np.sin(k) + rng.normal(0, 0.03, n_per_pass)
        rows.append(pd.DataFrame({
            "time": t,
            "cycle": 10 + k,
            "rgt": 545,
            "gt": 40,
            "beam": "gt2r",
            "lat": lat,
            "lon": 34.10,
            "h_wgs84_m": h_evrs + zeta,          # ellipsoidal = EVRS + zeta
            "H_egm2008_m": h_evrs + 0.15,        # EGM2008 ~15 cm above EVRS here
            "stdev_water_surf_m": 0.05,
            "water_depth_m": 8.0,
        }))
    return pd.concat(rows, ignore_index=True)


def test_transform_chain():
    cfg = load_config()
    seg = _synthetic_segments()

    # constant geoid grid covering the toy AOI
    grid = GeoidGrid(
        lats=np.array([47.0, 47.5, 48.0]),
        lons=np.array([33.5, 34.0, 34.5]),
        values=np.full((3, 3), 25.0),
        crs="EPSG:4258",
    )
    seg["water_mask_pass"] = True
    evrs = add_evrs_columns(seg, cfg, geoid=grid)

    assert np.allclose(evrs["H_evrs_egg2015_m"], evrs["h_wgs84_m"] - 25.0)
    assert evrs["egm2008_minus_evrs_m"].abs().max() < 0.3
    assert set(evrs["period"]) == {"PRE_BREACH"}

    passes = pass_level_table(evrs, cfg)
    assert len(passes) == 6
    assert passes["qc_pass"].all()
    assert passes["median_wse_evrs_m"].between(15.9, 16.1).all()

    # synthetic gauge stage series ~3.5 m below the true WSE
    stage = passes["median_wse_evrs_m"].to_numpy() - 12.5
    obs = pd.DataFrame({
        "station_id": 80959,
        "datetime": pd.to_datetime(passes["datetime"], utc=True),
        "stage_m": stage,
        "WSE_baltic_m": stage + 12.0,
    })[OBS_COLUMNS]

    station = dataclasses.replace(
        cfg.gauges.stations[0],
        id=80959, lon=34.10, lat=47.30, gauge_zero_baltic_m=12.0,
        active_regimes=("PRE_BREACH",),
    )
    cfg_t = dataclasses.replace(
        cfg, gauges=dataclasses.replace(cfg.gauges, stations=(station,)),
    )

    m = build_matchups(passes, obs, cfg_t, qc_only=True)
    assert len(m) == 6
    assert m["alignment_residual_m"].to_numpy() == pytest.approx(12.5, abs=0.05)

    est = estimate_empirical_alignment(m, cfg_t)
    allrow = est[est["station"] == "ALL"].iloc[0]
    assert allrow["n_matchups"] == 6
    assert allrow["alignment_constant_m"] == pytest.approx(12.5, abs=0.05)
