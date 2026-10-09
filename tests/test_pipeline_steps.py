"""Unit tests for the pure pipeline steps, products, heights, DEMs and regions
(no network, no docker)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry import atl13, dem, heights, pipeline, products
from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.regions import (
    EGG2015,
    EGM2008,
    LAKE,
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
G08 = "ATL08_20210507162458_06701102_007_01.h5"  # rgt 670, cycle 11


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture
def flat_egm2008(monkeypatch):
    """EGM2008 N = 22 m everywhere (no PROJ network in unit tests)."""
    monkeypatch.setattr(heights, "egm2008_undulation",
                        lambda lat, lon: np.full(np.asarray(lat).size, 22.0))


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


def fake_atl08(granules, *, lon0=33.35, lat0=46.70, n=40, terrain=40.0):
    """A GeoDataFrame shaped like SlideRule's atl08x return."""
    import geopandas as gpd

    from kakhovka_altimetry.discovery import GranuleInfo

    frames = []
    for k, g in enumerate(granules):
        info = GranuleInfo.parse(g)
        for gt in (10, 30, 50):
            t0 = pd.Timestamp(info.acquisition_time) + pd.Timedelta(seconds=gt)
            lat = lat0 + np.arange(n) * 0.0009      # ~100 m segments
            lon = np.full(n, lon0 + 0.01 * k + gt / 2000)
            canopy = np.where(np.arange(n) % 4 == 0, 3.4e38, 8.0).astype("float32")
            d = {
                "time": t0 + pd.to_timedelta(np.arange(n) * 0.014, unit="s"),
                "h_te_median": np.full(n, terrain + 22.0, dtype="float32"),
                "h_te_uncertainty": np.full(n, 0.3, dtype="float32"),
                "terrain_slope": np.zeros(n, dtype="float32"),
                "h_canopy": canopy, "h_mean_canopy": canopy,
                "canopy_openness": np.ones(n, dtype="float32"),
                "n_te_photons": np.full(n, 50, dtype="int32"),
                "n_ca_photons": np.full(n, 10, dtype="int32"),
                "segment_landcover": np.full(n, 40, dtype="uint8"),
                "segment_snowcover": np.ones(n, dtype="uint8"),
                "solar_elevation": np.full(n, 30.0, dtype="float32"),
                "segment_id_beg": np.arange(n) * 5,
                "rgt": info.rgt, "cycle": info.cycle, "gt": gt, "spot": 1, "srcid": 0,
            }
            frames.append(gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(lon, lat),
                                           crs="EPSG:4326"))
    out = pd.concat(frames, ignore_index=True).set_index("time")
    return gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4326")


def flat_geoid(value=20.0):
    return GeoidGrid(lats=np.array([40.0, 55.0]), lons=np.array([25.0, 45.0]),
                     values=np.full((2, 2), value), crs="EPSG:4258")


def box_region(**kw):
    base = dict(slug="t", name="t", coord_lon=34, coord_lat=47, refid=1,
                bbox=(33.0, 46.0, 35.0, 48.0))
    base.update(kw)
    return Region(**base)


# ---------------------------------------------------------------- discovery
def test_select_granules_filters_and_sorts():
    assert pipeline.select_granules([G2, G1, G1]) == [G1, G2]
    assert pipeline.select_granules([G1, G2], start=dt.date(2019, 5, 1)) == [G2]
    assert pipeline.select_granules([G1, G2], end=dt.date(2019, 12, 31)) == [G1]
    assert pipeline.select_granules([G1, G08], product="ATL08") == [G08]


def test_granule_lookup_keys_on_rgt_cycle():
    assert pipeline.granule_lookup([G1, G2]) == {(45, 3): G1, (105, 6): G2}
    assert pipeline.granule_lookup([G08]) == {(670, 11): G08}


# ---------------------------------------------------------------- ATL13
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


def test_atl13_egg2015_reservoir_matches_the_evrs_chain(cfg):
    region = box_region(kind=RESERVOIR, vertical=EGG2015, regimes=True,
                        bbox=(33.0, 46.0, 35.0, 47.255))
    seg = pipeline.segments_from_raw(fake_sliderule([G1]), [G1])
    evrs = pipeline.to_evrs(seg, cfg, region, geoid=flat_geoid())
    np.testing.assert_allclose(evrs["H_evrs_egg2015_m"], 16.0, atol=1e-4)
    np.testing.assert_allclose(evrs["H_m"], evrs["H_evrs_egg2015_m"])
    assert set(evrs["vertical_datum"]) == {"EVRS_EGG2015"}
    # lat 47.00..47.29 in 0.01 steps -> 47.00..47.25 (26 per beam) inside the clip
    assert evrs["water_mask_pass"].sum() == 2 * 26
    passes = pipeline.pass_levels(evrs, cfg, region)
    assert len(passes) == 2 and passes["qc_pass"].all()
    assert set(passes["period"]) == {"PRE_BREACH"}
    assert {"median_wse_m", "mean_wse_m", "vertical_datum"} <= set(passes.columns)
    assert "median_wse_evrs_m" not in passes


