"""Phase 2d -- nearest-station EGG2015 -> EVRF2019 corrector surface (Variant A).

Phase 2c (:mod:`kakhovka_altimetry.egg2015_corrector`) gives six point estimates

    c_station = median( H_gauge_EVRF2019 - H_ICESat_EGG2015 )

at the six Kakhovka gauges. This module turns those six points into a spatial
lookup so any ATL13 segment in the reservoir can carry an empirical EVRF2019
height, not just the segments that happen to sit near a gauge.

**Method: nearest-station (Voronoi) assignment, not IDW or a plane fit.** With
six stations -- one of them (Rozumivka) bimodal by RGT and another (Velyka
Lepetykha) at only 5 independent beam-passes -- a smooth interpolated surface
would let an unreliable station's value bleed into its neighbours' territory.
Nearest-station keeps every corrector's influence bounded to its own cell and
never blends it with another station's. ``distance_to_control_km`` is carried
on every output row precisely so a user can judge confidence themselves
instead of the surface silently deciding it for them; there is deliberately no
hard distance cutoff (see :func:`nearest_station`).

**This is a spatial lookup, not a new geodetic model.** Each cell's value is
still exactly one of the six ``c_station`` numbers, with all the caveats from
Phase 2c: it absorbs the EGG2015/EVRF2019 mismatch, the unsurveyed gauge zero,
and any systematic ATL13 bias, inseparably. See
``outputs/reports/egg2015_to_evrf2019_gauge_experiment.md``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .aggregate import _haversine_km
from .config import Config
from .vertical import GeoidGrid

STATION_TABLE_COLUMNS = [
    "station_id", "slug", "name_en", "lat", "lon",
    "c_station_m", "sigma_m", "reported_radius_km", "n_matchups", "flag",
]

CORRECTOR_COLUMNS = [
    "nearest_control_station", "distance_to_control_km",
    "egg2015_to_evrf2019_corrector_m", "corrector_uncertainty_m",
]


def load_station_correctors(cfg: Config) -> pd.DataFrame:
    """Per-station corrector + empirical precision, from Phase 2c's by-station table.

    ``sigma_m`` is the beam-pass NMAD (repeatability), not the bootstrap CI --
    Rozumivka's bootstrap CI is wide and bimodal by RGT (RGT 989 vs 205; see
    the Phase 2c report), so NMAD is the more robust per-station precision
    figure to carry into a spatial product.
    """
    path = cfg.tables_dir / "egg2015_to_evrf2019_by_station.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run `python scripts/egg2015_to_evrf2019.py` first."
        )
    df = pd.read_csv(path)
    df = df[np.isfinite(df["c_station_m"])].copy()
    df = df.rename(columns={"empirical_nmad_m": "sigma_m"})
    if df.empty:
        raise ValueError(f"no station in {path} has a usable c_station_m")
    return df[STATION_TABLE_COLUMNS].reset_index(drop=True)


def nearest_station(lat, lon, stations: pd.DataFrame) -> pd.DataFrame:
    """Nearest-station (Voronoi) corrector lookup for arbitrary points.

    One row per input point: ``nearest_control_station`` (slug),
    ``distance_to_control_km``, ``egg2015_to_evrf2019_corrector_m``,
    ``corrector_uncertainty_m``. No distance cutoff is applied -- every point
    gets *some* corrector, with the distance reported so a caller can decide
    for themselves whether a point is too far from the control network to
    trust (the AOI bbox already keeps the surface from being applied outside
    the reservoir; see :func:`build_corrector_grid`).
    """
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    if stations.empty:
        raise ValueError("no usable station correctors")

    dists = np.column_stack([
        _haversine_km(lat, lon, float(row.lat), float(row.lon))
        for row in stations.itertuples()
    ])
    idx = np.argmin(dists, axis=1)
    picked = stations.iloc[idx].reset_index(drop=True)
    return pd.DataFrame({
        "nearest_control_station": picked["slug"].to_numpy(),
        "distance_to_control_km": dists[np.arange(len(lat)), idx],
        "egg2015_to_evrf2019_corrector_m": picked["c_station_m"].to_numpy(float),
        "corrector_uncertainty_m": picked["sigma_m"].to_numpy(float),
    })


def augment_points(
    df: pd.DataFrame, stations: pd.DataFrame, *,
    lat_col: str = "lat", lon_col: str = "lon", level_col: str = "H_evrs_egg2015_m",
    out_col: str = "h_evrf2019_empirical_m",
) -> pd.DataFrame:
    """Add the corrector + empirical-EVRF2019 columns to an ATL13 table.

    ``level_col`` must already be an EGG2015-referenced EVRS height
    (``ht_water_surf - zeta_EGG2015``, the vertical rule -- see
    [[project-overview]]). This is a spatial lookup, not a re-derivation: the
    corrector itself comes only from PRE_BREACH gauge matchups
    (:mod:`kakhovka_altimetry.egg2015_corrector`); applying it to
    BREACH_DRAWDOWN/POST_BREACH rows assumes the local EGG2015/ATL13
    systematic terms it absorbs do not depend on reservoir stage -- a
    reasonable assumption for a geodetic/instrument bias, but not tested here.
    """
    out = df.copy()
    add = nearest_station(out[lat_col].to_numpy(), out[lon_col].to_numpy(), stations)
    for col in add.columns:
        out[col] = add[col].to_numpy()
    out[out_col] = out[level_col] + out["egg2015_to_evrf2019_corrector_m"]
    return out


def build_corrector_grid(
    cfg: Config, stations: pd.DataFrame, cell_deg: float = 0.005,
) -> tuple[GeoidGrid, GeoidGrid]:
    """Voronoi corrector + uncertainty rasters over the reservoir AOI bbox.

    The AOI bbox (``config/kakhovka.yaml``) is the only extrapolation guard:
    the raster is not built, and should not be sampled, outside it.
    """
    lon_min, lat_min, lon_max, lat_max = cfg.aoi_bbox
    lons = np.arange(lon_min, lon_max + cell_deg / 2, cell_deg)
    lats = np.arange(lat_min, lat_max + cell_deg / 2, cell_deg)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    add = nearest_station(lat_grid.ravel(), lon_grid.ravel(), stations)

    corrector = GeoidGrid(
        lats=lats, lons=lons, crs="EPSG:4258",
        values=add["egg2015_to_evrf2019_corrector_m"].to_numpy(float).reshape(lat_grid.shape),
    )
    uncertainty = GeoidGrid(
        lats=lats, lons=lons, crs="EPSG:4258",
        values=add["corrector_uncertainty_m"].to_numpy(float).reshape(lat_grid.shape),
    )
    return corrector, uncertainty


def corrector_geotiff_metadata(stations: pd.DataFrame) -> dict:
    return {
        "TITLE": "Empirical EGG2015 -> EVRF2019 corrector, Kakhovka reservoir",
        "PRODUCT_TYPE": "empirical ATL13/gauge-constrained corrector surface "
                        "-- NOT an official geodetic transformation",
        "METHOD": "nearest-station (Voronoi) assignment of 6 gauge-derived "
                  "c_station values (Phase 2c)",
        "UNITS": "metre",
        "SIGN_CONVENTION": "ADD this value to H_EGG2015 (= ht_water_surf - "
                           "zeta_EGG2015) to approximate H_EVRF2019",
        "STATIONS": ",".join(stations["slug"]),
        "C_STATION_RANGE_M": f"{stations['c_station_m'].min():.3f}.."
                             f"{stations['c_station_m'].max():.3f}",
        "CALIBRATION_PERIOD": "PRE_BREACH only (before 2023-06-06)",
        "CAVEAT": "absorbs, inseparably, the EGG2015/EVRF2019 model mismatch, "
                  "the unsurveyed gauge-zero error, and any systematic ATL13 "
                  "bias -- see outputs/reports/egg2015_to_evrf2019_gauge_experiment.md",
    }


def uncertainty_geotiff_metadata(stations: pd.DataFrame) -> dict:
    return {
        "TITLE": "Empirical precision of the Kakhovka EGG2015->EVRF2019 corrector",
        "UNITS": "metre",
        "DEFINITION": "beam-pass NMAD of c_station at the nearest control gauge "
                      "(repeatability only -- not absolute accuracy)",
        "STATIONS": ",".join(stations["slug"]),
        "SIGMA_RANGE_M": f"{stations['sigma_m'].min():.3f}..{stations['sigma_m'].max():.3f}",
        "NOT_INCLUDED": "EPSG:9902 published operation accuracy (0.068 m -- an "
                        "operation-accuracy field, not a sigma), gauge-zero error, "
                        "EGG2015 model error -- see the uncertainty table",
    }
