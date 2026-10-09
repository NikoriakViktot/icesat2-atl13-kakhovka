"""EGG2015 -> EVRF2019 corrector on synthetic data — no network, no data files."""

import dataclasses

import numpy as np
import pandas as pd

from kakhovka_altimetry import egg2015_corrector as ec
from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.gauges import OBS_COLUMNS
from kakhovka_altimetry.vertical import GeoidGrid

STATION_LAT, STATION_LON = 47.771208, 35.148890
ZERO = 12.00
DELTA_OFF = 0.200          # planted EPSG:9902 correction
TRUE_C = -0.150            # planted corrector: wse = zero + stage + delta_off - c
DEG_PER_KM_LAT = 1.0 / 111.32


def _grid():
    """Constant BS-77 -> EVRF2019 grid over the reservoir."""
    return GeoidGrid(
        lats=np.array([46.0, 48.5]),
        lons=np.array([33.0, 36.0]),
        values=np.full((2, 2), DELTA_OFF),
        crs="EPSG:4258",
    )


def _station(cfg):
    return dataclasses.replace(
        cfg.gauges.stations[0],
        id=80959, name="с. Розумівка", slug="rozumivka", name_en="Rozumivka",
        lat=STATION_LAT, lon=STATION_LON, gauge_zero_baltic_m=ZERO,
        active_regimes=("PRE_BREACH",),
    )


def _segments(specs, n_per_pass=30, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for date, rgt, beam, off_km, stage in specs:
        wse = ZERO + stage + DELTA_OFF - TRUE_C
        frames.append(pd.DataFrame({
            "time": pd.Timestamp(f"{date}T09:00:00Z"),
            "rgt": rgt, "beam": beam,
            "lat": STATION_LAT + off_km * DEG_PER_KM_LAT
            + rng.normal(0, 1e-5, n_per_pass),
            "lon": STATION_LON,
            "h_wgs84_m": wse + 22.0,
            "H_egm2008_m": wse - 0.145,
            "H_evrs_egg2015_m": wse + rng.normal(0, 0.01, n_per_pass),
            "stdev_water_surf_m": 0.04,
            "period": "PRE_BREACH", "water_mask_pass": True,
        }))
    return pd.concat(frames, ignore_index=True)


def _term_obs(specs):
    rows = []
    for date, *_rest, stage in specs:
        for hour in (6, 18):
            rows.append({
                "station_id": 80959,
                "datetime": pd.Timestamp(f"{date}T{hour:02d}:00:00Z"),
                "stage_m": stage, "WSE_baltic_m": ZERO + stage,
            })
    return pd.DataFrame(rows)[OBS_COLUMNS].drop_duplicates(
        subset=["station_id", "datetime"]
    )


SPECS = [
    ("2021-03-01", 205, "gt1l", 0.3, 3.90),
    ("2021-05-02", 205, "gt1r", 0.8, 4.05),
    ("2021-07-03", 989, "gt2l", 1.5, 3.70),
    ("2021-09-04", 989, "gt2r", 1.8, 3.85),
    ("2021-11-05", 205, "gt3l", 0.6, 3.60),
    ("2022-01-06", 989, "gt1l", 1.2, 3.55),
]


def test_c_station_sign_and_value():
    cfg = load_config()
    st = _station(cfg)
    m = ec.station_matchups(_segments(SPECS), _term_obs(SPECS), pd.DataFrame(),
                            st, cfg, _grid(), radii=(2.0,))
    assert not m.empty
    # c = (zero + stage + delta_off) - wse, recovered to the noise floor
    assert m["c_station_A_m"].median() == 0.0 or abs(m["c_station_A_m"].median() - TRUE_C) < 0.01
    # explicit identity on one row
    row = m.iloc[0]
    lhs = row["gauge_zero_bs77_m"] + row["stage_A_m"] + row["delta_epsg9902_m"] \
        - row["h_icesat_egg2015_m"]
    assert row["c_station_A_m"] == lhs


def test_by_radius_and_low_sample_flag():
    cfg = load_config()
    st = _station(cfg)
    m = ec.station_matchups(_segments(SPECS), _term_obs(SPECS), pd.DataFrame(),
                            st, cfg, _grid())
    ladder = ec.by_radius(m)
    two = ladder[np.isclose(ladder["radius_km"], 2.0)].iloc[0]
    assert two["n_matchups"] == 6
    assert two["flag"] == "OK"
    assert abs(two["c_station_m"] - TRUE_C) < 0.01
    half = ladder[np.isclose(ladder["radius_km"], 0.5)].iloc[0]
    assert half["flag"] == "LOW_SAMPLE"


def test_bootstrap_median_ci_brackets_median():
    x = np.array([-0.16, -0.15, -0.14, -0.15, -0.13, -0.17, -0.15, -0.14])
    lo, hi = ec.bootstrap_median_ci(x, n=2000, seed=1)
    assert lo <= np.median(x) <= hi
    assert hi - lo < 0.05


def test_pre_breach_only():
    cfg = load_config()
    st = _station(cfg)
    seg = _segments(SPECS)
    seg.loc[seg["rgt"] == 205, "period"] = "POST_BREACH"
    m = ec.station_matchups(seg, _term_obs(SPECS), pd.DataFrame(), st, cfg,
                            _grid(), radii=(2.0,))
    assert (m["rgt"] == 989).all()