def test_atl13_egm2008_lake_uses_ht_ortho_and_no_regimes(cfg):
    region = box_region(kind=LAKE)                      # defaults: egm2008, no regimes
    seg = pipeline.segments_from_raw(fake_sliderule([G1]), [G1])
    pts = pipeline.to_heights(seg, cfg, region)        # no geoid, no network needed
    np.testing.assert_allclose(pts["H_m"], 16.15, atol=1e-4)
    assert "H_evrs_egg2015_m" not in pts
    assert set(pts["period"]) == {"ALL"}
    passes = pipeline.pass_levels(pts, cfg, region)
    assert set(passes["vertical_datum"]) == {"EGM2008"}
    np.testing.assert_allclose(passes["median_wse_m"], 16.15, atol=1e-4)


def test_river_pass_levels_have_no_qc(cfg):
    region = box_region(kind=RIVER, vertical=EGG2015, regimes=True)
    seg = pipeline.segments_from_raw(fake_sliderule([G1, G2]), [G1, G2])
    passes = pipeline.pass_levels(pipeline.to_evrs(seg, cfg, region, geoid=flat_geoid()),
                                  cfg, region)
    assert len(passes) == 4
    assert "qc_pass" not in passes
    assert passes["vertical_datum"].eq("EVRS_EGG2015").all()


def test_egg2015_outside_grid_is_an_error(cfg):
    region = box_region(vertical=EGG2015, bbox=(32.0, -2.0, 34.0, 0.0))
    seg = pipeline.segments_from_raw(fake_sliderule([G1], lon0=33.0, lat0=-1.0), [G1])
    with pytest.raises(ValueError, match="EGG2015"):
        pipeline.to_heights(seg, cfg, region, geoid=flat_geoid())


# ---------------------------------------------------------------- ATL08 / ATL03
class ConstSource:
    def __init__(self, value):
        self.value = value

    def sample(self, lat, lon):
        return np.full(np.asarray(lat).size, self.value)


def test_atl08_normalise_clip_heights_and_dem_compare(cfg, flat_egm2008):
    p = products.get("ATL08")
    region = box_region(coord_lon=None, coord_lat=None, refid=None,
                        bbox=(33.0, 46.0, 34.0, 46.72))
    seg = pipeline.segments_from_raw(fake_atl08([G08]), [G08], product=p)
    assert seg["h_canopy_m"].isna().sum() == 3 * 10        # FLT_MAX masked
    assert set(seg["beam"]) == {"gt1l", "gt2l", "gt3l"}
    pts = pipeline.to_heights(seg, cfg, region, product=p)
    assert 0 < len(pts) < len(seg)                          # clipped at lat 46.72
    np.testing.assert_allclose(pts["H_m"], 40.0)            # 62 - N(22)
    np.testing.assert_allclose(pts["H_egm2008_m"], 40.0)
    out = dem.add_reference_dems(pts, ["cop30", "fabdem"],
                                 sources={"cop30": ConstSource(40.5),
                                          "fabdem": ConstSource(39.0)})
    np.testing.assert_allclose(out["dh_cop30_m"], -0.5)
    np.testing.assert_allclose(out["dh_fabdem_m"], 1.0)
    with pytest.raises(ValueError):
        dem.add_reference_dems(pts, ["srtm"])
    st = dem.compare(out, "cop30_m")
    assert st["n"] == len(pts) and st["median_m"] == pytest.approx(-0.5)


def test_request_parms_per_product():
    lake = box_region()
    p13 = products.request_parms(products.get("ATL13"), lake, [G1])
    assert p13["atl13"] == {"coord": {"lon": 34.0, "lat": 47.0}, "refid": 1}
    land = box_region(coord_lon=None, coord_lat=None, refid=None)
    p08 = products.request_parms(products.get("ATL08"), land, [G08],
                                 {"compare": ["cop30", "fabdem"]})
    assert p08["poly"][0] == p08["poly"][-1] and len(p08["poly"]) == 5
    assert "samples" not in p08          # reference DEMs are sampled locally
    p03 = products.request_parms(products.get("ATL03"), land, [G08],
                                 {"atl03": {"cnf": 3, "atl08_class": ["atl08_ground"]}})
    assert p03["cnf"] == 3 and p03["atl08_class"] == ["atl08_ground"]
    with pytest.raises(ValueError):
        products.request_parms(products.get("ATL13"), land, [G1])
    with pytest.raises(ValueError):
        products.request_parms(products.get("ATL03"), land, [G08],
                               {"atl03": {"atl08_class": ["trees"]}})


