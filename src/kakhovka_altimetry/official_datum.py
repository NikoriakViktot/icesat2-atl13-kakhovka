"""The official Ukrainian Baltic-1977 -> EVRF2019 transformation grid.

EPSG:9902 ("Baltic 1977 height to EVRF2019 height") is a *grid*, not a constant:
the correction varies across Ukraine. It is **not a quasigeoid** — it maps one
system of normal heights onto another and never touches the ellipsoid.

PROJ *defines* the operation (``Baltic 1977 height to EVRF2019 height (1)``,
accuracy 0.068, grid ``ua_2019z.asc``) but ships **no grid** for it:
``open_license=False``, ``direct_download=False``, empty URL, and no Ukrainian
grids on the CDN, so PROJ reports it ``available: False``. What PROJ can still
offer between these CRSs then degrades to a ballpark ``proj=noop`` that silently
returns 0 — which is why the grid is read directly here instead.

Once the grid *is* in hand, PROJ can perform the shift itself: see
:func:`to_geotiff`, which writes a PROJ-conformant vertical-offset GeoTIFF, and
``tests/test_official_datum.py``, which cross-checks :func:`correction_at`
against PROJ's own ``vgridshift`` (they agree to well under a millimetre).

The same product is published by CRS-EU as ``UA_KRON/NH to EVRF2019zero``
(``ua_2019z.asc``, ESRI ASCII, IDW-interpolated), which is the grid Stopkhai et al.
(2026) used to build Ukraine's BS-77 -> EVRF2019 transfer model. EPSG:9903 is the
mean-tide sibling and is deliberately not used: EGG2015 and EVRF2019 are both
zero-tide.

Sign convention: the grid value is **added** to a Baltic 1977 height to obtain the
EVRF2019 height.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import Config
from .vertical import GeoidGrid, _load_raster

_HEADER_KEYS = (
    "ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter",
    "cellsize", "dx", "dy", "nodata_value",
)


def load_esri_ascii(path: str | Path) -> GeoidGrid:
    """Read an ESRI ASCII grid (``.asc``) into a :class:`GeoidGrid`.

    Handles ``xllcorner``/``yllcorner`` and ``xllcenter``/``yllcenter`` origins and
    both ``cellsize`` and separate ``dx``/``dy``. ESRI rows run north -> south; the
    array is flipped so latitude ascends, matching ``GeoidGrid``.
    """
    path = Path(path)
    hdr: dict[str, float] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        pos = fh.tell()
        line = fh.readline()
        while line:
            parts = line.split()
            if len(parts) == 2 and parts[0].lower() in _HEADER_KEYS:
                hdr[parts[0].lower()] = float(parts[1])
                pos = fh.tell()
                line = fh.readline()
                continue
            fh.seek(pos)
            break
        values = np.loadtxt(fh)

    ncols, nrows = int(hdr["ncols"]), int(hdr["nrows"])
    dx = hdr.get("cellsize", hdr.get("dx"))
    dy = hdr.get("cellsize", hdr.get("dy"))
    if dx is None or dy is None:
        raise ValueError(f"{path.name}: no cellsize/dx/dy in header")

    values = values.reshape(nrows, ncols)
    nodata = hdr.get("nodata_value", -9999.0)
    values = np.where(np.isclose(values, nodata), np.nan, values)

    # Cell centres.
    if "xllcenter" in hdr:
        x0, y0 = hdr["xllcenter"], hdr["yllcenter"]
    else:
        x0, y0 = hdr["xllcorner"] + dx / 2.0, hdr["yllcorner"] + dy / 2.0
    lons = x0 + dx * np.arange(ncols)
    lats = y0 + dy * np.arange(nrows)

    return GeoidGrid(lats=lats, lons=lons, values=values[::-1, :], crs="EPSG:4258")


def load_official_grid(cfg: Config) -> GeoidGrid:
    """Load the transformation grid named in ``config/vertical_datums.yaml``."""
    path = cfg.official_transform.path
    if not path.exists():
        raise FileNotFoundError(
            f"official transformation grid not found at {path}. Fetch it with "
            f"`python scripts/datum_comparison.py --download` (source: "
            f"{cfg.official_transform.source_url})."
        )
    if path.suffix.lower() == ".asc":
        return load_esri_ascii(path)
    return _load_raster(path, "EPSG:4258")


def grid_statistics(grid: GeoidGrid) -> dict[str, float]:
    """mean / min / max / SD / node count over the grid's valid cells."""
    v = grid.values[np.isfinite(grid.values)]
    if v.size == 0:
        return {"n_nodes": 0, "mean_m": np.nan, "min_m": np.nan,
                "max_m": np.nan, "sd_m": np.nan}
    return {
        "n_nodes": int(v.size),
        "mean_m": float(v.mean()),
        "min_m": float(v.min()),
        "max_m": float(v.max()),
        "sd_m": float(v.std()),
    }


