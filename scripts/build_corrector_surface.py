#!/usr/bin/env python3
"""Phase 2d: nearest-station EGG2015 -> EVRF2019 corrector surface (Variant A).

    python scripts/build_corrector_surface.py
    python scripts/build_corrector_surface.py --cell-deg 0.01 --no-rasters

Turns the six Phase 2c ``c_station`` point estimates
(``outputs/tables/egg2015_to_evrf2019_by_station.csv``) into a Voronoi
(nearest-station) lookup: every ATL13 segment and pass gets its own
``egg2015_to_evrf2019_corrector_m``, ``corrector_uncertainty_m``,
``nearest_control_station`` and ``distance_to_control_km``, plus
``h_evrf2019_empirical_m = H_evrs_egg2015_m + corrector_m``.

This is an **empirical, ATL13/gauge-constrained corrector surface**, not an
official geodetic transformation and not a new quasigeoid -- see
:mod:`kakhovka_altimetry.corrector_surface` and
``outputs/reports/egg2015_to_evrf2019_gauge_experiment.md``.

Reads  outputs/tables/egg2015_to_evrf2019_by_station.csv
       data/processed/kakhovka_atl13_evrs.parquet
       data/processed/kakhovka_atl13_pass_levels.parquet
Writes data/processed/kakhovka_atl13_evrf2019_empirical.parquet   (segment-level)
       outputs/tables/atl13_pass_levels_evrf2019_empirical.csv    (pass-level)
       outputs/rasters/kakhovka_egg2015_to_evrf2019_corrector.tif
       outputs/rasters/kakhovka_egg2015_to_evrf2019_corrector_uncertainty.tif
       outputs/reports/kakhovka_corrector_surface.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kakhovka_altimetry import corrector_surface as cs  # noqa: E402
from kakhovka_altimetry import official_datum as od  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.io import read_parquet, setup_logging, write_parquet  # noqa: E402

CORRECTOR_TIF = "kakhovka_egg2015_to_evrf2019_corrector.tif"
UNCERTAINTY_TIF = "kakhovka_egg2015_to_evrf2019_corrector_uncertainty.tif"


def _write_report(cfg, stations, seg_out, pass_out, raster_paths, seg_dist_max) -> Path:
    L: list[str] = []
    L.append("# Kakhovka EGG2015 -> EVRF2019 corrector surface (Phase 2d)\n\n")
    L.append(
        "> **Empirical, ATL13/gauge-constrained corrector surface.** Not an "
        "official geodetic transformation, not a new quasigeoid. Each cell's "
        "value is exactly one of the six Phase 2c `c_station` numbers, "
        "assigned by nearest-station (Voronoi) lookup -- see "
        "`outputs/reports/egg2015_to_evrf2019_gauge_experiment.md` for what "
        "`c_station` does and does not measure.\n\n"
    )
    L.append("## Method\n\n```\n"
             "H_ATL13,EVRF2019_empirical = H_EGG2015 + c(x,y)\n"
             "H_EGG2015 = ht_water_surf - zeta_EGG2015\n"
             "c(x,y) = c_station of the nearest of the 6 control gauges\n"
             "```\n\n"
             "Nearest-station, not IDW or a plane fit: with 6 stations -- one "
             "(Rozumivka) bimodal by RGT, another (Velyka Lepetykha) at only "
             "5 independent beam-passes -- a smooth surface would blend an "
             "unreliable station's value into its neighbours. "
             "`distance_to_control_km` is carried on every row so confidence "
             "can be judged per point; there is no hard distance cutoff "
             "beyond the reservoir AOI bbox itself.\n\n")

    L.append("## Control stations\n\n")
    cols = ["name_en", "slug", "lat", "lon", "c_station_m", "sigma_m",
            "reported_radius_km", "n_matchups", "flag"]
    L.append(stations[cols].round(4).to_markdown(index=False) + "\n\n")

    L.append("## Outputs\n\n")
    L.append(f"- `{seg_out}` -- {pass_out[1]:,} ATL13 segments, all periods, "
             f"columns added: `{'`, `'.join(cs.CORRECTOR_COLUMNS)}`, "
             f"`h_evrf2019_empirical_m`.\n")
    L.append(f"- `{pass_out[0]}` -- {pass_out[2]:,} beam-passes, same columns "
             f"applied to `median_wse_evrs_m`.\n")
    for label, p in raster_paths.items():
        L.append(f"- `{p}` -- {label}.\n")
    L.append("\n")

    L.append("## Caveats (inherited from Phase 2c, unchanged by this step)\n\n")
    L.append("- The corrector is calibrated on **PRE_BREACH matchups only**; "
             "applying it to BREACH_DRAWDOWN/POST_BREACH rows assumes the "
             "local EGG2015/ATL13 systematic terms it absorbs do not depend "
             "on reservoir stage. Not tested.\n")
    L.append("- `corrector_uncertainty_m` is beam-pass NMAD (repeatability) "
             "at the nearest station only. It does **not** include the "
             "EPSG:9902 published operation accuracy (0.068 m — an "
             "operation-accuracy field, not a standard deviation), the "
             "unresolved gauge-zero error, or the EGG2015 model error -- see "
             "`outputs/tables/egg2015_to_evrf2019_uncertainty.csv`.\n")
    L.append("- The raster is built only over the reservoir AOI bbox "
             f"`{cfg.aoi_bbox}` and must not be sampled outside it -- these "
             "6 gauges are not a basin-wide, let alone national, corrector.\n")
    L.append("- Every station here is thin (5-12 independent beam-passes, "
             "2020-2021 only except Rozumivka). Treat the whole surface as "
             "provisional.\n")
    max_d = float(seg_dist_max)
    L.append(f"- The reservoir spans ~130 km but has only 6 unevenly spaced "
             f"gauges: some segments are up to **{max_d:.0f} km** from their "
             f"nearest control station (see `distance_to_control_km` per row, "
             f"or the per-station breakdown printed by this script) -- this "
             f"is Voronoi *assignment*, not a claim that the corrector is "
             f"still accurate that far out.\n\n")

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_dir / "kakhovka_corrector_surface.md"
    out.write_text("".join(L), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell-deg", type=float, default=0.005,
                    help="raster cell size, degrees (default 0.005 ~ 500 m)")
    ap.add_argument("--no-rasters", action="store_true", help="skip GeoTIFF export")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()

    stations = cs.load_station_correctors(cfg)
    print(f"{len(stations)} control stations:\n"
          + stations[["name_en", "slug", "c_station_m", "sigma_m", "flag"]]
          .round(4).to_string(index=False))

    evrs = read_parquet(cfg.evrs_parquet)
    seg = cs.augment_points(evrs, stations)
    seg_path = cfg.processed_dir / "kakhovka_atl13_evrf2019_empirical.parquet"
    write_parquet(seg, seg_path, label="atl13_evrf2019_empirical")

    passes = read_parquet(cfg.pass_levels_parquet)
    pl = cs.augment_points(
        passes, stations, lat_col="lat_mean", lon_col="lon_mean",
        level_col="median_wse_evrs_m",
    )
    pass_path = cfg.tables_dir / "atl13_pass_levels_evrf2019_empirical.csv"
    cfg.tables_dir.mkdir(parents=True, exist_ok=True)
    pl.to_csv(pass_path, index=False)
    print(f"wrote {pass_path} ({len(pl)} rows)")

    print("\nby control station, applied to all rows:\n",
          seg.groupby("nearest_control_station").agg(
              n_segments=("egg2015_to_evrf2019_corrector_m", "size"),
              corrector_m=("egg2015_to_evrf2019_corrector_m", "first"),
              mean_distance_km=("distance_to_control_km", "mean"),
              max_distance_km=("distance_to_control_km", "max"),
          ).round(3).to_string())

    raster_paths: dict[str, Path] = {}
    if not args.no_rasters:
        corrector_grid, uncertainty_grid = cs.build_corrector_grid(
            cfg, stations, cell_deg=args.cell_deg
        )
        rasters_dir = cfg.repo_root / "outputs" / "rasters"
        c_path = rasters_dir / CORRECTOR_TIF
        u_path = rasters_dir / UNCERTAINTY_TIF
        od.to_geotiff(
            corrector_grid, c_path, cfg,
            metadata=cs.corrector_geotiff_metadata(stations),
            band_description="empirical EGG2015 -> EVRF2019 corrector c(x,y) (m)",
            overviews=False,
        )
        od.to_geotiff(
            uncertainty_grid, u_path, cfg,
            metadata=cs.uncertainty_geotiff_metadata(stations),
            band_description="corrector empirical precision, NMAD (m)",
            overviews=False,
        )
        print(f"\nwrote {c_path}\nwrote {u_path}")
        raster_paths = {
            "corrector c(x,y), metres, ADD to H_EGG2015": c_path.relative_to(cfg.repo_root),
            "corrector empirical precision (NMAD), metres": u_path.relative_to(cfg.repo_root),
        }

    report = _write_report(
        cfg, stations,
        seg_path.relative_to(cfg.repo_root),
        (pass_path.relative_to(cfg.repo_root), len(seg), len(pl)),
        raster_paths,
        seg["distance_to_control_km"].max(),
    )
    print(f"\nwrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
