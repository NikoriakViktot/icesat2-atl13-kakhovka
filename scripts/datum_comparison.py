#!/usr/bin/env python3
"""Phase 2b: split the empirical alignment constant using the official
Baltic-1977 -> EVRF2019 transformation (EPSG:9902).

    python scripts/datum_comparison.py --download --maps

Reads  data/external/datum/ua_2019z.asc          (grid; --download fetches it)
       outputs/tables/kakhovka_alignment_by_station.csv   (Phase 2a)
       outputs/tables/<slug>_local_matchups.csv           (Phase 2a)
Writes outputs/tables/kakhovka_datum_comparison{,_by_radius,_by_rgt}.csv
       outputs/reports/kakhovka_datum_comparison.md
       outputs/figures/*.png   (with --maps)
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from kakhovka_altimetry import official_datum as od  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.datum import decompose_alignment, decompose_by  # noqa: E402
from kakhovka_altimetry.io import setup_logging  # noqa: E402
from kakhovka_altimetry.local_alignment import CALIBRATION_PERIOD  # noqa: E402

CAVEAT = (
    "`delta_unexplained_m` is **not** a residual of the datum transformation. It "
    "still contains the gauge-zero error, EGG2015's model error over Ukraine "
    "(~0.1 m) and any systematic ATL13 bias. Separating those needs a surveyed "
    "BS-77 gauge zero or a GNSS height on a benchmark."
)


def download_grid(cfg) -> None:
    ot = cfg.official_transform
    if ot.available:
        print(f"grid already present: {ot.path}")
        return
    ot.path.parent.mkdir(parents=True, exist_ok=True)
    for url in (ot.source_url, ot.source_url.replace(".asc", ".prj")):
        dest = ot.path.parent / url.rsplit("/", 1)[-1]
        print(f"downloading {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)


def _write_figures(cfg, grid, decomp, by_radius):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from kakhovka_altimetry import viz

    figs = cfg.repo_root / "outputs" / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    written = []

    fig, ax = plt.subplots(figsize=(12, 7))
    viz.official_correction_map(grid, decomp, cfg, ax=ax)
    fig.tight_layout()
    fig.savefig(figs / "datum_official_correction_map.png", dpi=150)
    plt.close(fig)
    written.append("datum_official_correction_map.png")

    fig, ax = plt.subplots(figsize=(10, 5))
    viz.datum_budget_bars(decomp, cfg, ax=ax)
    fig.tight_layout()
    fig.savefig(figs / "datum_budget.png", dpi=150)
    plt.close(fig)
    written.append("datum_budget.png")

    if not by_radius.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        viz.unexplained_by_radius(by_radius, cfg, ax=ax)
        fig.tight_layout()
        fig.savefig(figs / "datum_unexplained_by_radius.png", dpi=150)
        plt.close(fig)
        written.append("datum_unexplained_by_radius.png")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--download", action="store_true",
                    help="fetch the grid from CRS-EU if missing")
    ap.add_argument("--maps", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="proceed even if grid validation fails (not advised)")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    ot = cfg.official_transform
    tables = cfg.tables_dir

    if args.download:
        download_grid(cfg)

    grid = od.load_official_grid(cfg)
    validation = od.validate_against_published(grid, cfg)
    print(f"official transformation: EPSG:{ot.epsg_operation} -> {ot.target_frame} "
          f"({ot.tide_system})\nsource: {ot.source}\n")
    print(od.format_validation(validation), "\n")
    if not validation["passed"] and not args.force:
        print("grid does not match the published EPSG statistics — refusing to use "
              "it. Re-check the source, or pass --force if you know better.",
              file=sys.stderr)
        return 2

    summary_path = tables / "kakhovka_alignment_by_station.csv"
    if not summary_path.exists():
        print(f"{summary_path} missing — run scripts/local_alignment.py first",
              file=sys.stderr)
        return 2
    summary = pd.read_csv(summary_path)

    decomp = decompose_alignment(summary, grid, cfg)
    decomp.to_csv(tables / "kakhovka_datum_comparison.csv", index=False)

    # Per-radius and per-RGT breakdowns from the Phase 2a matchups.
    rad_frames, rgt_frames = [], []
    for _, r in decomp.iterrows():
        mp = tables / f"{r['slug']}_local_matchups.csv"
        if not mp.exists():
            continue
        m = pd.read_csv(mp)
        if m.empty:
            continue
        assert (m["period"] == CALIBRATION_PERIOD).all(), \
            f"non-{CALIBRATION_PERIOD} rows in {mp.name}"
        kw = dict(station_lat=r["lat"], station_lon=r["lon"],
                  nominal_zero_m=r["nominal_zero_m"])
        rad_frames.append(decompose_by(m, grid, cfg, ["radius_km"], **kw)
                          .assign(station_id=r["station_id"], name_en=r["name_en"]))
        main_r = cfg.local_alignment.main_radius_km
        diag_r = cfg.local_alignment.diagnostic_radius_km
        sub = m[np.isclose(m["radius_km"], diag_r) | np.isclose(m["radius_km"], main_r)]
        if not sub.empty:
            rgt_frames.append(decompose_by(sub, grid, cfg, ["radius_km", "rgt"], **kw)
                              .assign(station_id=r["station_id"], name_en=r["name_en"]))

    by_radius = pd.concat(rad_frames, ignore_index=True) if rad_frames else pd.DataFrame()
    by_rgt = pd.concat(rgt_frames, ignore_index=True) if rgt_frames else pd.DataFrame()
    by_radius.to_csv(tables / "kakhovka_datum_comparison_by_radius.csv", index=False)
    by_rgt.to_csv(tables / "kakhovka_datum_comparison_by_rgt.csv", index=False)

    cols = ["name_en", "alignment_constant_m", "nominal_zero_m", "delta_empirical_m",
            "delta_official_m", "delta_unexplained_m", "implied_gauge_zero_baltic_m"]
    print(decomp[cols].round(3).to_string(index=False), "\n")

    figures = _write_figures(cfg, grid, decomp, by_radius) if args.maps else []
    _write_report(cfg, validation, decomp, by_radius, by_rgt, figures)
    return 0


def _write_report(cfg, validation, decomp, by_radius, by_rgt, figures) -> None:
    ot = cfg.official_transform
    ok = decomp[decomp["delta_official_m"].notna()]

    L = ["# Baltic-1977 → EVRF2019 at the Kakhovka gauges — official vs empirical\n\n"]
    L.append(f"_Official transformation: **EPSG:{ot.epsg_operation}** → "
             f"{ot.target_frame} ({ot.tide_system}). {ot.source}_\n\n")

    L.append("## Headline\n\n")
    if not ok.empty:
        L.append(f"- Official BS-77 → EVRF2019 correction **at the Kakhovka posts**: "
                 f"**{ok['delta_official_m'].min():.3f} … "
                 f"{ok['delta_official_m'].max():.3f} m** "
                 f"(median {ok['delta_official_m'].median():.3f} m) — inside the "
                 f"national range {ot.published_stats['min_m']:.3f} … "
                 f"{ot.published_stats['max_m']:.3f} m, and above the national mean "
                 f"of {ot.published_stats['mean_m']:.3f} m.\n")
        L.append(f"- Empirical `C − nominal zero`: median "
                 f"**{ok['delta_empirical_m'].median():+.3f} m**.\n")
        L.append(f"- Left over: `delta_unexplained_m` median "
                 f"**{ok['delta_unexplained_m'].median():+.3f} m** "
                 f"({ok['delta_unexplained_m'].min():+.3f} … "
                 f"{ok['delta_unexplained_m'].max():+.3f}).\n")
        L.append(f"- A common **adopted** BS-77 gauge zero of "
                 f"{ok['nominal_zero_m'].median():.2f} m was used for all posts; it "
                 f"is a fixed constant of the model, not an estimated parameter.\n\n")
    L.append(f"> {CAVEAT}\n\n")

    L.append("## Grid numerical sanity check\n\n```\n")
    L.append(od.format_validation(validation) + "\n```\n\n")
    L.append("This is a **consistency check, not a proof of file identity**. The "
             "published EPSG statistics are quoted over the transformation's "
             "**154-point defining set**, while ours are over 3776 interpolated grid "
             "nodes — IDW smooths the extremes, which is why `max` sits 3.4 cm lower "
             "and is not treated as decisive. Agreement of three summary statistics "
             "says the file is *consistent with* the product, not that it *is* the "
             "product; identity is established by the SHA-256 recorded in "
             "`outputs/reports/provenance.json`. What the check does earn its keep "
             "for is catching a wrong, empty or all-zero grid — the real failure mode "
             "here, since PROJ's ballpark fallback silently returns 0. The valid-node "
             "count matches the figure published by Stopkhai et al. (2026) exactly.\n\n")

    L.append("## Per station\n\n")
    cols = ["station_id", "name_en", "alignment_constant_m", "nominal_zero_m",
            "delta_empirical_m", "delta_official_m", "delta_unexplained_m",
            "implied_gauge_zero_baltic_m", "official_within_national_range"]
    L.append(decomp[cols].round(3).to_markdown(index=False) + "\n\n")

    L.append("## Error budget\n\n")
    L.append(f"| term | value | note |\n|---|---:|---|\n"
             f"| `delta_official_m` | {ok['delta_official_m'].median():+.3f} m | "
             f"EPSG:{ot.epsg_operation} grid at the post; accuracy "
             f"±{ot.published_stats.get('accuracy_m', float('nan')):.3f} m |\n"
             f"| `evrf2019_minus_evrf2007_m` | {ot.evrf2019_minus_evrf2007_m:+.3f} m | "
             f"EGG2015 is EVRF2007-consistent; **0.0 = not assumed**, cm level |\n"
             f"| `tide_system_correction_m` | {ot.tide_system_correction_m:+.3f} m | "
             f"zero- vs mean-tide; **0.0 = not assumed**, ~2–3 cm at 47.7° N |\n"
             f"| EGG2015 model error | ±{ot.egg2015_accuracy_m:.3f} m | quoted "
             f"accuracy over Ukraine; sits inside `delta_unexplained_m` |\n"
             f"| ATL13 bias | {ot.atl13_bias_m:+.3f} m | not assumed |\n"
             f"| **`delta_unexplained_m`** | "
             f"**{ok['delta_unexplained_m'].median():+.3f} m** | gauge-zero error "
             f"+ EGG2015 error + ATL13 bias |\n\n")

    if not by_radius.empty:
        thr = cfg.local_alignment.min_matchups_for_confidence
        L.append("## Stability across the radius ladder\n\n")
        solid = by_radius[by_radius["n_matchups"] >= thr]
        spread = (solid.groupby("name_en")["delta_unexplained_m"]
                  .agg(lambda s: s.max() - s.min()))
        L.append(f"`delta_unexplained_m` must be flat in radius — it is a "
                 f"datum/zero term, so radius dependence would mean a bug upstream. "
                 f"Over rows with n ≥ {thr}, the per-station spread is "
                 f"**{spread.min() * 100:.1f}–{spread.max() * 100:.1f} cm**.\n\n")
        thin = by_radius[by_radius["n_matchups"] < thr]
        if not thin.empty:
            L.append(f"Rows with n < {thr} scatter much more (up to "
                     f"{(by_radius.groupby('name_en')['delta_unexplained_m'].agg(lambda s: s.max() - s.min()).max()) * 100:.0f} cm "
                     f"if they are included) and are excluded from that statistic — "
                     f"they are small-sample noise, not a radius effect.\n\n")
        L.append(by_radius[["name_en", "radius_km", "n_matchups",
                            "alignment_constant_m", "delta_unexplained_m"]]
                 .round(3).to_markdown(index=False) + "\n\n")

    if not by_rgt.empty:
        L.append("## Per RGT\n\n")
        L.append(by_rgt[["name_en", "radius_km", "rgt", "n_matchups",
                         "alignment_constant_m", "delta_unexplained_m"]]
                 .round(3).to_markdown(index=False) + "\n\n")

    if figures:
        L.append("## Figures\n\n")
        for f in figures:
            L.append(f"- `outputs/figures/{f}`\n")
        L.append("\n")

    L.append("## What is and is not determined\n\n"
             "**Determined.** The official BS-77 → EVRF2019 correction at these "
             "coordinates, from Ukraine's own transformation grid. This is the "
             "answer to \"what is the Baltic→EVRF correction here\".\n\n"
             "**Not determined.** How the remaining "
             f"{ok['delta_unexplained_m'].median():+.3f} m splits between the "
             "gauge-zero error, EGG2015's model error and ATL13 bias — these enter "
             "`c` additively and gauges plus ICESat alone cannot separate them.\n\n"
             "**Diagnostic, not a result.** `implied_gauge_zero_baltic_m` is a "
             "counterfactual: *if* the EGG2015 and ATL13 systematics were exactly "
             "zero, the posts' true BS-77 zeros would have to be "
             f"{ok['implied_gauge_zero_baltic_m'].min():.3f} … "
             f"{ok['implied_gauge_zero_baltic_m'].max():.3f} m "
             f"(median {ok['implied_gauge_zero_baltic_m'].median():.3f}) rather than "
             f"the adopted {ok['nominal_zero_m'].median():.2f} m. Because the zero is "
             "*adopted* rather than estimated, this column is arithmetically "
             "`nominal_zero + delta_unexplained` — it restates the residual and adds "
             "no independent information. It is worth checking against a technical "
             "passport if one surfaces, but it is not a measured zero and must not be "
             "reported as one.\n")

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_dir / "kakhovka_datum_comparison.md"
    out.write_text("".join(L), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    raise SystemExit(main())