def validate_against_published(grid: GeoidGrid, cfg: Config) -> dict:
    """Numerical sanity check: is the loaded grid consistent with EPSG:9902?

    **This is not a proof of identity.** The published EPSG statistics are quoted
    over the transformation's **defining point set** (154 points) while ours are
    over 3776 interpolated grid nodes, so agreement of three summary statistics
    says the file is *consistent with* the product, not that it *is* the product.
    File identity is established by the SHA-256 recorded in
    ``outputs/reports/provenance.json``.

    What this check does earn its keep for is catching the real failure mode: a
    wrong, empty or all-zero grid (PROJ's ballpark ``noop`` silently returns 0),
    which would sail through unnoticed otherwise.

    Because IDW smooths the *extremes*, ``mean``, ``min`` and ``sd`` are the
    deciding statistics and ``max`` is reported but not decisive.
    """
    ot = cfg.official_transform
    got = grid_statistics(grid)
    pub = ot.published_stats
    tol = ot.validation_tolerance_m

    deltas = {k: got[k] - pub[k] for k in ("mean_m", "min_m", "max_m", "sd_m")
              if k in pub and np.isfinite(got[k])}
    decisive = [k for k in ("mean_m", "min_m", "sd_m") if k in deltas]
    passed = all(abs(deltas[k]) <= tol for k in decisive)

    return {
        "passed": bool(passed),
        "statistics": got,
        "published": dict(pub),
        "deltas": deltas,
        "decisive": decisive,
        "tolerance_m": tol,
        "node_count_matches_paper": got["n_nodes"] == ot.expected_nodes
        if ot.expected_nodes else None,
    }


def format_validation(result: dict) -> str:
    """Human-readable sanity-check block for the console and the report."""
    g, p, d = result["statistics"], result["published"], result["deltas"]
    n_pub = result["published"].get("n_determination_points")
    over = f"; published stats over {n_pub:g} determination points" if n_pub else ""
    lines = [
        "numerical sanity check vs the published EPSG:9902 metadata "
        f"(consistency, not file identity{over})",
        f"grid nodes (valid): {g['n_nodes']}"
        + ("  [matches the published node count]"
           if result.get("node_count_matches_paper") else ""),
        f"{'stat':<8}{'grid':>10}{'published':>12}{'delta':>10}   decisive",
    ]
    for k in ("mean_m", "min_m", "max_m", "sd_m"):
        if k not in d:
            continue
        lines.append(
            f"{k:<8}{g[k]:>10.3f}{p[k]:>12.3f}{d[k]:>+10.3f}   "
            f"{'yes' if k in result['decisive'] else 'no'}"
        )
    lines.append(
        f"sanity check: {'PASS' if result['passed'] else 'FAIL'} "
        f"(tolerance {result['tolerance_m']:.3f} m on the decisive statistics; "
        f"identity is established by the SHA-256 in provenance.json, not here)"
    )
    return "\n".join(lines)


def correction_at(grid: GeoidGrid, lat, lon) -> np.ndarray:
    """Official BS-77 -> EVRF2019 correction (m), added to the Baltic height."""
    return grid.sample(np.atleast_1d(lat), np.atleast_1d(lon))


