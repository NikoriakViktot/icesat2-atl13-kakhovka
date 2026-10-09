"""Ellipsoidal ICESat-2 heights -> orthometric / normal heights, for any product.

    H_m = h_ellipsoid - N        N_m = geoid (EGM2008) or quasigeoid (EGG2015) height

* ``egg2015`` -- N = EGG2015 quasigeoid (Europe only; EVRF2007-consistent normal
  heights, exactly the reservoir pipeline's ``H_evrs_egg2015_m``).
* ``egm2008`` -- N = EGM2008 geoid via PROJ (``EPSG:4979 -> EPSG:9518``), global.
  The grid is fetched from the PROJ CDN on first use (``PROJ_NETWORK=ON``).

Independently of the region's choice, ``H_egm2008_m`` is always provided: the
reference DEMs (Copernicus GLO-30, FABDEM) are EGM2008 heights, so every DEM
comparison is done in that frame.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from .regions import EGG2015, EGM2008, VERTICAL_DATUM_LABEL
from .vertical import GeoidGrid


@lru_cache(maxsize=1)
def _egm2008_transformer():
    from pyproj import Transformer, network

    network.set_network_enabled(True)
    # only_best: raise instead of silently falling back to a ballpark (N = 0) transform
    return Transformer.from_crs("EPSG:4979", "EPSG:9518", always_xy=True, only_best=True)


def egm2008_undulation(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """EGM2008 geoid height N (m) at the given points."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    if lat.size == 0:
        return np.empty(0)
    _, _, h_ortho = _egm2008_transformer().transform(lon, lat, np.zeros_like(lat))
    n = -np.asarray(h_ortho, float)
    n[~np.isfinite(n) | (np.abs(n) > 200)] = np.nan
    return n


def add_heights(
    df: pd.DataFrame,
    height_col: str,
    vertical: str,
    *,
    geoid: GeoidGrid | None = None,
    egm2008_col: str | None = None,
) -> pd.DataFrame:
    """Add ``N_m``, ``H_m``, ``vertical_datum`` and ``H_egm2008_m``.

    ``egm2008_col`` -- a product column that already holds EGM2008 heights (ATL13
    ``H_egm2008_m`` from ``ht_ortho``); otherwise EGM2008 comes from PROJ.
    """
    out = df.copy()
    h = out[height_col].to_numpy(float)
    lat, lon = out["lat"].to_numpy(float), out["lon"].to_numpy(float)

    if egm2008_col is not None and egm2008_col in out.columns:
        h_egm = out[egm2008_col].to_numpy(float)
    else:
        h_egm = h - egm2008_undulation(lat, lon)

    if vertical == EGG2015:
        if geoid is None:
            raise ValueError("vertical='egg2015' needs the EGG2015 grid")
        n = geoid.sample(lat, lon)
        if len(n) and np.all(np.isnan(n)):
            raise ValueError("all points fall outside the EGG2015 grid (Europe only); "
                             "use vertical='egm2008' for this region")
    elif vertical == EGM2008:
        n = h - h_egm
    else:
        raise ValueError(f"unknown vertical {vertical!r}")

    out["N_m"] = n
    out["H_m"] = h - n
    out["H_egm2008_m"] = h_egm
    out["vertical_datum"] = VERTICAL_DATUM_LABEL[vertical]
    return out
