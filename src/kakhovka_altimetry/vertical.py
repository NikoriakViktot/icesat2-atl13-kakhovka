"""The vertical bridge: ellipsoidal ATL13 heights -> EVRS via the EGG2015 quasigeoid.

    H_evrs = h_ellipsoid - zeta_egg2015

``h_ellipsoid`` is ATL13 ``ht_water_surf`` (segments column ``h_wgs84_m``). The
EGM2008-referenced ``ht_ortho`` (``H_egm2008_m``) is used **only** for the
``egm2008_minus_evrs_m`` cross-check and never enters the EVRS chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config

EVRS_COLUMNS = [
    "zeta_egg2015_m",
    "H_evrs_egg2015_m",
    "egm2008_minus_evrs_m",
    "period",
]


# --------------------------------------------------------------------------- #
# Grid loading                                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class GeoidGrid:
    """A regular lat/lon geoid/quasigeoid grid with bilinear sampling."""

    lats: np.ndarray            # 1-D, ascending
    lons: np.ndarray            # 1-D, ascending
    values: np.ndarray          # shape (len(lats), len(lons)); NaN for nodata
    crs: str

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Bilinearly interpolate the grid at the given lat/lon (degrees)."""
        from scipy.interpolate import RegularGridInterpolator

        interp = RegularGridInterpolator(
            (self.lats, self.lons),
            self.values,
            method="linear",
            bounds_error=False,
            fill_value=np.nan,
        )
        pts = np.column_stack([np.asarray(lat, float), np.asarray(lon, float)])
        return interp(pts)


def _isg_coord(text: str) -> float:
    """Parse an ISG coordinate: decimal degrees, or DMS like ``25°01'30"`` / ``-50 0 0``."""
    t = text.strip().strip('"')
    try:
        return float(t)
    except ValueError:
        pass
    for ch in ("°", "'", '"', "d", "m", "s", ":"):
        t = t.replace(ch, " ")
    parts = [p for p in t.split() if p]
    sign = -1.0 if parts[0].startswith("-") else 1.0
    nums = [abs(float(p)) for p in parts]
    deg = nums[0] if nums else 0.0
    minute = nums[1] if len(nums) > 1 else 0.0
    second = nums[2] if len(nums) > 2 else 0.0
    return sign * (deg + minute / 60.0 + second / 3600.0)


def _load_isg(path: Path) -> GeoidGrid:
    """Reader for the ISG 1.0/2.0 text format (e.g. EGG2015 from isgeoid.polimi.it).

    Handles decimal-degree or DMS coordinate fields and N-to-S / S-to-N row
    ordering. Grid values are quasigeoid heights (zeta) in metres.
    """
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header: dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(text):
        low = line.strip().lower()
        if low.startswith(("begin_of_head", "isg format")):
            continue
        if low.startswith(("end_of_head", "begin_of_data")):
            body_start = i + 1
            break
        if ":" in line:
            key, _, val = line.partition(":")
            header[key.strip().lower()] = val.strip()

    def h(*names: str) -> str:
        for n in names:
            if n in header:
                return header[n]
        raise KeyError(names)

    lat_min = _isg_coord(h("lat min"))
    lat_max = _isg_coord(h("lat max"))
    lon_min = _isg_coord(h("lon min"))
    lon_max = _isg_coord(h("lon max"))
    dlat = _isg_coord(h("delta lat"))
    dlon = _isg_coord(h("delta lon"))
    nrows = int(h("nrows"))
    ncols = int(h("ncols"))
    nodata = float(h("nodata")) if "nodata" in header else -9999.0
    ordering = header.get("data ordering", "N-to-S").lower()

    flat = np.fromstring(" ".join(text[body_start:]), sep=" ")
    grid = flat[: nrows * ncols].reshape(nrows, ncols)
    grid = np.where(np.isclose(grid, nodata), np.nan, grid)

    lats = np.linspace(lat_min, lat_max, nrows)
    lons = np.linspace(lon_min, lon_max, ncols)
    if ordering.startswith("n-to-s") or "n_to_s" in ordering:
        grid = grid[::-1, :]      # file rows go lat_max -> lat_min; make ascending
    if lon_min > lon_max:
        lons = lons[::-1]
        grid = grid[:, ::-1]

    assert nrows == 1 or abs((lats[1] - lats[0]) - dlat) < 1e-6
    assert ncols == 1 or abs((lons[1] - lons[0]) - dlon) < 1e-6
    return GeoidGrid(lats=lats, lons=lons, values=grid, crs="EPSG:4258")