# --------------------------------------------------------------------------- #
# GeoTIFF export                                                               #
# --------------------------------------------------------------------------- #
def trim_to_valid(grid: GeoidGrid) -> GeoidGrid:
    """Drop the all-NODATA margin, keeping the model's actual domain."""
    ok = np.isfinite(grid.values)
    if not ok.any():
        return grid
    rows = np.where(ok.any(axis=1))[0]
    cols = np.where(ok.any(axis=0))[0]
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    return GeoidGrid(
        lats=grid.lats[r0:r1],
        lons=grid.lons[c0:c1],
        values=grid.values[r0:r1, c0:c1],
        crs=grid.crs,
    )


def resample_grid(grid: GeoidGrid, cell_deg: float) -> GeoidGrid:
    """Bilinear resample onto a finer/coarser regular lat/lon grid.

    Uses the same sampler as every other lookup in this project. Upsampling does
    **not** add information — the source is an IDW product at its native step —
    so callers must record that the output is interpolated.
    """
    lats = np.arange(grid.lats[0], grid.lats[-1] + cell_deg / 2, cell_deg)
    lons = np.arange(grid.lons[0], grid.lons[-1] + cell_deg / 2, cell_deg)
    LON, LAT = np.meshgrid(lons, lats)
    values = grid.sample(LAT.ravel(), LON.ravel()).reshape(LAT.shape)
    return GeoidGrid(lats=lats, lons=lons, values=values, crs=grid.crs)


def geotiff_metadata(cfg: Config, grid: GeoidGrid, *, resampled_from=None) -> dict:
    """GDAL metadata describing exactly what the raster means."""
    ot = cfg.official_transform
    stats = grid_statistics(grid)
    md = {
        "TITLE": "Baltic 1977 height to EVRF2019 height correction, Ukraine",
        "EPSG_OPERATION": str(ot.epsg_operation),
        "SOURCE_VERTICAL_CRS": "EPSG:5705 (Baltic 1977 height)",
        "TARGET_VERTICAL_CRS": f"EPSG:9389 ({ot.target_frame} height)",
        "TIDE_SYSTEM": ot.tide_system,
        "UNITS": "metre",
        "SIGN_CONVENTION":
            "ADD this value to a Baltic 1977 height to obtain the "
            f"{ot.target_frame} height",
        "SOURCE": ot.source,
        "SOURCE_URL": ot.source_url,
        "VALID_NODES": str(stats["n_nodes"]),
        "VALUE_MIN_M": f"{stats['min_m']:.4f}",
        "VALUE_MAX_M": f"{stats['max_m']:.4f}",
        "VALUE_MEAN_M": f"{stats['mean_m']:.4f}",
        "VALUE_SD_M": f"{stats['sd_m']:.4f}",
        "STATED_ACCURACY_M": str(ot.published_stats.get("accuracy_m", "")),
        "ACCURACY_NOTE":
            "STATED_ACCURACY_M is EPSG's operation-accuracy field, NOT a standard "
            "deviation and NOT a 95% CI. The same EPSG record separately reports "
            f"SD {ot.published_stats.get('sd_m', '')} m over "
            f"{ot.published_stats.get('n_determination_points', '?')} determination "
            "points. Do not relabel it as a sigma or combine it in quadrature.",
        "CELLSIZE_DEG": f"{float(grid.lons[1] - grid.lons[0]):.6f}",
        # --- PROJ vertical-offset grid tags -----------------------------------
        # These make the raster directly usable as
        #   +proj=vgridshift +grids=<this file> +multiplier=1
        # so PROJ can apply the same shift our sampler does. Without TYPE, PROJ
        # rejects the file with "could not find required grid(s)".
        "TYPE": "VERTICAL_OFFSET_VERTICAL_TO_VERTICAL",
        "source_crs_epsg_code": "5705",
        "target_crs_epsg_code": "9389",
        "area_of_use": "Ukraine",
        "recommended_interpolation_method": "bilinear",
    }
    if resampled_from is not None:
        md["RESAMPLED"] = (
            f"bilinear from native {resampled_from:.6f} deg — interpolated, "
            f"adds no information beyond the source IDW product"
        )
    return md


