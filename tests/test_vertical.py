import numpy as np
import pytest

from kakhovka_altimetry.vertical import (
    GeoidGrid,
    egm2008_minus_evrs,
    to_evrs,
)


def test_to_evrs_is_h_minus_zeta():
    h = np.array([50.0, 51.0, 49.5])
    zeta = np.array([25.0, 25.1, 24.9])
    np.testing.assert_allclose(to_evrs(h, zeta), h - zeta)


def test_egm2008_minus_evrs_sign():
    # H_egm2008 slightly above H_evrs -> positive diagnostic
    assert egm2008_minus_evrs(np.array([16.2]), np.array([16.0]))[0] == pytest.approx(0.2)


def test_geoidgrid_bilinear_on_linear_field():
    # zeta(lat, lon) = 10 + 2*lat + 3*lon  -> bilinear interp must be exact
    lats = np.linspace(46.0, 48.0, 5)
    lons = np.linspace(33.0, 36.0, 7)
    LON, LAT = np.meshgrid(lons, lats)
    values = 10 + 2 * LAT + 3 * LON
    grid = GeoidGrid(lats=lats, lons=lons, values=values, crs="EPSG:4258")

    qlat = np.array([46.5, 47.25, 47.9])
    qlon = np.array([33.7, 34.2, 35.5])
    expected = 10 + 2 * qlat + 3 * qlon
    np.testing.assert_allclose(grid.sample(qlat, qlon), expected, rtol=1e-9)


def test_geoidgrid_out_of_bounds_is_nan():
    grid = GeoidGrid(
        lats=np.array([46.0, 47.0]),
        lons=np.array([33.0, 34.0]),
        values=np.zeros((2, 2)),
        crs="EPSG:4258",
    )
    assert np.isnan(grid.sample(np.array([90.0]), np.array([0.0]))[0])


def test_load_isg_roundtrip(tmp_path):
    from kakhovka_altimetry.vertical import _load_isg

    # 2x3 grid, rows from lat_max down to lat_min (ISG convention)
    content = "\n".join([
        "begin_of_head ================================================",
        "model name          : test",
        "lat min             :   46.000000",
        "lat max             :   47.000000",
        "lon min             :   33.000000",
        "lon max             :   35.000000",
        "delta lat           :    1.000000",
        "delta lon           :    1.000000",
        "nrows               :    2",
        "ncols               :    3",
        "nodata              :   -9999.0000",
        "end_of_head ==================================================",
        "1.0 2.0 3.0",
        "4.0 5.0 6.0",
    ])
    p = tmp_path / "test.isg"
    p.write_text(content)

    grid = _load_isg(p)
    assert grid.values.shape == (2, 3)
    # after the ISG flip, ascending latitude row 0 is the file's LAST row
    np.testing.assert_allclose(grid.values[0], [4.0, 5.0, 6.0])
    np.testing.assert_allclose(grid.lats, [46.0, 47.0])


def test_isg_coord_parsing():
    from kakhovka_altimetry.vertical import _isg_coord

    assert _isg_coord("47.5") == pytest.approx(47.5)
    assert _isg_coord('25°30\'00"') == pytest.approx(25.5)
    assert _isg_coord("-50 0 0") == pytest.approx(-50.0)
    assert _isg_coord('0°02\'00"') == pytest.approx(2 / 60)


def test_load_isg_dms_header(tmp_path):
    from kakhovka_altimetry.vertical import _load_isg

    content = "\n".join([
        "begin_of_head ================================================",
        "model name          : EGG2015-like",
        "data ordering       : N-to-S, W-to-E",
        "ref ellipsoid       : GRS80",
        'lat min             :   46°00\'00"',
        'lat max             :   47°00\'00"',
        'lon min             :   33°00\'00"',
        'lon max             :   35°00\'00"',
        'delta lat           :    1°00\'00"',
        'delta lon           :    1°00\'00"',
        "nrows               :    2",
        "ncols               :    3",
        "nodata              :   -9999.0000",
        "end_of_head ==================================================",
        "10.0 11.0 12.0",   # northern row (lat 47) first
        "13.0 14.0 15.0",   # southern row (lat 46)
    ])
    p = tmp_path / "egg.isg"
    p.write_text(content)

    grid = _load_isg(p)
    np.testing.assert_allclose(grid.lats, [46.0, 47.0])
    np.testing.assert_allclose(grid.lons, [33.0, 34.0, 35.0])
    np.testing.assert_allclose(grid.values[0], [13.0, 14.0, 15.0])  # lat 46
    np.testing.assert_allclose(grid.values[1], [10.0, 11.0, 12.0])  # lat 47
