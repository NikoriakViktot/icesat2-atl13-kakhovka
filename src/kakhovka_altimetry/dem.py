"""Digital elevation models: reference-DEM sampling, ICESat-2 vs DEM statistics,
and gridding ICESat-2 points into a raster (Cloud-Optimised GeoTIFF).

Reference DEMs -- both 1 arc-second (~30 m), both EGM2008 orthometric heights,
both read as 1x1 degree COG tiles and cached (local dir + optional S3 prefix):

* ``cop30``  -- Copernicus GLO-30 DSM, AWS Open Data ``copernicus-dem-30m``
  (public, no credentials). Read directly rather than through SlideRule's raster
  sampling: SlideRule's ``esa-copernicus-30meter`` samples came back ellipsoidal at
  Kakhovka (cop30 - FABDEM = 23.0 m = N) but orthometric on Lake Victoria (1133.0 m),
  so their vertical frame cannot be relied on.
* ``fabdem`` -- FABDEM V1-2 (Copernicus with forests and buildings removed; Hawker
  et al. 2022, University of Bristol, **CC BY-NC-SA 4.0: non-commercial**). Tiles
  are read straight out of Bristol's 10x10 degree zips with HTTP range requests.

ICESat-2 heights are compared as ``H_egm2008_m - dem`` so both sides are EGM2008.
"""

from __future__ import annotations

import logging
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

COP30_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
FABDEM_BASE = "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn"
FABDEM_VERSION = "V1-2"
FABDEM_NODATA = -9999.0
REFERENCE_DEMS = ("cop30", "fabdem")
NMAD_K = 1.4826


def _ns(lat: int) -> str:
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"


def _ew(lon: int) -> str:
    return f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"


def cop30_tile(lat: float, lon: float) -> str:
    """``Copernicus_DSM_COG_10_N46_00_E033_00_DEM`` (SW corner of the 1x1 tile)."""
    la, lo = math.floor(lat), math.floor(lon)
    return f"Copernicus_DSM_COG_10_{_ns(la)}_00_{_ew(lo)}_00_DEM"


def fabdem_tile(lat: float, lon: float) -> str:
    """1x1 degree tile containing the point, named by its SW corner."""
    return f"{_ns(math.floor(lat))}{_ew(math.floor(lon))}_FABDEM_{FABDEM_VERSION}.tif"


def fabdem_zip(lat: float, lon: float) -> str:
    """The 10x10 degree zip holding that tile, e.g. ``N40E030-N50E040_FABDEM_V1-2.zip``."""
    la, lo = math.floor(lat / 10) * 10, math.floor(lon / 10) * 10
    return f"{_ns(la)}{_ew(lo)}-{_ns(la + 10)}{_ew(lo + 10)}_FABDEM_{FABDEM_VERSION}.zip"


class TileSource:
    """A tiled 1x1 degree DEM: local cache -> S3 cache -> origin (subclass ``_fetch``)."""

    name = "dem"

    def __init__(self, cache_dir: Path, s3_prefix: str | None = None,
                 base_url: str | None = None):
        self.cache_dir = Path(cache_dir) / self.name
        self.s3_prefix = s3_prefix.rstrip("/") if s3_prefix else None
        if base_url is not None:
            self.base_url = base_url
        self.missing: set[str] = set()   # tiles the DEM does not have (open ocean)

    def tile_file(self, lat: float, lon: float) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def _fetch(self, tile: str, lat: float, lon: float) -> bytes | None:  # pragma: no cover
        raise NotImplementedError

    def tile_path(self, lat: float, lon: float) -> Path | None:
        tile = self.tile_file(lat, lon)
        local = self.cache_dir / tile
        if local.exists():
            return local
        if tile in self.missing:
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        import fsspec

        if self.s3_prefix:
            fs, path = fsspec.core.url_to_fs(f"{self.s3_prefix}/{tile}")
            if fs.exists(path):
                fs.get(path, str(local))
                return local
        data = self._fetch(tile, lat, lon)
        if data is None:
            self.missing.add(tile)
            return None
        tmp = local.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.rename(local)
        if self.s3_prefix:
            fs, path = fsspec.core.url_to_fs(f"{self.s3_prefix}/{tile}")
            fs.put(str(local), path)
        return local

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        import rasterio

        lat = np.asarray(lat, float)
        lon = np.asarray(lon, float)
        out = np.full(lat.size, np.nan)
        if lat.size == 0:
            return out
        keys = pd.Series([self.tile_file(a, o) for a, o in zip(lat, lon, strict=True)])
        for _, idx in keys.groupby(keys).groups.items():
            idx = np.asarray(idx)
            path = self.tile_path(lat[idx[0]], lon[idx[0]])
            if path is None:
                continue
            with rasterio.open(path) as ds:
                xy = zip(lon[idx], lat[idx], strict=True)
                vals = np.array([v[0] for v in ds.sample(xy)], float)
                nod = ds.nodata
            if nod is not None:
                vals[vals == nod] = np.nan
            vals[np.abs(vals) > 1e4] = np.nan
            out[idx] = vals
        return out