# ---------------------------------------------------------------- DEMs
def test_cop30_tile_names():
    assert dem.cop30_tile(46.75, 33.35) == "Copernicus_DSM_COG_10_N46_00_E033_00_DEM"
    assert dem.cop30_tile(-0.9, 32.99) == "Copernicus_DSM_COG_10_S01_00_E032_00_DEM"


def test_fabdem_tile_and_zip_names():
    assert dem.fabdem_tile(46.75, 33.35) == "N46E033_FABDEM_V1-2.tif"
    assert dem.fabdem_zip(46.75, 33.35) == "N40E030-N50E040_FABDEM_V1-2.zip"
    assert dem.fabdem_tile(-0.5, -71.2) == "S01W072_FABDEM_V1-2.tif"
    assert dem.fabdem_zip(-0.5, -71.2) == "S10W080-N00W070_FABDEM_V1-2.zip"


def test_fabdem_source_reads_cached_tile(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    tile = tmp_path / "fabdem" / "N46E033_FABDEM_V1-2.tif"
    tile.parent.mkdir()
    data = np.full((10, 10), 17.0, dtype="float32")
    data[0, 0] = -9999.0
    with rasterio.open(tile, "w", driver="GTiff", height=10, width=10, count=1,
                       dtype="float32", crs="EPSG:4326", nodata=-9999.0,
                       transform=from_origin(33.0, 47.0, 0.1, 0.1)) as ds:
        ds.write(data, 1)
    src = dem.FabdemSource(tmp_path, base_url="http://invalid.example")
    assert src.tile_path(46.5, 33.5) == tile         # served from the local cache
    vals = src.sample(np.array([46.5, 46.99]), np.array([33.5, 33.01]))
    assert vals[0] == 17.0 and np.isnan(vals[1])


def test_grid_points_and_cog(tmp_path):
    import rasterio

    df = pd.DataFrame({"lon": [33.300, 33.3001, 33.31, 33.32],
                       "lat": [46.700, 46.7001, 46.71, 46.72],
                       "H_m": [10.0, 12.0, 20.0, np.nan]})
    grid = dem.grid_points(df, "H_m", 100)
    assert grid["crs"] == "EPSG:32636"
    assert np.nansum(grid["count"]) == 3
    assert sorted(v for v in grid["value"].ravel() if np.isfinite(v)) == [11.0, 20.0]
    path = dem.write_cog(grid, tmp_path / "dtm.tif", description="terrain")
    with rasterio.open(path) as ds:
        assert ds.count == 2 and ds.crs.to_epsg() == 32636 and ds.res == (100.0, 100.0)
        assert ds.descriptions[0] == "terrain"
    st = dem.raster_stats(grid)
    assert st["valid_cells"] == 2 and st["points"] == 3


# ---------------------------------------------------------------- regions
def test_configured_regions_match_the_batch_config(cfg):
    regions = configured_regions(cfg)
    assert {"kakhovka", "kherson", "dnipro_estuary"} <= set(regions)
    k = reservoir_region(cfg)
    assert k.kind == RESERVOIR and k.refid == cfg.atl13x.refid
    assert k.vertical == EGG2015 and k.regimes
    assert k.search_bbox == tuple(cfg.aoi_bbox)
    assert len(k.seed_granules()) > 300


def test_region_from_request_polygon_and_roundtrip():
    poly = {"type": "Polygon", "coordinates": [[[33, 46], [34, 46], [34, 47], [33, 47], [33, 46]]]}
    r = region_from_dict({"slug": "x", "coord": {"lon": 33.5, "lat": 46.5}, "polygon": poly})
    assert r.kind == LAKE and r.vertical == EGM2008 and not r.regimes and r.refid is None
    assert r.search_bbox == (33.0, 46.0, 34.0, 47.0)
    assert region_from_dict(r.to_dict()) == r
    land = region_from_dict({"slug": "y", "bbox": [1, 2, 3, 4]})
    assert land.coord_lon is None
    with pytest.raises(ValueError):
        Region(slug="z", name="z", coord_lon=0, coord_lat=0)
