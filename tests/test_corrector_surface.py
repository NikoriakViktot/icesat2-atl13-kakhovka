"""Phase 2d corrector surface -- nearest-station lookup, on synthetic data."""

import dataclasses

import numpy as np
import pandas as pd

from kakhovka_altimetry import corrector_surface as cs
from kakhovka_altimetry.config import load_config

STATIONS = pd.DataFrame({
    "station_id": [1, 2],
    "slug": ["north", "south"],
    "name_en": ["North", "South"],
    "lat": [48.0, 47.0],
    "lon": [34.0, 34.0],
    "c_station_m": [-0.10, -0.20],
    "sigma_m": [0.03, 0.05],
    "reported_radius_km": [2.0, 2.0],
    "n_matchups": [10, 8],
    "flag": ["OK", "OK"],
})


def test_nearest_station_assigns_closer_station():
    lat = np.array([47.9, 47.1])
    lon = np.array([34.0, 34.0])
    out = cs.nearest_station(lat, lon, STATIONS)
    assert list(out["nearest_control_station"]) == ["north", "south"]
    assert list(out["egg2015_to_evrf2019_corrector_m"]) == [-0.10, -0.20]
    assert list(out["corrector_uncertainty_m"]) == [0.03, 0.05]
    assert (out["distance_to_control_km"] > 0).all()


def test_nearest_station_midpoint_ties_to_first():
    lat = np.array([47.5])
    lon = np.array([34.0])
    out = cs.nearest_station(lat, lon, STATIONS)
    # equidistant -> argmin picks the first row deterministically
    assert out["nearest_control_station"].iloc[0] == "north"


def test_augment_points_adds_empirical_evrf2019():
    df = pd.DataFrame({
        "lat": [48.0, 47.0],
        "lon": [34.0, 34.0],
        "H_evrs_egg2015_m": [16.00, 16.00],
    })
    out = cs.augment_points(df, STATIONS)
    assert list(out["h_evrf2019_empirical_m"]) == [15.90, 15.80]
    for col in cs.CORRECTOR_COLUMNS:
        assert col in out.columns


def test_augment_points_custom_columns():
    df = pd.DataFrame({
        "lat_mean": [48.0], "lon_mean": [34.0], "median_wse_evrs_m": [15.5],
    })
    out = cs.augment_points(
        df, STATIONS, lat_col="lat_mean", lon_col="lon_mean",
        level_col="median_wse_evrs_m",
    )
    assert out["h_evrf2019_empirical_m"].iloc[0] == 15.4


def test_build_corrector_grid_covers_bbox_and_matches_lookup():
    cfg = load_config()
    small_bbox = dataclasses.replace(cfg, aoi_bbox=(33.9, 46.9, 34.1, 48.1))
    corrector, uncertainty = cs.build_corrector_grid(small_bbox, STATIONS, cell_deg=0.1)
    assert corrector.values.shape == uncertainty.values.shape
    assert np.isin(np.unique(corrector.values), STATIONS["c_station_m"].to_numpy()).all()
    # north station (lat 48.0) should dominate the top rows
    top_row_value = corrector.values[-1, 0]
    assert top_row_value == STATIONS.loc[STATIONS["slug"] == "north", "c_station_m"].iloc[0]


def test_load_station_correctors_drops_nan_and_renames(tmp_path):
    cfg = dataclasses.replace(load_config(), repo_root=tmp_path)
    tables = cfg.tables_dir
    tables.mkdir(parents=True)
    df = pd.DataFrame({
        "station_id": [1, 2], "slug": ["a", "b"], "name_en": ["A", "B"],
        "lat": [47.0, 48.0], "lon": [34.0, 35.0],
        "c_station_m": [-0.1, np.nan], "empirical_nmad_m": [0.03, 0.04],
        "reported_radius_km": [2.0, np.nan], "n_matchups": [10, 0],
        "flag": ["OK", "LOW_SAMPLE"],
    })
    df.to_csv(tables / "egg2015_to_evrf2019_by_station.csv", index=False)
    out = cs.load_station_correctors(cfg)
    assert list(out["slug"]) == ["a"]
    assert "sigma_m" in out.columns and "empirical_nmad_m" not in out.columns