class Cop30Source(TileSource):
    """Copernicus GLO-30 DSM tiles from AWS Open Data (no credentials)."""

    name = "cop30"
    base_url = COP30_BASE

    def tile_file(self, lat: float, lon: float) -> str:
        return cop30_tile(lat, lon) + ".tif"

    def _fetch(self, tile: str, lat: float, lon: float) -> bytes | None:
        import fsspec

        stem = tile[:-4]
        url = f"{self.base_url}/{stem}/{tile}"
        log.info("COP30: downloading %s", url)
        try:
            with fsspec.open(url, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return None


class FabdemSource(TileSource):
    """FABDEM V1-2 tiles extracted from Bristol's 10x10 degree zips (range reads)."""

    name = "fabdem"
    base_url = FABDEM_BASE

    def tile_file(self, lat: float, lon: float) -> str:
        return fabdem_tile(lat, lon)

    def _fetch(self, tile: str, lat: float, lon: float) -> bytes | None:
        import fsspec

        url = f"{self.base_url}/{fabdem_zip(lat, lon)}"
        log.info("FABDEM: extracting %s from %s", tile, url)
        try:
            with fsspec.open(url, block_size=2**22).open() as fh, zipfile.ZipFile(fh) as zf:
                members = {Path(n).name: n for n in zf.namelist()}
                return zf.read(members[tile]) if tile in members else None
        except FileNotFoundError:
            return None


SOURCES = {"cop30": Cop30Source, "fabdem": FabdemSource}


# --------------------------------------------------------------------------- #
# ICESat-2 vs reference DEM                                                    #
# --------------------------------------------------------------------------- #
def compare(df: pd.DataFrame, dem_col: str, *, height_col: str = "H_egm2008_m",
            mask: np.ndarray | None = None) -> dict:
    """Statistics of ``height_col - dem_col`` (m) over the valid points."""
    h = df[height_col].to_numpy(float)
    d = df[dem_col].to_numpy(float) if dem_col in df else np.full(len(df), np.nan)
    ok = np.isfinite(h) & np.isfinite(d)
    if mask is not None:
        ok &= np.asarray(mask, bool)
    dh = h[ok] - d[ok]
    if dh.size == 0:
        return {"n": 0}
    med = float(np.median(dh))
    return {
        "n": int(dh.size),
        "median_m": med,
        "nmad_m": float(NMAD_K * np.median(np.abs(dh - med))),
        "mean_m": float(dh.mean()),
        "std_m": float(dh.std(ddof=1)) if dh.size > 1 else float("nan"),
        "rmse_m": float(np.sqrt(np.mean(dh ** 2))),
        "p05_m": float(np.percentile(dh, 5)),
        "p95_m": float(np.percentile(dh, 95)),
    }


def add_reference_dems(df: pd.DataFrame, refs: list[str], *,
                       sources: dict[str, TileSource] | None = None) -> pd.DataFrame:
    """Sample the requested reference DEMs (``<dem>_m``, EGM2008) unless already
    present, and add ``dh_<dem>_m`` = ``H_egm2008_m - <dem>_m``."""
    out = df.copy()
    sources = sources or {}
    for ref in refs:
        if ref not in REFERENCE_DEMS:
            raise ValueError(f"unknown reference DEM {ref!r}; use {REFERENCE_DEMS}")
        col = f"{ref}_m"
        if col not in out.columns:
            if ref not in sources:
                raise ValueError(f"no tile source for reference DEM {ref!r}")
            out[col] = sources[ref].sample(out["lat"].to_numpy(), out["lon"].to_numpy())
        out[f"dh_{ref}_m"] = out["H_egm2008_m"].to_numpy(float) - out[col].to_numpy(float)
    return out


# --------------------------------------------------------------------------- #
# Gridding ICESat-2 points -> raster                                           #
# --------------------------------------------------------------------------- #
def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def grid_points(
    df: pd.DataFrame, value_col: str, resolution_m: float, *, epsg: int | None = None,
    stat: str = "median",
) -> dict:
    """Bin points into a ``resolution_m`` grid in UTM (median per cell by default).

    Returns ``{"value", "count", "transform", "crs", "bounds_4326"}``; cells without
    points are NaN -- ICESat-2 tracks are km apart, so the raster is honest about
    its gaps rather than interpolating across them.
    """
    from pyproj import Transformer
    from rasterio.transform import from_origin

    pts = df[np.isfinite(df[value_col].to_numpy(float))]
    if pts.empty:
        raise ValueError(f"no finite {value_col!r} values to grid")
    lon, lat = pts["lon"].to_numpy(float), pts["lat"].to_numpy(float)
    epsg = epsg or utm_epsg(float(np.median(lon)), float(np.median(lat)))
    x, y = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    r = float(resolution_m)
    x0, y1 = math.floor(x.min() / r) * r, math.ceil(y.max() / r) * r
    if y1 == y.max():
        y1 += r
    col = ((x - x0) // r).astype(np.int64)
    row = ((y1 - y) // r).astype(np.int64)
    ncol, nrow = int(col.max()) + 1, int(row.max()) + 1
    if ncol * nrow > 50_000_000:
        raise ValueError(f"grid {nrow}x{ncol} too large at {r} m; use a coarser resolution")
    cells = pd.DataFrame({"cell": row * ncol + col, "v": pts[value_col].to_numpy(float)})
    agg = cells.groupby("cell")["v"].agg([stat, "size"])
    value = np.full(nrow * ncol, np.nan, dtype="float32")
    count = np.zeros(nrow * ncol, dtype="float32")
    value[agg.index.to_numpy()] = agg[stat].to_numpy()
    count[agg.index.to_numpy()] = agg["size"].to_numpy()
    transform = from_origin(x0, y1, r, r)
    back = Transformer.from_crs(epsg, 4326, always_xy=True)
    bx, by = back.transform([x0, x0 + ncol * r, x0 + ncol * r, x0],
                            [y1, y1, y1 - nrow * r, y1 - nrow * r])
    return {
        "value": value.reshape(nrow, ncol),
        "count": count.reshape(nrow, ncol),
        "transform": transform,
        "crs": f"EPSG:{epsg}",
        "footprint_4326": list(zip(bx, by, strict=True)),
    }


def write_cog(grid: dict, path: Path, *, description: str = "") -> Path:
    """Two-band COG: band 1 = value (float32, NaN nodata), band 2 = point count."""
    import rasterio.shutil
    from rasterio.io import MemoryFile

    value, count = grid["value"], grid["count"]
    profile = {
        "driver": "GTiff", "height": value.shape[0], "width": value.shape[1], "count": 2,
        "dtype": "float32", "crs": grid["crs"], "transform": grid["transform"],
        "nodata": float("nan"),
    }
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            ds.write(value, 1)
            ds.write(count, 2)
            ds.set_band_description(1, description or "value")
            ds.set_band_description(2, "n_points")
        with mem.open() as src:
            rasterio.shutil.copy(src, str(path), driver="COG", compress="DEFLATE",
                                 predictor=3, blocksize=256)
    return Path(path)


def raster_stats(grid: dict) -> dict:
    v = grid["value"]
    ok = np.isfinite(v)
    out = {"rows": int(v.shape[0]), "cols": int(v.shape[1]), "valid_cells": int(ok.sum()),
           "points": int(grid["count"].sum())}
    if ok.any():
        out.update(min=float(np.nanmin(v)), max=float(np.nanmax(v)),
                   median=float(np.nanmedian(v)))
    return out

