"""Downstream ATL13 water bodies + the estuary clip polygon."""

import numpy as np
import pytest

from kakhovka_altimetry.config import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_two_bodies_configured(cfg):
    slugs = [b.slug for b in cfg.downstream_bodies]
    assert slugs == ["kherson", "dnipro_estuary"]


def test_downstream_body_lookup_and_paths(cfg):
    kh = cfg.downstream_body("kherson")
    es = cfg.downstream_body("dnipro_estuary")
    assert kh.clip_bbox is not None and kh.clip_polygon is None
    assert es.clip_polygon is not None and es.clip_bbox is None
    assert es.refid == 6033000138
    assert kh.pass_levels_parquet.name == "kherson_atl13_pass_levels.parquet"
    assert es.pass_levels_parquet.name == "dnipro_estuary_atl13_pass_levels.parquet"
    assert es.manifest.name == "resources_manifest_downstream_dnipro_estuary.csv"
    with pytest.raises(KeyError):
        cfg.downstream_body("nope")


def test_estuary_polygon_covers_liman_not_open_sea(cfg):
    import geopandas as gpd

    poly = cfg.downstream_body("dnipro_estuary").clip_polygon
    assert poly.exists(), "run scripts/build_estuary_aoi.py"
    geom = gpd.read_file(poly).to_crs("EPSG:4326").union_all()

    inside = gpd.points_from_xy(
        [31.970917, 31.85, 32.10],   # Mykolaiv, mid-liman, Dnipro mouth
        [46.984306, 46.62, 46.55])
    outside = gpd.points_from_xy(
        [31.0, 33.4, 31.99, 32.61],  # open Black Sea W, reservoir E, far south, Kherson (own body)
        [46.2, 47.5, 46.1, 46.6237])
    assert gpd.GeoSeries(inside, crs="EPSG:4326").within(geom).all()
    assert not gpd.GeoSeries(outside, crs="EPSG:4326").within(geom).any()


def test_estuary_pass_levels_and_wse_summary(cfg):
    from kakhovka_altimetry.downstream import estuary_wse_summary, load_body_pass_levels

    path = cfg.downstream_body("dnipro_estuary").pass_levels_parquet
    if not path.exists():
        pytest.skip("run scripts/download_atl13_downstream.py --body dnipro_estuary")

    passes = load_body_pass_levels(cfg, "dnipro_estuary")
    assert len(passes) > 0
    assert passes["rgt"].nunique() > 0

    summary = estuary_wse_summary(passes)
    assert (summary["year"] == "ALL").any()
    all_row = summary[summary["year"] == "ALL"].iloc[0]
    assert np.isfinite(all_row["median_wse_evrs_m"])


def test_mykolaiv_is_a_coastal_gauge_with_bs77_zero(cfg):
    m = cfg.gauges.downstream_station(98027)
    assert m.slug == "mykolaiv"
    assert m.coords_approx is False   # surveyed position, operator-supplied 2026-09-04
    assert m.lat == pytest.approx(46.984306) and m.lon == pytest.approx(31.970917)
    assert m.gauge_zero_baltic_m == pytest.approx(-5.00)   # same graph zero as Kherson
    assert m.yearbook_grid_csv is not None and m.yearbook_grid_csv.exists()