def _load_raster(path: Path, crs: str) -> GeoidGrid:
    import rasterio

    with rasterio.open(path) as ds:
        band = ds.read(1, masked=True).filled(np.nan).astype("float64")
        h, w = band.shape
        # Cell-centre coordinates.
        xs = np.array([ds.xy(0, c)[0] for c in range(w)])
        ys = np.array([ds.xy(r, 0)[1] for r in range(h)])
        raster_crs = str(ds.crs) if ds.crs else crs

    # Ensure ascending axes.
    if ys[0] > ys[-1]:
        ys = ys[::-1]
        band = band[::-1, :]
    if xs[0] > xs[-1]:
        xs = xs[::-1]
        band = band[:, ::-1]
    return GeoidGrid(lats=ys, lons=xs, values=band, crs=raster_crs)


def load_geoid(cfg: Config) -> GeoidGrid:
    """Load the EGG2015 grid described by ``config/vertical_datums.yaml``."""
    return load_geoid_file(cfg.egg2015.path, cfg.egg2015.grid_crs)


def load_geoid_file(path: Path, crs: str = "EPSG:4258") -> GeoidGrid:
    """Load an EGG2015 grid from an explicit local path (``.isg`` or a raster)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"EGG2015 grid not found at {path}. Place/symlink it there and set the "
            f"path in config/vertical_datums.yaml."
        )
    if path.suffix.lower() == ".isg":
        return _load_isg(path)
    return _load_raster(path, crs)


# --------------------------------------------------------------------------- #
# Pure transforms                                                              #
# --------------------------------------------------------------------------- #
def to_evrs(h_ellipsoid: np.ndarray, zeta: np.ndarray) -> np.ndarray:
    """H_evrs = h_ellipsoid - zeta (quasigeoid height)."""
    return np.asarray(h_ellipsoid, float) - np.asarray(zeta, float)


def egm2008_minus_evrs(h_egm2008: np.ndarray, h_evrs: np.ndarray) -> np.ndarray:
    """Diagnostic: EGM2008 orthometric minus EGG2015/EVRS height.

    Over the AOI this is the (geoid - quasigeoid) + (EGM2008 - EVRF2007) difference:
    small (decimetre-level) and spatially smooth. Large or noisy values mean the
    vertical chain has been mixed up.
    """
    return np.asarray(h_egm2008, float) - np.asarray(h_evrs, float)


# --------------------------------------------------------------------------- #
# DataFrame entry point                                                        #
# --------------------------------------------------------------------------- #
def add_evrs_columns(
    segments: pd.DataFrame, cfg: Config, *, geoid: GeoidGrid | None = None
) -> pd.DataFrame:
    """Return ``segments`` + the EVRS columns (see :data:`EVRS_COLUMNS`)."""
    df = segments.copy()
    geoid = geoid or load_geoid(cfg)

    zeta = geoid.sample(df["lat"].to_numpy(dtype=float), df["lon"].to_numpy(dtype=float))
    df["zeta_egg2015_m"] = zeta
    df["H_evrs_egg2015_m"] = to_evrs(df["h_wgs84_m"].to_numpy(dtype=float), zeta)
    df["egm2008_minus_evrs_m"] = egm2008_minus_evrs(
        df["H_egm2008_m"].to_numpy(dtype=float), df["H_evrs_egg2015_m"].to_numpy()
    )
    dates = pd.to_datetime(df["time"], utc=True).dt.date
    df["period"] = [cfg.regimes.label_for(d) for d in dates]
    return df
