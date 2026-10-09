"""Official BS-77 -> EVRF2019 grid reading, validation and decomposition."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from kakhovka_altimetry.config import load_config
from kakhovka_altimetry.datum import (
    decompose_alignment,
    decompose_by,
    solve_geodetic_datum_offset,
)
from kakhovka_altimetry.official_datum import (
    correction_at,
    grid_statistics,
    load_esri_ascii,
    validate_against_published,
)


def _write_asc(tmp_path, *, center=False, nodata=-9999.0, name="g.asc"):
    """3x4 grid, value = 0.10 + 0.01*row + 0.02*col, one NODATA cell.

    ESRI rows run north -> south, so the FIRST written row is the northernmost.
    """
    nrows, ncols, cs = 3, 4, 0.5
    rows_n_to_s = []
    for r in range(nrows):                       # r=0 is north
        lat_idx = nrows - 1 - r                  # ascending-lat index
        rows_n_to_s.append([0.10 + 0.01 * lat_idx + 0.02 * c for c in range(ncols)])
    rows_n_to_s[0][0] = nodata                   # NW corner missing

    origin = "xllcenter     20.0\nyllcenter     40.0" if center else \
             "xllcorner     19.75\nyllcorner     39.75"
    body = "\n".join(" ".join(f"{v:.4f}" for v in row) for row in rows_n_to_s)
    p = tmp_path / name
    p.write_text(
        f"ncols         {ncols}\nnrows         {nrows}\n{origin}\n"
        f"cellsize      {cs}\nNODATA_value  {nodata}\n{body}\n"
    )
    return p


def test_esri_ascii_orientation_and_origin(tmp_path):
    g = load_esri_ascii(_write_asc(tmp_path))
    assert g.values.shape == (3, 4)
    # cell centres, latitude ascending
    np.testing.assert_allclose(g.lats, [40.0, 40.5, 41.0])
    np.testing.assert_allclose(g.lons, [20.0, 20.5, 21.0, 21.5])
    # row 0 is the SOUTHERNMOST after the flip -> lat_idx 0 -> 0.10 + 0.02*c
    np.testing.assert_allclose(g.values[0], [0.10, 0.12, 0.14, 0.16])
    # the NODATA cell was the NW corner -> now top-left
    assert np.isnan(g.values[2, 0])
    np.testing.assert_allclose(g.values[2, 1:], [0.14, 0.16, 0.18])


def test_xllcenter_equals_xllcorner_form(tmp_path):
    a = load_esri_ascii(_write_asc(tmp_path, center=False, name="corner.asc"))
    b = load_esri_ascii(_write_asc(tmp_path, center=True, name="center.asc"))
    np.testing.assert_allclose(a.lats, b.lats)
    np.testing.assert_allclose(a.lons, b.lons)


def test_bilinear_sampling_on_linear_field(tmp_path):
    g = load_esri_ascii(_write_asc(tmp_path))
    # value = 0.10 + 0.01*(lat-40)/0.5 + 0.02*(lon-20)/0.5, exact under bilinear
    got = correction_at(g, 40.25, 20.25)
    assert got[0] == pytest.approx(0.10 + 0.01 * 0.5 + 0.02 * 0.5, abs=1e-9)


def test_grid_statistics_ignores_nodata(tmp_path):
    s = grid_statistics(load_esri_ascii(_write_asc(tmp_path)))
    assert s["n_nodes"] == 11                     # 12 cells minus one NODATA
    assert s["min_m"] == pytest.approx(0.10)
    assert s["max_m"] == pytest.approx(0.18)


def _cfg_with_published(mean, mn, mx, sd, tol=0.02, nodes=None):
    cfg = load_config()
    return dataclasses.replace(
        cfg,
        official_transform=dataclasses.replace(
            cfg.official_transform,
            published_stats={"mean_m": mean, "min_m": mn, "max_m": mx, "sd_m": sd},
            validation_tolerance_m=tol,
            expected_nodes=nodes,
        ),
    )


def test_validation_passes_and_ignores_max(tmp_path):
    g = load_esri_ascii(_write_asc(tmp_path))
    s = grid_statistics(g)
    # max deliberately off by 0.10 -> must still pass, max is not decisive
    cfg = _cfg_with_published(s["mean_m"], s["min_m"], s["max_m"] + 0.10, s["sd_m"],
                              nodes=11)
    r = validate_against_published(g, cfg)
    assert r["passed"] is True
    assert r["node_count_matches_paper"] is True
    assert abs(r["deltas"]["max_m"]) == pytest.approx(0.10)
    assert "max_m" not in r["decisive"]


def test_validation_fails_on_decisive_statistic(tmp_path):
    g = load_esri_ascii(_write_asc(tmp_path))
    s = grid_statistics(g)
    cfg = _cfg_with_published(s["mean_m"] + 0.10, s["min_m"], s["max_m"], s["sd_m"])
    assert validate_against_published(g, cfg)["passed"] is False


def _summary():
    return pd.DataFrame({
        "station_id": [80959, 80977],
        "slug": ["a", "b"],
        "name": ["A", "B"],
        "name_en": ["A", "B"],
        "lat": [40.25, 40.75],
        "lon": [20.25, 20.75],
        "gauge_zero_baltic_m": [12.0, 12.0],
        "alignment_constant_m": [12.350, 12.343],
        "reported_radius_km": [2.0, 2.0],
        "n_reported": [9, 12],
        "note": ["", ""],
    })


def test_decomposition_identity(tmp_path):
    cfg = load_config()
    g = load_esri_ascii(_write_asc(tmp_path))
    d = decompose_alignment(_summary(), g, cfg)

    assert len(d) == 2
    # the defining identity
    np.testing.assert_allclose(
        d["implied_gauge_zero_baltic_m"],
        d["nominal_zero_m"] + d["delta_unexplained_m"], atol=1e-12,
    )
    np.testing.assert_allclose(
        d["delta_empirical_m"],
        d["alignment_constant_m"] - d["nominal_zero_m"], atol=1e-12,
    )
    np.testing.assert_allclose(
        d["delta_unexplained_m"],
        d["delta_empirical_m"] - d["delta_official_m"], atol=1e-12,
    )


def test_frame_terms_are_subtracted_not_ignored(tmp_path):
    base = load_config()
    g = load_esri_ascii(_write_asc(tmp_path))
    d0 = decompose_alignment(_summary(), g, base)

    cfg = dataclasses.replace(
        base,
        official_transform=dataclasses.replace(
            base.official_transform,
            evrf2019_minus_evrf2007_m=0.02, tide_system_correction_m=0.01,
        ),
    )
    d1 = decompose_alignment(_summary(), g, cfg)
    np.testing.assert_allclose(
        d1["delta_unexplained_m"], d0["delta_unexplained_m"] - 0.03, atol=1e-12
    )
    np.testing.assert_allclose(
        d1["implied_gauge_zero_baltic_m"],
        d0["implied_gauge_zero_baltic_m"] - 0.03, atol=1e-12,
    )


def test_decompose_by_groups(tmp_path):
    cfg = load_config()
    g = load_esri_ascii(_write_asc(tmp_path))
    m = pd.DataFrame({
        "radius_km": [1.0, 1.0, 2.0, 2.0, 2.0],
        "alignment_constant_m": [12.34, 12.36, 12.35, 12.35, 12.37],
    })
    out = decompose_by(m, g, cfg, ["radius_km"],
                       station_lat=40.25, station_lon=20.25, nominal_zero_m=12.0)
    assert list(out["radius_km"]) == [1.0, 2.0]
    assert list(out["n_matchups"]) == [2, 3]
    # official correction is the same at both radii — it is evaluated at the post
    assert out["delta_official_m"].nunique() == 1
    np.testing.assert_allclose(
        out["delta_unexplained_m"],
        out["alignment_constant_m"] - 12.0 - out["delta_official_m"], atol=1e-12,
    )


def test_solver_wrapper_reports_grid_available():
    cfg = load_config()
    if cfg.official_transform.available:
        with pytest.raises(RuntimeError, match="decompose_alignment"):
            solve_geodetic_datum_offset(cfg)
    else:
        with pytest.raises(NotImplementedError):
            solve_geodetic_datum_offset(cfg)


# --------------------------------------------------------------------------- #
# GeoTIFF export                                                               #
# --------------------------------------------------------------------------- #
def test_trim_to_valid_drops_empty_margin(tmp_path):
    from kakhovka_altimetry.official_datum import trim_to_valid

    g = load_esri_ascii(_write_asc(tmp_path))
    # pad with an all-NODATA frame, then trim it back off
    padded = dataclasses.replace(
        g,
        lats=np.concatenate(([g.lats[0] - 0.5], g.lats, [g.lats[-1] + 0.5])),
        lons=np.concatenate(([g.lons[0] - 0.5], g.lons, [g.lons[-1] + 0.5])),
        values=np.pad(g.values, 1, constant_values=np.nan),
    )
    t = trim_to_valid(padded)
    assert t.values.shape == g.values.shape
    np.testing.assert_allclose(t.lats, g.lats)
    np.testing.assert_allclose(t.lons, g.lons)


def test_resample_preserves_a_linear_field(tmp_path):
    from kakhovka_altimetry.official_datum import resample_grid

    lats = np.linspace(44.0, 46.0, 5)
    lons = np.linspace(22.0, 25.0, 7)
    LON, LAT = np.meshgrid(lons, lats)
    g = load_esri_ascii(_write_asc(tmp_path))
    g = dataclasses.replace(g, lats=lats, lons=lons, values=0.1 + 0.01 * LAT + 0.02 * LON)

    r = resample_grid(g, 0.25)
    LON2, LAT2 = np.meshgrid(r.lons, r.lats)
    np.testing.assert_allclose(r.values, 0.1 + 0.01 * LAT2 + 0.02 * LON2, atol=1e-9)


def test_geotiff_roundtrip_orientation_and_tags(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from kakhovka_altimetry.official_datum import to_geotiff

    cfg = load_config()
    g = load_esri_ascii(_write_asc(tmp_path))
    out = tmp_path / "out.tif"
    written = to_geotiff(g, out, cfg)

    assert written["shape"] == g.values.shape
    with rasterio.open(out) as ds:
        assert ds.crs.to_string() == "EPSG:4258"
        assert ds.nodata == -9999.0
        # north-up: first raster row is the HIGHEST latitude
        a = ds.read(1, masked=True)
        np.testing.assert_allclose(a[-1].compressed(), g.values[0], rtol=1e-6)
        # geotransform origin is the outer NW corner, half a cell beyond the centre
        dx = float(g.lons[1] - g.lons[0])
        assert ds.bounds.left == pytest.approx(g.lons[0] - dx / 2)
        assert ds.bounds.top == pytest.approx(g.lats[-1] + dx / 2)
        # sampling the raster reproduces the source values
        for i, lat in enumerate(g.lats):
            for j, lon in enumerate(g.lons):
                if np.isnan(g.values[i, j]):
                    continue
                got = float(next(ds.sample([(lon, lat)]))[0])
                assert got == pytest.approx(g.values[i, j], abs=1e-6)
        tags = ds.tags()
        assert tags["EPSG_OPERATION"] == "9902"
        assert "ADD this value" in tags["SIGN_CONVENTION"]
        assert tags["UNITS"] == "metre"
        assert tags["TIDE_SYSTEM"] == "zero-tide"


def test_geotiff_metadata_flags_resampling(tmp_path):
    from kakhovka_altimetry.official_datum import geotiff_metadata

    cfg = load_config()
    g = load_esri_ascii(_write_asc(tmp_path))
    assert "RESAMPLED" not in geotiff_metadata(cfg, g)
    assert "adds no information" in geotiff_metadata(cfg, g, resampled_from=0.15)["RESAMPLED"]


def test_correction_matches_proj_vgridshift(tmp_path):
    """Our ASCII reader + bilinear sampler must agree with PROJ's own vgridshift.

    This is the independent check the statistics comparison cannot give: PROJ
    defines EPSG:9902 but ships no grid for it, so once we supply the grid
    ourselves PROJ can run the very same shift through a completely separate
    implementation. Agreement is at the nanometre level.
    """
    pyproj = pytest.importorskip("pyproj")
    rasterio = pytest.importorskip("rasterio")

    from kakhovka_altimetry.official_datum import load_official_grid, to_geotiff

    cfg = load_config()
    if not cfg.official_transform.available:
        pytest.skip(f"official grid missing: {cfg.official_transform.path}")

    grid = load_official_grid(cfg)
    tif = tmp_path / "vgrid.tif"
    to_geotiff(grid, tif, cfg, overviews=False)

    # PROJ identifies a vertical-offset grid by TYPE + the band description.
    with rasterio.open(tif) as ds:
        assert ds.tags()["TYPE"] == "VERTICAL_OFFSET_VERTICAL_TO_VERTICAL"
        assert ds.descriptions[0] == "vertical_offset"

    try:
        tr = pyproj.Transformer.from_pipeline(
            f"+proj=vgridshift +grids={tif} +multiplier=1"
        )
    except pyproj.exceptions.ProjError as exc:      # pragma: no cover - env dependent
        pytest.skip(f"PROJ refused the grid: {exc}")

    pts = [(s.lon, s.lat) for s in cfg.gauges.stations if s.lon is not None]
    assert pts, "no gauge coordinates to test against"
    for lon, lat in pts:
        ours = float(correction_at(grid, lat, lon)[0])
        theirs = tr.transform(lon, lat, 0.0)[2]
        assert ours == pytest.approx(theirs, abs=1e-6), (lon, lat)

    # and away from the control points, over the grid interior
    rng = np.random.default_rng(7)
    lats = rng.uniform(45.0, 52.0, 120)
    lons = rng.uniform(23.0, 40.0, 120)
    ours = correction_at(grid, lats, lons)
    theirs = np.array([tr.transform(x, y, 0.0)[2]
                       for x, y in zip(lons, lats, strict=True)])
    both = np.isfinite(ours) & np.isfinite(theirs)
    assert both.sum() > 50, "too few in-domain sample points to be meaningful"
    assert np.abs(ours[both] - theirs[both]).max() < 1e-6