def to_geotiff(
    grid: GeoidGrid,
    path: str | Path,
    cfg: Config,
    *,
    dst_crs: str | None = None,
    nodata: float = -9999.0,
    dtype: str = "float32",
    metadata: dict | None = None,
    band_description: str = "vertical_offset",
    band_long_name: str = "BS-77 -> EVRF2019 correction (m)",
    overviews: bool = True,
) -> dict:
    """Write ``grid`` as a tiled, compressed GeoTIFF.

    The array is flipped to the north-up row order GeoTIFF expects. When
    ``dst_crs`` is given the raster is reprojected (bilinear) after writing the
    geographic version.

    ``band_description`` defaults to ``"vertical_offset"`` because **PROJ
    identifies the band of a vertical-offset grid by its description** and will
    refuse the file outright ("could not find required grid(s)") if it reads
    anything else — a prose description is enough to break it. The human-readable
    string lives in the ``LONG_NAME`` band tag instead.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    dx = float(grid.lons[1] - grid.lons[0])
    dy = float(grid.lats[1] - grid.lats[0])
    # Grid coordinates are cell centres; GeoTIFF origin is the outer NW corner.
    transform = from_origin(
        float(grid.lons[0]) - dx / 2.0, float(grid.lats[-1]) + dy / 2.0, dx, dy
    )
    data = np.flipud(grid.values).astype(dtype)
    data = np.where(np.isfinite(data), data, nodata).astype(dtype)

    profile = {
        "driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
        "count": 1, "dtype": dtype, "crs": grid.crs or "EPSG:4258",
        "transform": transform, "nodata": nodata,
        "tiled": True, "blockxsize": 256, "blockysize": 256,
        "compress": "deflate", "predictor": 3, "zlevel": 9,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
        dst.update_tags(**(metadata or geotiff_metadata(cfg, grid)))
        dst.set_band_description(1, band_description)
        # PROJ identifies the band of a vertical-offset grid by these tags.
        dst.update_tags(1, DESCRIPTION=band_description, UNITTYPE="metre",
                        LONG_NAME=band_long_name)
        if overviews and min(data.shape) >= 512:
            dst.build_overviews([2, 4, 8], Resampling.average)

    written = {"path": path, "shape": data.shape, "crs": profile["crs"],
               "cellsize_deg": dx, "nodata": nodata}

    if dst_crs:
        written["reprojected"] = _reproject_geotiff(
            path, dst_crs, nodata, dtype, band_description
        )
    return written


def _reproject_geotiff(
    src_path: Path, dst_crs: str, nodata: float, dtype: str,
    band_description: str = "BS-77 -> EVRF2019 correction (m)",
) -> Path:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import calculate_default_transform, reproject

    out = src_path.with_name(
        f"{src_path.stem}_{dst_crs.replace(':', '').lower()}{src_path.suffix}"
    )
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        profile = src.profile.copy()
        profile.update(crs=dst_crs, transform=transform, width=width, height=height,
                       nodata=nodata, dtype=dtype)
        tags = src.tags()
        with rasterio.open(out, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1), destination=rasterio.band(dst, 1),
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform, dst_crs=dst_crs,
                src_nodata=nodata, dst_nodata=nodata,
                resampling=Resampling.bilinear,
            )
            dst.update_tags(**tags)
            dst.set_band_description(1, band_description)
    return out


def clip_to_bbox(grid: GeoidGrid, bbox) -> GeoidGrid:
    """Clip to ``(lon_min, lat_min, lon_max, lat_max)``, keeping whole cells."""
    lon_min, lat_min, lon_max, lat_max = bbox
    ix = np.where((grid.lons >= lon_min) & (grid.lons <= lon_max))[0]
    iy = np.where((grid.lats >= lat_min) & (grid.lats <= lat_max))[0]
    if ix.size == 0 or iy.size == 0:
        raise ValueError(f"bbox {bbox} does not intersect the grid")
    return GeoidGrid(
        lats=grid.lats[iy], lons=grid.lons[ix],
        values=grid.values[np.ix_(iy, ix)], crs=grid.crs,
    )
