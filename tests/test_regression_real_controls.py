"""Real-data regression control: the frozen six-station Phase 2c result.

Skips cleanly when the pipeline output is absent (fresh checkout / CI without
data). When it *is* present, a refactor that moves any station corrector by more
than a few mm for unchanged inputs fails here — catching an accidental sign flip,
radius-selection change, timezone bug, bootstrap-unit change, or a leaked
post-breach row.
"""

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.config import load_config

# Frozen 2026-09-03 baseline (outputs/reports/egg2015_to_evrf2019_gauge_experiment.md).
FROZEN_C_STATION_M = {
    "nova_kakhovka": -0.128,
    "velyka_lepetykha": -0.189,
    "nikopol": -0.208,
    "blahovishchenka": -0.150,
    "rozumivka": -0.146,
    "plavni": -0.217,
}
TOL_M = 0.005


@pytest.fixture(scope="module")
def by_station() -> pd.DataFrame:
    path = load_config().tables_dir / "egg2015_to_evrf2019_by_station.csv"
    if not path.exists():
        pytest.skip(f"{path} absent — run scripts/egg2015_to_evrf2019.py first")
    return pd.read_csv(path)


@pytest.mark.parametrize("slug,expected", FROZEN_C_STATION_M.items())
def test_station_corrector_matches_frozen_baseline(by_station, slug, expected):
    row = by_station.loc[by_station["slug"] == slug]
    assert not row.empty, f"{slug} missing from by_station.csv"
    assert row["c_station_m"].iloc[0] == pytest.approx(expected, abs=TOL_M)


def test_regional_median_and_sign(by_station):
    c = by_station["c_station_m"].to_numpy(float)
    c = c[np.isfinite(c)]
    assert (c < 0).all(), "every station corrector must stay negative"
    assert np.median(c) == pytest.approx(-0.170, abs=TOL_M)
