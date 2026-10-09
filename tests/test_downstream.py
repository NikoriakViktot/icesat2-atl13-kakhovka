"""Downstream (Kherson) series loader — uses a tiny synthetic donor tree."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.downstream import (
    bs77_daily,
    coverage_summary,
    load_downstream_series,
)


@pytest.fixture
def cfg_with_fake_kherson(tmp_path, monkeypatch):
    cfg = load_config()
    kh = cfg.gauges.downstream_station(80805)

    ycsv = tmp_path / "80805_yearbook.csv"
    pd.DataFrame({
        "date": ["2022-12-31", "2023-06-08", "2023-06-09"],
        "water_level_cm": [497.0, 1056.0, 1015.0],
        "water_level_m_abs": [-0.03, 5.56, 5.15],
        "stat_type": ["daily", "daily", "daily"],
    }).to_csv(ycsv, index=False)

    pdir = tmp_path / "post_id=80805"
    pdir.mkdir()
    pd.DataFrame({
        "date": pd.to_datetime(["2023-06-08", "2025-01-01"]),  # overlaps one yearbook day
        "h_mean": [999.0, 495.0],
    }).to_parquet(pdir / "year=all.parquet")

    new_kh = dataclasses.replace(kh, yearbook_csv=ycsv, parquet_dir=pdir)
    new_gauges = dataclasses.replace(cfg.gauges, downstream=(new_kh,))
    return dataclasses.replace(cfg, gauges=new_gauges)


@pytest.fixture
def cfg_with_fake_mykolaiv(tmp_path):
    cfg = load_config()
    mk = cfg.gauges.downstream_station(98027)

    root = tmp_path / "parquet"
    for snap, year, val in [("version=20260101_0000", 2019, 490.0),
                            ("tmp_deadbeef", 2019, 999.0),   # tmp snapshot loses the tie
                            ("version=20260101_0000", 2020, 485.0)]:
        d = root / snap / "daily" / "post_id=98027" / f"year={year}"
        d.mkdir(parents=True)
        pd.DataFrame({
            "post_id": 98027, "date": pd.to_datetime([f"{year}-06-01"]),
            "variable": "level", "value": [val],
        }).to_parquet(d / "data.parquet")

    grid = tmp_path / "mykolaiv_98027_2021_yearbook_grid.csv"
    grid.write_text("day,m01\n1,492\n2,479\n", encoding="utf-8")   # 2 days in Jan 2021

    new_mk = dataclasses.replace(mk, parquet_versions_root=root, yearbook_grid_csv=grid,
                                 parquet_dir=None, yearbook_csv=None)
    new_gauges = dataclasses.replace(cfg.gauges, downstream=(new_mk,))
    return dataclasses.replace(cfg, gauges=new_gauges)


def test_stitches_sources_and_prefers_yearbook_on_overlap(cfg_with_fake_kherson):
    s = load_downstream_series(cfg_with_fake_kherson)
    assert len(s) == 4  # 3 yearbook + 1 parquet-only (2025)
    overlap = s[s["date"] == pd.Timestamp("2023-06-08")].iloc[0]
    assert overlap["h_cm"] == 1056.0                # yearbook wins, not 999
    assert overlap["source"] == "yearbook_csv"


def test_no_absolute_zero_is_invented(cfg_with_fake_kherson):
    s = load_downstream_series(cfg_with_fake_kherson)
    assert "WSE" not in " ".join(s.columns)
    # 2025 parquet row has no local anomaly
    assert pd.isna(s.loc[s["date"] == pd.Timestamp("2025-01-01"), "h_m_local"].iloc[0])


def test_breach_and_period_flags(cfg_with_fake_kherson):
    s = load_downstream_series(cfg_with_fake_kherson)
    assert not s.loc[s["date"] == pd.Timestamp("2022-12-31"), "post_breach"].iloc[0]
    assert s.loc[s["date"] == pd.Timestamp("2023-06-08"), "post_breach"].iloc[0]
    assert s.loc[s["date"] == pd.Timestamp("2022-12-31"), "period"].iloc[0] == "PRE_BREACH"


def test_coverage_summary_reports_breach_peak(cfg_with_fake_kherson):
    s = load_downstream_series(cfg_with_fake_kherson)
    cov = coverage_summary(s).iloc[0]
    assert cov["postbreach_h_cm_max"] == 1056.0
    assert cov["n_days"] == 4


def test_mykolaiv_version_parquets_and_grid(cfg_with_fake_mykolaiv):
    s = load_downstream_series(cfg_with_fake_mykolaiv)
    # 2 version-parquet days + 2 grid days (2021)
    assert sorted(s["date"].dt.year.unique().tolist()) == [2019, 2020, 2021]
    row2019 = s.loc[s["date"] == pd.Timestamp("2019-06-01")].iloc[0]
    assert row2019["h_cm"] == 490.0                 # real version snapshot beats tmp_ (999)
    assert row2019["source"] == "donor_parquet_versioned"
    assert np.isnan(row2019["h_m_local"])
    # h0 = -5.00 -> absolute BS-77
    assert row2019["h_bs77_m"] == pytest.approx(-5.00 + 4.90)


def test_bs77_daily_for_mykolaiv(cfg_with_fake_mykolaiv):
    b = bs77_daily(cfg_with_fake_mykolaiv, "mykolaiv")
    assert set(b.columns) == {"date", "h_bs77_m", "h0_bs77_m", "period"}
    assert (b["h0_bs77_m"] == -5.00).all()
    assert len(b) == 4
