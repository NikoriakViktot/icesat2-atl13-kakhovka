"""Unit tests for the pure pipeline steps and regions (no network, no docker)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry import atl13, pipeline
from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.regions import (
    RESERVOIR,
    RIVER,
    Region,
    configured_regions,
    region_from_dict,
    reservoir_region,
)
from kakhovka_altimetry.vertical import GeoidGrid

G1 = "ATL13_20190401044830_00450301_007_01.h5"   # rgt 45, cycle 3
G2 = "ATL13_20200102140508_01050601_007_01.h5"   # rgt 105, cycle 6


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def fake_sliderule(granules, *, lon0=34.0, lat0=47.0, n=30, wse=16.0, zeta=20.0):
    """A GeoDataFrame shaped like SlideRule's atl13x return: 2 beams per granule."""
    import geopandas as gpd

    from kakhovka_altimetry.discovery import GranuleInfo

    frames = []
    for k, g in enumerate(granules):
        info = GranuleInfo.parse(g)
        for gt in (10, 50):
            t0 = pd.Timestamp(info.acquisition_time) + pd.Timedelta(seconds=gt)
            lat = lat0 + np.arange(n) * 0.01
            lon = np.full(n, lon0 + 0.05 * k + gt / 1000)
            frames.append(gpd.GeoDataFrame({
                "time": t0 + pd.to_timedelta(np.arange(n) * 0.1, unit="s"),
                "ht_water_surf": np.full(n, wse + zeta, dtype="float32"),
                "ht_ortho": np.full(n, wse + 0.15, dtype="float32"),
                "stdev_water_surf": np.full(n, 0.05, dtype="float32"),
                "water_depth": np.full(n, 3.4e38, dtype="float32"),
                "rgt": info.rgt, "cycle": info.cycle, "gt": gt, "spot": 1,
                "segment_id_beg": np.arange(n), "srcid": 0,
            }, geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326"))
    out = pd.concat(frames, ignore_index=True).set_index("time")
    return gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4326")


def flat_geoid(value=20.0):
    return GeoidGrid(lats=np.array([40.0, 55.0]), lons=np.array([25.0, 45.0]),
                     values=np.full((2, 2), value), crs="EPSG:4258")


def test_select_granules_filters_and_sorts():
    assert pipeline.select_granules([G2, G1, G1]) == [G1, G2]
    assert pipeline.select_granules([G1, G2], start=dt.date(2019, 5, 1)) == [G2]
    assert pipeline.select_granules([G1, G2], end=dt.date(2019, 12, 31)) == [G1]


def test_granule_lookup_keys_on_rgt_cycle():
    assert pipeline.granule_lookup([G1, G2]) == {(45, 3): G1, (105, 6): G2}


def test_raw_frame_roundtrip_normalises_like_the_live_return(tmp_path):
    gdf = fake_sliderule([G1, G2])
    live = atl13.normalise(gdf)
    path = tmp_path / "raw.parquet"
    atl13.raw_frame(gdf).to_parquet(path, index=False)
    back = pipeline.segments_from_raw(pd.read_parquet(path), [G1, G2])
    assert len(back) == len(live) == 120
    np.testing.assert_allclose(back.sort_values(["beam", "time"])["lat"],
                               live.sort_values(["beam", "time"])["lat"])
    assert set(back["granule"]) == {G1, G2}
    assert back["water_depth_m"].isna().all()           # FLT_MAX masked


def test_to_evrs_and_reservoir_pass_levels(cfg):
    region = Region(slug="t", name="t", refid=1, coord_lon=34, coord_lat=47,
                    kind=RESERVOIR, bbox=(33.0, 46.0, 35.0, 47.255))
    seg = pipeline.segments_from_raw(fake_sliderule([G1]), [G1])
    evrs = pipeline.to_evrs(seg, cfg, region, geoid=flat_geoid())
    np.testing.assert_allclose(evrs["H_evrs_egg2015_m"], 16.0, atol=1e-4)
    # lat 47.00..47.29 in 0.01 steps -> 47.00..47.25 (26 per beam) inside the clip
    assert evrs["water_mask_pass"].sum() == 2 * 26
    passes = pipeline.pass_levels(evrs, cfg, region)
    assert len(passes) == 2
    assert passes["qc_pass"].all()
    assert set(passes["period"]) == {"PRE_BREACH"}


def test_river_pass_levels_have_no_qc(cfg):
    region = Region(slug="r", name="r", refid=1, coord_lon=34, coord_lat=47,
                    kind=RIVER, bbox=(33.0, 46.0, 35.0, 48.0))
    seg = pipeline.segments_from_raw(fake_sliderule([G1, G2]), [G1, G2])
    passes = pipeline.pass_levels(pipeline.to_evrs(seg, cfg, region, geoid=flat_geoid()),
                                  cfg, region)
    assert len(passes) == 4
    assert "qc_pass" not in passes
    assert list(passes.columns) == pipeline.BASIC_PASS_LEVEL_COLUMNS


def test_configured_regions_match_the_batch_config(cfg):
    regions = configured_regions(cfg)
    assert {"kakhovka", "kherson", "dnipro_estuary"} <= set(regions)
    k = reservoir_region(cfg)
    assert k.kind == RESERVOIR and k.refid == cfg.atl13x.refid
    assert k.search_bbox == tuple(cfg.aoi_bbox)
    assert len(k.seed_granules()) > 300


def test_region_from_request_polygon():
    poly = {"type": "Polygon", "coordinates": [[[33, 46], [34, 46], [34, 47], [33, 47], [33, 46]]]}
    r = region_from_dict({"slug": "x", "refid": 5, "coord": {"lon": 33.5, "lat": 46.5},
                          "polygon": poly})
    assert r.kind == RIVER
    assert r.search_bbox == (33.0, 46.0, 34.0, 47.0)
    with pytest.raises(ValueError):
        Region(slug="y", name="y", refid=1, coord_lon=0, coord_lat=0)
