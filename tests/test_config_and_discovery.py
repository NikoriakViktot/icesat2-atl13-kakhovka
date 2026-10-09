import datetime as dt

from kakhovka_altimetry import REGIME_BREACH_DRAWDOWN, REGIME_POST_BREACH, REGIME_PRE_BREACH
from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.discovery import GranuleInfo, build_manifest, read_seed_granules


def test_config_loads():
    cfg = load_config()
    assert cfg.atl13x.refid == 2210000129
    assert cfg.product.version == "007"
    assert cfg.aoi_bbox[0] < cfg.aoi_bbox[2]


def test_regime_labelling():
    r = load_config().regimes
    assert r.label_for(dt.date(2022, 5, 1)) == REGIME_PRE_BREACH
    assert r.label_for(dt.date(2023, 6, 5)) == REGIME_PRE_BREACH
    assert r.label_for(dt.date(2023, 6, 6)) == REGIME_BREACH_DRAWDOWN
    assert r.label_for(dt.date(2023, 9, 1)) == REGIME_BREACH_DRAWDOWN
    assert r.label_for(dt.date(2024, 6, 1)) == REGIME_POST_BREACH


def test_granule_parse():
    info = GranuleInfo.parse("ATL13_20220427183114_05451501_007_01.h5")
    assert info.rgt == 545
    assert info.cycle == 15
    assert info.region == 1
    assert info.release == "007"
    assert info.acquisition_time.year == 2022
    assert info.acquisition_time.tzinfo is not None


def test_seed_list_and_manifest_build():
    cfg = load_config()
    seed = read_seed_granules(cfg)
    assert len(seed) > 200
    assert all(s.startswith("ATL13_") for s in seed)

    df = build_manifest(cfg, include_cmr=False, write=False)
    assert len(df) == len(set(seed))
    assert (df["refid"] == cfg.atl13x.refid).all()
    assert df["acquisition_time"].is_monotonic_increasing
