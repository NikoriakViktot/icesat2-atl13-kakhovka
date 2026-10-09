#!/usr/bin/env python3
"""Phase 2a: local vertical alignment between gauges and ICESat-2/EGG2015.

    python scripts/local_alignment.py                    # all configured stations
    python scripts/local_alignment.py --station 80959    # one station
    python scripts/local_alignment.py --radii 0.5,1,2,3,5 --main 2 --maps

Reads  data/processed/kakhovka_atl13_evrs.parquet   (point-level, NOT pass levels)
       data/processed/kakhovka_atl13_pass_levels.parquet   (reservoir reference)
       gauge stage series via config/gauges.yaml
Writes outputs/tables/<slug>_{local_matchups,alignment_by_radius,alignment_by_rgt}.csv
       outputs/tables/kakhovka_alignment_by_station.csv
       outputs/reports/kakhovka_local_alignment.md
       outputs/figures/*.png   (with --maps)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.gauges import load_gauge_observations  # noqa: E402
from kakhovka_altimetry.io import read_parquet, setup_logging  # noqa: E402
from kakhovka_altimetry.local_alignment import (  # noqa: E402
    CALIBRATION_PERIOD,
    STATION_SUMMARY_COLUMNS,
    per_rgt,
    radius_ladder,
    station_summary,
)

CAVEAT = (
    "`alignment_constant_m` is the **empirical vertical alignment constant** between "
    "gauge stage and ICESat-2/EGG2015 water-surface elevations. It incorporates the "
    "gauge zero elevation, the Baltic-1977 → EVRS datum difference, and any "
    "systematic ICESat-2 / vertical-model bias, and therefore **must not** be "
    "interpreted as a pure Baltic-to-EVRS transformation."
)


def run_station(station, evrs, obs, reservoir, cfg, radii, main_r, diag_r):
    o = obs[obs["station_id"] == station.id]
    if o.empty:
        return None
    ladder, matchups = radius_ladder(
        evrs, o, station, cfg, radii=radii, reservoir_passes=reservoir
    )
    if not matchups.empty:
        assert (matchups["period"] == CALIBRATION_PERIOD).all(), \
            f"non-{CALIBRATION_PERIOD} rows leaked into {station.id} matchups"
    rgt = pd.concat(
        [per_rgt(matchups, main_r), per_rgt(matchups, diag_r)], ignore_index=True
    )
    return {
        "station": station, "obs": o, "ladder": ladder,
        "matchups": matchups, "rgt": rgt,
        "summary": station_summary(station, ladder, cfg),
    }


def _write_maps(results, evrs, summary, cfg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from kakhovka_altimetry import viz

    figs = cfg.repo_root / "outputs" / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    written = []

    fig, ax = plt.subplots(figsize=(13, 7))
    viz.overview_map(evrs, cfg, ax=ax)
    fig.tight_layout()
    fig.savefig(figs / "map_overview.png", dpi=150)
    plt.close(fig)
    written.append("map_overview.png")

    fig = viz.station_panel(evrs, cfg)
    fig.savefig(figs / "map_stations.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    written.append("map_stations.png")

    fig, ax = plt.subplots(figsize=(13, 7))
    viz.alignment_map(summary, evrs, cfg, ax=ax)
    fig.tight_layout()
    fig.savefig(figs / "map_alignment.png", dpi=150)
    plt.close(fig)
    written.append("map_alignment.png")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    viz.longitudinal_profile(summary, ax=ax)
    fig.tight_layout()
    fig.savefig(figs / "alignment_longitudinal.png", dpi=150)
    plt.close(fig)
    written.append("alignment_longitudinal.png")

    ladders = {r["station"].name_en: r["ladder"] for r in results
               if r["ladder"]["n_matchups"].sum() > 0}
    if ladders:
        fig, ax = plt.subplots(figsize=(9, 5))
        viz.radius_stability(ladders, cfg, ax=ax)
        fig.tight_layout()
        fig.savefig(figs / "alignment_radius_stability.png", dpi=150)
        plt.close(fig)
        written.append("alignment_radius_stability.png")

    for r in results:
        if r["matchups"].empty:
            continue
        rep = r["summary"]["reported_radius_km"]
        m = r["matchups"][np.isclose(r["matchups"]["radius_km"], rep)] \
            if np.isfinite(rep) else r["matchups"]
        if m.empty:
            continue
        fig, ax = plt.subplots(figsize=(6, 5.5))
        viz.gauge_vs_icesat(m, r["station"], ax=ax)
        name = f"scatter_{r['station'].slug}.png"
        fig.tight_layout()
        fig.savefig(figs / name, dpi=150)
        plt.close(fig)
        written.append(name)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station", type=str, default="all",
                    help="'all' or comma-separated post ids")
    ap.add_argument("--radii", type=str, default=None, help="comma-separated km")
    ap.add_argument("--main", type=float, default=None)
    ap.add_argument("--diagnostic-radius", type=float, default=None)
    ap.add_argument("--maps", action="store_true", help="also render figures")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    la = cfg.local_alignment

    if args.station == "all":
        stations = [s for s in cfg.gauges.stations if s.complete]
    else:
        ids = [int(x) for x in args.station.split(",")]
        stations = [cfg.gauges.station(i) for i in ids]

    radii = tuple(float(x) for x in args.radii.split(",")) if args.radii else la.radii_km
    main_r = args.main or la.main_radius_km
    diag_r = args.diagnostic_radius or la.diagnostic_radius_km
    all_radii = tuple(sorted({*radii, main_r, diag_r}))

    evrs = read_parquet(cfg.evrs_parquet)
    try:
        reservoir = read_parquet(cfg.pass_levels_parquet)
    except FileNotFoundError:
        reservoir = None
    obs = load_gauge_observations(cfg)

    print(f"calibration period: {CALIBRATION_PERIOD} only | "
          f"main radius {main_r:g} km | diagnostic {diag_r:g} km\n")

    tables = cfg.tables_dir
    tables.mkdir(parents=True, exist_ok=True)

    results = []
    for st in stations:
        r = run_station(st, evrs, obs, reservoir, cfg, all_radii, main_r, diag_r)
        if r is None:
            print(f"{st.id} {st.name_en}: no gauge observations — skipped")
            continue
        results.append(r)
        r["matchups"].to_csv(tables / f"{st.slug}_local_matchups.csv", index=False)
        r["ladder"].to_csv(tables / f"{st.slug}_alignment_by_radius.csv", index=False)
        r["rgt"].to_csv(tables / f"{st.slug}_alignment_by_rgt.csv", index=False)
        s = r["summary"]
        head = (f"C = {s['alignment_constant_m']:.3f} m @ {s['reported_radius_km']:g} km "
                f"(n={s['n_reported']}, NMAD {s['nmad_m']:.3f})"
                if np.isfinite(s["alignment_constant_m"]) else "no usable tie")
        print(f"{st.id} {st.name_en:<18} {head}"
              + (f"  [{s['note']}]" if s["note"] else ""))

    if not results:
        print("nothing to do", file=sys.stderr)
        return 2

    summary = pd.DataFrame([r["summary"] for r in results],
                           columns=STATION_SUMMARY_COLUMNS)
    summary = summary.sort_values("distance_from_dam_km").reset_index(drop=True)
    summary.to_csv(tables / "kakhovka_alignment_by_station.csv", index=False)

    figures = _write_maps(results, evrs, summary, cfg) if args.maps else []

    _write_report(results, summary, cfg, main_r, diag_r, figures)
    return 0


def _write_report(results, summary, cfg, main_r, diag_r, figures) -> None:
    la = cfg.local_alignment
    ok = summary[summary["alignment_constant_m"].notna()]

    L = ["# Local vertical alignment at the Kakhovka reservoir gauges\n\n"]
    L.append(f"_ATL13 point-level EVRS within a radius of each post, "
             f"`{CALIBRATION_PERIOD}` only, matched to that post's stage series._\n\n")
    L.append(f"> {CAVEAT}\n\n")

    L.append("## Result per station\n\n")
    cols = ["station_id", "name_en", "distance_from_dam_km", "reported_radius_km",
            "n_reported", "alignment_constant_m", "nmad_m", "ci95_low_m",
            "ci95_high_m", "evrs_minus_bs77_m", "note"]
    L.append(summary[cols].round(3).to_markdown(index=False) + "\n\n")

    if len(ok) > 1:
        spread = float(ok["alignment_constant_m"].max() - ok["alignment_constant_m"].min())
        pooled = float(np.median(ok["alignment_constant_m"]))
        L.append(f"Across the {len(ok)} posts with a usable tie the constant spans "
                 f"**{spread * 100:.0f} cm** (median {pooled:.3f} m). "
                 f"Every post carries the same *nominal* 12.00 m BS-77 zero, and the "
                 f"pool is quasi-horizontal, so this spread is essentially the "
                 f"**relative error between the posts' true gauge zeros** — not a "
                 f"water-surface gradient.\n\n")

    L.append("## Sensitivity to radius, per station\n\n")
    for r in results:
        st, ladder = r["station"], r["ladder"]
        L.append(f"### {st.name} / {st.name_en} ({st.id})\n\n")
        gauge = r["obs"]
        L.append(f"Gauge {gauge['datetime'].min().date()} → "
                 f"{gauge['datetime'].max().date()} ({len(gauge)} readings). ")
        s = r["summary"]
        if np.isfinite(s["alignment_constant_m"]):
            L.append(f"**alignment_constant_m = {s['alignment_constant_m']:.3f} m** "
                     f"at {s['reported_radius_km']:g} km "
                     f"(n = {s['n_reported']}, NMAD {s['nmad_m']:.3f} m).\n\n")
        else:
            L.append("**No usable tie** — see the note in the table above.\n\n")
        L.append(ladder.round(4).to_markdown(index=False) + "\n\n")
        body = r["rgt"][r["rgt"]["rgt"] != "ALL"]
        if not body.empty:
            L.append("Per-RGT bias:\n\n")
            L.append(r["rgt"].round(4).to_markdown(index=False) + "\n\n")

    if figures:
        L.append("## Figures\n\n")
        for f in figures:
            L.append(f"- `outputs/figures/{f}`\n")
        L.append("\n")

    L.append("## Method\n\n")
    L.append(f"- Source: `{cfg.evrs_parquet.name}` (point-level), **not** the "
             f"reservoir-wide pass levels.\n"
             f"- Local pass = one `(date, rgt, beam)` inside the radius; level = "
             f"median `H_evrs_egg2015_m`.\n"
             f"- Local QC: `n_points >= {la.min_points_per_local_pass}`, "
             f"`nmad_m <= {la.max_local_nmad_m}`, and an ICESat-only plausibility "
             f"gate `|level − reservoir level that date| <= "
             f"{la.max_deviation_from_reservoir_m} m` (the reference is the median of "
             f"QC-ok reservoir-wide pass levels on the same date — never the gauge). "
             f"The reservoir-wide QC thresholds (track length, along-track slope) are "
             f"reservoir-scale and are not reused.\n"
             f"- Gauge stage interpolated ({cfg.matchup.gauge_interpolation}) to the "
             f"overpass time, max gap {cfg.matchup.max_time_difference_hours} h.\n"
             f"- CI is around the **median**: `1.96 · 1.2533 · NMAD / √n`.\n"
             f"- A station whose main radius has fewer than "
             f"{la.min_matchups_for_confidence} matchups is reported at the smallest "
             f"radius that reaches that count, flagged in `note`.\n"
             f"- `evrs_minus_bs77_m = alignment_constant_m − gauge_zero_baltic_m` by "
             f"construction — a shift of the same quantity, not independent evidence.\n")

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_dir / "kakhovka_local_alignment.md"
    out.write_text("".join(L), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    raise SystemExit(main())
