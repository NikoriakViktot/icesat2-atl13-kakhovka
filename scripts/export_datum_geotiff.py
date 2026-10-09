#!/usr/bin/env python3
"""Export the official Baltic-1977 -> EVRF2019 correction for Ukraine as a GeoTIFF.

    python scripts/export_datum_geotiff.py                      # full box, 0.15 deg
    python scripts/export_datum_geotiff.py --cell-deg 0.05      # bilinear resample
    python scripts/export_datum_geotiff.py --dst-crs EPSG:6381  # + projected copy
    python scripts/export_datum_geotiff.py --extent ukraine     # Ukraine bbox
    python scripts/export_datum_geotiff.py --extent data        # shrink-wrapped

Source: EPSG:9902 grid (`ua_2019z.asc`), published by CRS-EU as
"UA_KRON/NH to EVRF2019zero". Target frame **EVRF2019, zero-tide**.

Sign: the raster value is **ADDED** to a Baltic 1977 height to obtain the EVRF2019
height. The value is metres.

The grid is sanity-checked against the published EPSG:9902 statistics before
anything is written. PROJ *defines* EPSG:9902 but ships no grid for it, so the
operation it can actually offer between these two CRSs degrades to a ballpark
``proj=noop`` — a silent zero is a real failure mode here, and the check catches it.

The written raster carries PROJ's vertical-offset grid tags (``TYPE``, band
description ``vertical_offset``), so once exported it can be handed straight back
to PROJ as ``+proj=vgridshift +grids=<this file> +multiplier=1``. That is what
``tests/test_official_datum.py`` uses to cross-check our own sampler.

Writes outputs/rasters/ua_bs77_to_evrf2019z.tif (+ a reprojected copy with
--dst-crs) and outputs/figures/datum_ukraine_geotiff.png with --preview.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from kakhovka_altimetry import official_datum as od  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.io import setup_logging  # noqa: E402

DEFAULT_NAME = "ua_bs77_to_evrf2019z.tif"
# Ukraine bounding box (lon_min, lat_min, lon_max, lat_max), Crimea included.
# Deliberately a touch wider than the country so it never clips the grid's own
# valid extent (lon 22.001..40.301, lat 44.338..52.438).
UKRAINE_BBOX = (21.9, 44.2, 40.4, 52.5)


def _preview(path: Path, cfg, out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio

    with rasterio.open(path) as ds:
        a = ds.read(1, masked=True)
        b = ds.bounds
        tags = ds.tags()

    fig, ax = plt.subplots(figsize=(12, 7))
    im = ax.imshow(a, extent=(b.left, b.right, b.bottom, b.top), origin="upper",
                   cmap="viridis")
    plt.colorbar(im, ax=ax, label="BS-77 → EVRF2019 correction (m)", shrink=0.85)
    cs = ax.contour(np.linspace(b.left, b.right, a.shape[1]),
                    np.linspace(b.top, b.bottom, a.shape[0]), a,
                    colors="w", linewidths=0.6, alpha=0.75)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%.2f")

    for st in cfg.gauges.stations:
        if st.complete:
            ax.plot(st.lon, st.lat, "o", ms=5, mfc="red", mec="white", mew=1.0,
                    zorder=6)
    ax.set_aspect(1.0 / np.cos(np.radians((b.bottom + b.top) / 2)))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"EPSG:{tags.get('EPSG_OPERATION', '9902')} — Baltic 1977 → "
                 f"{tags.get('TARGET_VERTICAL_CRS', 'EVRF2019')} "
                 f"({tags.get('TIDE_SYSTEM', 'zero-tide')}), Ukraine")
    ax.grid(alpha=0.15)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--cell-deg", type=float, default=None,
                    help="resample to this cell size (default: native)")
    ap.add_argument("--dst-crs", type=str, default=None,
                    help="also write a copy reprojected to this CRS")
    ap.add_argument("--extent", choices=("source", "ukraine", "data"),
                    default="source",
                    help="raster footprint: 'source' = the full uncropped grid box "
                         "(default), 'ukraine' = Ukraine's bounding box, "
                         "'data' = shrink-wrapped to the valid cells. All three "
                         "hold identical values — only the NODATA margin differs.")
    ap.add_argument("--preview", action="store_true", help="render a PNG preview")
    ap.add_argument("--force", action="store_true",
                    help="write even if grid validation fails (not advised)")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    ot = cfg.official_transform

    grid = od.load_official_grid(cfg)
    validation = od.validate_against_published(grid, cfg)
    print(f"source: {ot.source}\n{od.format_validation(validation)}\n")
    if not validation["passed"] and not args.force:
        print("grid does not match the published EPSG:9902 statistics — refusing "
              "to export. Re-check the source, or pass --force.", file=sys.stderr)
        return 2

    native_cell = float(grid.lons[1] - grid.lons[0])
    n_valid_before = int(np.isfinite(grid.values).sum())
    if args.extent == "data":
        before = grid.values.shape
        grid = od.trim_to_valid(grid)
        print(f"extent 'data': shrink-wrapped {before} -> {grid.values.shape}")
    elif args.extent == "ukraine":
        before = grid.values.shape
        grid = od.clip_to_bbox(grid, UKRAINE_BBOX)
        print(f"extent 'ukraine': {before} -> {grid.values.shape} "
              f"(bbox {UKRAINE_BBOX})")
    else:
        print(f"extent 'source': full uncropped grid box {grid.values.shape}")
    n_valid = int(np.isfinite(grid.values).sum())
    if n_valid != n_valid_before:
        print(f"  NOTE: {n_valid_before - n_valid} valid cells fell outside this "
              f"extent ({n_valid_before} -> {n_valid})")
    else:
        print(f"  all {n_valid} valid cells retained — the extent choice only "
              f"changes the NODATA margin")

    resampled_from = None
    if args.cell_deg:
        grid = od.resample_grid(grid, args.cell_deg)
        resampled_from = native_cell
        print(f"resampled {native_cell:g} -> {args.cell_deg:g} deg "
              f"(bilinear; adds no information)")

    out = args.output or (cfg.repo_root / "outputs" / "rasters" / DEFAULT_NAME)
    md = od.geotiff_metadata(cfg, grid, resampled_from=resampled_from)
    written = od.to_geotiff(grid, out, cfg, dst_crs=args.dst_crs, metadata=md)

    print(f"\nwrote {written['path']}")
    print(f"  shape {written['shape']}  crs {written['crs']}  "
          f"cell {written['cellsize_deg']:.4f} deg  nodata {written['nodata']}")
    if "reprojected" in written:
        print(f"  reprojected copy: {written['reprojected']}")

    # Read back and prove the raster says what we think it says.
    import rasterio
    with rasterio.open(written["path"]) as ds:
        a = ds.read(1, masked=True)
        print(f"\nread-back: {a.count()} valid cells, "
              f"{a.min():.3f} … {a.max():.3f} m, mean {a.mean():.3f}")
        print(f"  bounds lon {ds.bounds.left:.3f}..{ds.bounds.right:.3f}  "
              f"lat {ds.bounds.bottom:.3f}..{ds.bounds.top:.3f}")
        print(f"  sign: {ds.tags()['SIGN_CONVENTION']}")
        # spot-check against the source grid at the gauges
        src = od.load_official_grid(cfg)
        rows = []
        for st in cfg.gauges.stations:
            if not st.complete:
                continue
            ref = float(od.correction_at(src, st.lat, st.lon)[0])
            got = float(next(ds.sample([(st.lon, st.lat)]))[0])
            rows.append((st.name_en, ref, got, got - ref))
        print("\n  raster vs source grid at the gauges (m):")
        for name, ref, got, d in rows:
            print(f"    {name:<18} source {ref:+.4f}  raster {got:+.4f}  Δ {d:+.4f}")
        worst = max(abs(d) for *_, d in rows) if rows else 0.0
        # nearest-neighbour read-back of a bilinear source differs by ~half a cell
        print(f"  max |Δ| = {worst:.4f} m "
              f"(nearest-neighbour sampling of a {written['cellsize_deg']:g}° cell)")

    if args.preview:
        png = cfg.repo_root / "outputs" / "figures" / "datum_ukraine_geotiff.png"
        _preview(written["path"], cfg, png)
        print(f"\npreview: {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
