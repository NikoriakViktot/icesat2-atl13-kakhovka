"""Local alignment on synthetic data — no network, no data files."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.gauges import OBS_COLUMNS
from kakhovka_altimetry.local_alignment import (
    distance_to_station,
    local_pass_levels,
    match_local,
    per_rgt,
    radius_ladder,
    reservoir_level_by_date,
)

STATION_LAT, STATION_LON = 47.771208, 35.148890
ZERO = 12.00
TRUE_C = 12.34          # alignment constant we plant in the synthetic data
DEG_PER_KM_LAT = 1.0 / 111.32


def _station(cfg):
    return dataclasses.replace(
        cfg.gauges.stations[0],
        id=80959, name="с. Розумівка",
        lat=STATION_LAT, lon=STATION_LON, gauge_zero_baltic_m=ZERO,
        active_regimes=("PRE_BREACH",),
    )


def _segments(specs, n_per_pass=30, seed=0, period="PRE_BREACH"):
    """specs: list of (date_str, rgt, beam, offset_km, stage_m)."""
    rng = np.random.default_rng(seed)
    frames = []
    for date, rgt, beam, off_km, stage in specs:
        t = pd.Timestamp(f"{date}T09:00:00Z")
        lat = STATION_LAT + off_km * DEG_PER_KM_LAT
        wse = stage + TRUE_C
        frames.append(pd.DataFrame({
            "time": t,
            "rgt": rgt,
            "beam": beam,
            "lat": lat + rng.normal(0, 1e-5, n_per_pass),
            "lon": STATION_LON,
            "h_wgs84_m": wse + 22.0,
            "H_egm2008_m": wse - 0.145,
            "H_evrs_egg2015_m": wse + rng.normal(0, 0.01, n_per_pass),
            "stdev_water_surf_m": 0.04,
            "period": period,
            "water_mask_pass": True,
        }))
    return pd.concat(frames, ignore_index=True)


def _obs(specs):
    rows = []
    for date, _rgt, _beam, _off, stage in specs:
        for hour in (6, 18):
            rows.append({
                "station_id": 80959,
                "datetime": pd.Timestamp(f"{date}T{hour:02d}:00:00Z"),
                "stage_m": stage,
                "WSE_baltic_m": ZERO + stage,
            })
    return pd.DataFrame(rows)[OBS_COLUMNS].drop_duplicates(
        subset=["station_id", "datetime"]
    )


SPECS = [
    ("2021-03-01", 205, "gt1l", 0.3, 3.90),
    ("2021-05-02", 205, "gt1r", 0.8, 4.05),
    ("2021-07-03", 989, "gt2l", 1.5, 3.70),
    ("2021-09-04", 989, "gt2r", 2.5, 3.85),   # outside the 2 km radius
    ("2021-11-05", 45, "gt3l", 4.0, 3.60),    # outside 2 km, inside 5 km
]


def test_distance_and_radius_filter():
    cfg = load_config()
    st = _station(cfg)
    seg = _segments(SPECS)
    d = distance_to_station(seg, st)
    assert d.min() == pytest.approx(0.3, abs=0.05)
    assert d.max() == pytest.approx(4.0, abs=0.05)

    lp2 = local_pass_levels(seg, st, 2.0, cfg)
    assert len(lp2) == 3                        # 0.3, 0.8, 1.5 km
    assert set(lp2["rgt"]) == {205, 989}
    lp5 = local_pass_levels(seg, st, 5.0, cfg)
    assert len(lp5) == 5
    assert set(lp5["rgt"]) == {45, 205, 989}
    assert (lp2["radius_km"] == 2.0).all()


def test_min_points_local_qc():
    cfg = load_config()
    st = _station(cfg)
    seg = _segments(SPECS[:1], n_per_pass=4)     # below min_points_per_local_pass
    lp = local_pass_levels(seg, st, 2.0, cfg)
    assert len(lp) == 1
    assert bool(lp.iloc[0]["local_qc_pass"]) is False
    assert match_local(lp, _obs(SPECS[:1]), st, cfg, qc_only=True).empty


def test_plausibility_gate_rejects_flat_land_return():
    """A bank/land return can be perfectly flat — only the level exposes it."""
    cfg = load_config()
    st = _station(cfg)
    spec_ok = ("2021-03-01", 205, "gt1l", 0.3, 3.90)
    seg = _segments([spec_ok])
    # same date/radius, internally flat (tiny NMAD), but 7 m above the water
    land = _segments([("2021-03-01", 989, "gt2r", 0.9, 3.90)], seed=3)
    land["H_evrs_egg2015_m"] += 7.0
    seg = pd.concat([seg, land], ignore_index=True)

    reservoir = pd.DataFrame({
        "date": [pd.Timestamp("2021-03-01").date()],
        "rgt": [205], "beam": ["gt1l"], "qc_pass": [True],
        "median_wse_evrs_m": [TRUE_C + 3.90],
    })
    level = reservoir_level_by_date(reservoir)

    lp = local_pass_levels(seg, st, 2.0, cfg, reservoir_level=level)
    assert len(lp) == 2
    by_beam = lp.set_index("beam")
    assert by_beam.loc["gt2r", "nmad_m"] < 0.05          # it IS flat
    assert bool(by_beam.loc["gt2r", "local_qc_pass"]) is False
    assert "implausible_level" in by_beam.loc["gt2r", "local_qc_flags"]
    assert bool(by_beam.loc["gt1l", "local_qc_pass"]) is True

    m = match_local(lp, _obs([spec_ok]), st, cfg)
    assert len(m) == 1
    assert m.iloc[0]["alignment_constant_m"] == pytest.approx(TRUE_C, abs=0.02)


def test_median_consistent_ci():
    """One gross outlier must not blow up the CI around the median estimate."""
    cfg = load_config()
    st = _station(cfg)
    seg, obs = _segments(SPECS), _obs(SPECS)
    ladder, _ = radius_ladder(seg, obs, st, cfg, radii=(5.0,))
    r = ladder.iloc[0]
    half = (r["ci95_high_m"] - r["ci95_low_m"]) / 2
    assert half == pytest.approx(1.96 * 1.2533 * r["nmad_m"] / np.sqrt(r["n_matchups"]),
                                 rel=1e-6)
    assert r["ci95_low_m"] < r["alignment_constant_m"] < r["ci95_high_m"]


def test_alignment_constant_recovered():
    cfg = load_config()
    st = _station(cfg)
    seg, obs = _segments(SPECS), _obs(SPECS)
    m = match_local(local_pass_levels(seg, st, 2.0, cfg), obs, st, cfg)
    assert len(m) == 3
    assert m["alignment_constant_m"].to_numpy() == pytest.approx(TRUE_C, abs=0.02)
    # evrs_minus_bs77 is exactly the constant shifted by the nominal zero
    assert (m["alignment_constant_m"] - m["evrs_minus_bs77_m"]).to_numpy() == pytest.approx(
        ZERO, abs=1e-9
    )
    assert m["H_bs77_m"].to_numpy() == pytest.approx(
        (ZERO + m["stage_m"]).to_numpy(), abs=1e-9
    )


def test_post_breach_never_reaches_output():
    cfg = load_config()
    st = _station(cfg)
    good = _segments(SPECS[:2])
    bad = _segments(
        [("2024-05-01", 205, "gt1l", 0.4, 1.0)], seed=7, period="POST_BREACH"
    )
    seg = pd.concat([good, bad], ignore_index=True)
    obs = _obs(SPECS[:2] + [("2024-05-01", 205, "gt1l", 0.4, 1.0)])

    lp = local_pass_levels(seg, st, 2.0, cfg)
    assert (lp["period"] == "PRE_BREACH").all()
    assert pd.Timestamp("2024-05-01").date() not in set(lp["date"])

    ladder, m = radius_ladder(seg, obs, st, cfg, radii=(1.0, 2.0))
    assert (m["period"] == "PRE_BREACH").all()


def test_radius_ladder_and_indicative_flag():
    cfg = load_config()
    st = _station(cfg)
    seg, obs = _segments(SPECS), _obs(SPECS)
    ladder, m = radius_ladder(seg, obs, st, cfg, radii=(0.5, 2.0, 5.0))

    assert list(ladder["radius_km"]) == [0.5, 2.0, 5.0]
    assert ladder.set_index("radius_km").loc[0.5, "n_matchups"] == 1
    assert ladder.set_index("radius_km").loc[2.0, "n_matchups"] == 3
    assert ladder.set_index("radius_km").loc[5.0, "n_matchups"] == 5
    # every radius recovers the same planted constant
    assert ladder["alignment_constant_m"].to_numpy() == pytest.approx(TRUE_C, abs=0.02)
    # thin radii are flagged, well-populated ones are not
    assert bool(ladder.set_index("radius_km").loc[0.5, "indicative"]) is True
    assert bool(ladder.set_index("radius_km").loc[5.0, "indicative"]) is False
    assert set(m["radius_km"]) == {0.5, 2.0, 5.0}


def test_per_rgt_bias_arithmetic():
    cfg = load_config()
    st = _station(cfg)
    seg, obs = _segments(SPECS), _obs(SPECS)
    _, m = radius_ladder(seg, obs, st, cfg, radii=(5.0,))
    t = per_rgt(m, 5.0)

    assert t.iloc[-1]["rgt"] == "ALL"
    pooled = t.iloc[-1]["alignment_constant_m"]
    for _, row in t[t["rgt"] != "ALL"].iterrows():
        assert row["bias_relative_to_pooled_m"] == pytest.approx(
            row["alignment_constant_m"] - pooled, abs=1e-9
        )
    assert t.iloc[-1]["bias_relative_to_pooled_m"] == 0.0
    assert t.loc[t["rgt"] != "ALL", "n_matchups"].sum() == t.iloc[-1]["n_matchups"]
