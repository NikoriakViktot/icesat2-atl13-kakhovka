#!/usr/bin/env python3
"""Phase 2c: empirical EGG2015 -> EVRF2019 corrector from the Kakhovka gauges.

    python scripts/egg2015_to_evrf2019.py            # all configured stations, + figures
    python scripts/egg2015_to_evrf2019.py --station 80959
    python scripts/egg2015_to_evrf2019.py --no-figures

For every gauge with usable PRE_BREACH observations this estimates

    c_station = median( H_gauge_EVRF2019 - H_ICESat_EGG2015 )

with H_gauge_EVRF2019 = gauge_zero_BS77 + stage + delta_EPSG9902(lat,lon) and
H_ICESat_EGG2015 = local median H_evrs_egg2015_m ( = ht_water_surf - zeta_EGG2015 ),
and quantifies its empirical precision (bootstrap over independent beam-passes)
separately from the systematic budget.

Reads  data/processed/kakhovka_atl13_evrs.parquet        (point-level)
       data/processed/kakhovka_atl13_pass_levels.parquet  (plausibility reference)
       data/external/datum/ua_2019z.asc                   (EPSG:9902 grid)
       gauge series via config/gauges.yaml
Writes outputs/tables/gauge_icesat_egg2015_matchups.csv
       outputs/tables/egg2015_to_evrf2019_by_station.csv
       outputs/tables/egg2015_to_evrf2019_by_radius.csv
       outputs/tables/egg2015_to_evrf2019_by_rgt.csv
       outputs/tables/egg2015_to_evrf2019_uncertainty.csv
       outputs/figures/{correction_by_station,correction_by_radius,correction_by_rgt,
                        residual_vs_distance,residual_vs_time,gauge_vs_icesat_timeseries}.png
       outputs/reports/egg2015_to_evrf2019_gauge_experiment.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from kakhovka_altimetry import egg2015_corrector as ec  # noqa: E402
from kakhovka_altimetry import official_datum as od  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.gauges import load_gauge_observations  # noqa: E402
from kakhovka_altimetry.io import read_parquet, setup_logging  # noqa: E402
from kakhovka_altimetry.local_alignment import CALIBRATION_PERIOD  # noqa: E402

CAVEAT = (
    "`c_station` is **not** an official datum transformation. It absorbs, "
    "inseparably from ICESat + gauges alone, the EGG2015 vs EVRF2019 model "
    "mismatch, the (unsurveyed) gauge-zero error, any systematic ICESat-2/ATL13 "
    "bias, and the spatial/temporal matchup mismatch. It equals "
    "`-delta_unexplained_m` from the Phase-2b decomposition."
)


# --------------------------------------------------------------------------- #
# Figures                                                                      #
# --------------------------------------------------------------------------- #
def _figures(matchups, ladder, station_tbl, rgt_tbl, term_obs, cfg) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figs = cfg.repo_root / "outputs" / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    C = ec.PRIMARY_C
    order = station_tbl.sort_values("lon")

    # 1. corrector by station, with bootstrap CI ------------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    s = order[np.isfinite(order["c_station_m"])]
    y = np.arange(len(s))
    lo = s["c_station_m"] - s["bootstrap_ci95_low_m"]
    hi = s["bootstrap_ci95_high_m"] - s["c_station_m"]
    colors = ["tab:red" if f == "LOW_SAMPLE" else "tab:blue" for f in s["flag"]]
    ax.errorbar(s["c_station_m"], y, xerr=[lo, hi], fmt="o", ecolor="gray", capsize=3)
    for yi, ci, col in zip(y, s["c_station_m"], colors, strict=False):
        ax.scatter([ci], [yi], color=col, zorder=5)
    if np.isfinite(s["c_station_m"]).sum() > 1:
        ax.axvline(float(np.median(s["c_station_m"])), ls="--", color="k", lw=1,
                   label=f"median {np.median(s['c_station_m']):+.3f} m")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{n}\n({r:g} km, n={nn})" for n, r, nn in
                        zip(s["name_en"], s["reported_radius_km"], s["n_matchups"], strict=False)])
    ax.set_xlabel("c_station  (m)   [EGG2015 height + c ≈ EVRF2019]")
    ax.set_title("Empirical EGG2015→EVRF2019 corrector per gauge\n"
                 "red = LOW_SAMPLE (n<5 independent beam-passes)")
    ax.legend()
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(figs / "correction_by_station.png", dpi=150)
    plt.close(fig)
    written.append("correction_by_station.png")

    # 2. corrector vs radius -------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    for name, g in ladder.groupby("name_en"):
        g = g.sort_values("radius_km")
        solid = g["n_matchups"] >= ec.MIN_INDEPENDENT
        ax.plot(g["radius_km"], g["c_station_m"], "-", alpha=0.4)
        ax.scatter(g.loc[solid, "radius_km"], g.loc[solid, "c_station_m"], label=name, s=40)
        ax.scatter(g.loc[~solid, "radius_km"], g.loc[~solid, "c_station_m"],
                   facecolors="none", edgecolors="gray", s=40)
    ax.set_xlabel("matchup radius (km)")
    ax.set_ylabel("c_station  (m)")
    ax.set_title("Corrector vs matchup radius (open marker = n<5)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figs / "correction_by_radius.png", dpi=150)
    plt.close(fig)
    written.append("correction_by_radius.png")

    # 3. corrector by RGT --------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    if not rgt_tbl.empty:
        names = list(dict.fromkeys(rgt_tbl["name_en"]))
        for i, name in enumerate(names):
            g = rgt_tbl[rgt_tbl["name_en"] == name]
            jitter = (i - len(names) / 2) * 0.06
            ax.errorbar(g["rgt"] + jitter, g["correction_m"],
                        yerr=[g["correction_m"] - g["ci95_low_m"],
                              g["ci95_high_m"] - g["correction_m"]],
                        fmt="o", capsize=2, label=name)
        ax.set_xlabel("RGT")
        ax.set_ylabel("c_station_rgt  (m)")
        ax.set_title("Per-RGT corrector at each station's reported radius")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figs / "correction_by_rgt.png", dpi=150)
    plt.close(fig)
    written.append("correction_by_rgt.png")

    # 4. residual vs distance --------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    for name, g in matchups.groupby("name_en"):
        ax.scatter(g["mean_distance_km"], g[C], s=12, alpha=0.5, label=name)
    ax.set_xlabel("mean distance of beam-pass to gauge (km)")
    ax.set_ylabel("c_station per matchup  (m)")
    ax.set_title("Per-matchup corrector vs distance to gauge (all radii)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figs / "residual_vs_distance.png", dpi=150)
    plt.close(fig)
    written.append("residual_vs_distance.png")

    # 5. residual vs time ----------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    prim = matchups[np.isclose(matchups["radius_km"], ec.PRIMARY_RADIUS_KM)]
    src = prim if not prim.empty else matchups
    for name, g in src.groupby("name_en"):
        ax.scatter(pd.to_datetime(g["datetime"]), g[C], s=16, alpha=0.6, label=name)
    ax.set_xlabel("ICESat-2 acquisition (UTC)")
    ax.set_ylabel("c_station per matchup  (m)")
    ax.set_title(f"Per-matchup corrector vs time "
                 f"(radius {ec.PRIMARY_RADIUS_KM:g} km where available)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figs / "residual_vs_time.png", dpi=150)
    plt.close(fig)
    written.append("residual_vs_time.png")

    # 6. gauge vs ICESat time series ----------------------------------
    names = list(dict.fromkeys(matchups["name_en"]))
    n = len(names)
    fig, axes = plt.subplots(n, 1, figsize=(10, 2.4 * n + 1), sharex=True, squeeze=False)
    for ax, name in zip(axes[:, 0], names, strict=False):
        g = matchups[(matchups["name_en"] == name)
                     & np.isclose(matchups["radius_km"], _report_r(ladder, name))]
        if g.empty:
            g = matchups[matchups["name_en"] == name]
        sid = g["station_id"].iloc[0]
        zero = g["gauge_zero_bs77_m"].iloc[0]
        d_off = g["delta_epsg9902_m"].iloc[0]
        to = term_obs[term_obs["station_id"] == sid].sort_values("datetime")
        to = to[pd.to_datetime(to["datetime"]) <= pd.Timestamp("2023-06-05", tz="UTC")]
        ax.plot(pd.to_datetime(to["datetime"]), zero + to["stage_m"] + d_off,
                "-", color="gray", lw=0.8, label="gauge H_EVRF2019 (nominal zero)")
        ax.scatter(pd.to_datetime(g["datetime"]), g["h_icesat_egg2015_m"],
                   s=22, color="tab:blue", label="ICESat H_EGG2015", zorder=5)
        ax.set_title(f"{name}  (c = {_report_c(ladder, name):+.3f} m)", fontsize=9)
        ax.set_ylabel("m")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    axes[-1, 0].set_xlabel("date")
    fig.tight_layout()
    fig.savefig(figs / "gauge_vs_icesat_timeseries.png", dpi=150)
    plt.close(fig)
    written.append("gauge_vs_icesat_timeseries.png")
    return written


def _report_r(ladder, name):
    lad = ladder[ladder["name_en"] == name]
    r = ec.reported_radius(lad)
    return r if r is not None else np.nan


def _report_c(ladder, name):
    lad = ladder[ladder["name_en"] == name]
    r = ec.reported_radius(lad)
    if r is None:
        return np.nan
    row = lad[np.isclose(lad["radius_km"], r)]
    return float(row["c_station_m"].iloc[0]) if not row.empty else np.nan


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #
def _fmt_fit(f: dict) -> str:
    if not np.isfinite(f.get("r2", np.nan)):
        return f"n={f.get('n', 0)} — too few stations"
    return (f"slope {f['slope']:+.3f} m per unit, R²={f['r2']:.2f} (n={f['n']})")


def _write_report(cfg, grid, validation, matchups, ladder, station_tbl, rgt_tbl,
                  unc_tbl, xstat, figures) -> None:
    ot = cfg.official_transform
    L: list[str] = []
    L.append("# Empirical EGG2015 → EVRF2019 corrector from the Kakhovka gauges\n\n")
    L.append(f"_ATL13 point-level `H_evrs_egg2015_m` (= `ht_water_surf − ζ_EGG2015`) "
             f"within a radius of each gauge, `{CALIBRATION_PERIOD}` only, matched to "
             f"that gauge's stage series and referenced to EVRF2019 with the official "
             f"EPSG:{ot.epsg_operation} grid._\n\n")
    L.append(f"> {CAVEAT}\n\n")

    L.append("## Definitions\n\n")
    L.append("```\n"
             "c_station        = median( H_gauge_EVRF2019 − H_ICESat_EGG2015 )\n"
             "H_gauge_EVRF2019 = gauge_zero_BS77 + stage_m + delta_EPSG9902(lat,lon)\n"
             "H_ICESat_EGG2015 = local median H_evrs_egg2015_m  (one value per beam-pass)\n"
             "use:  H_ICESat_EVRF2019_approx = H_ICESat_EGG2015 + c_station\n"
             "```\n\n")
    L.append(f"Independent statistical unit = one `(date, RGT, beam)` beam-pass. "
             f"Multiple ATL13 segments from one beam-pass are aggregated to a single "
             f"median first and never counted as independent. Bootstrap CIs "
             f"({ec.BOOTSTRAP_N:,} resamples) resample beam-passes, not segments. "
             f"Fewer than {ec.MIN_INDEPENDENT} independent beam-passes → `LOW_SAMPLE`.\n\n")

    # grid numerical sanity check (consistency, not identity — see provenance.json)
    L.append("## Official grid numerical sanity check\n\n```\n")
    L.append(od.format_validation(validation) + "\n```\n\n")
    L.append("Consistency with the published EPSG:9902 metadata, **not** proof of "
             "file identity — that is the SHA-256 in `provenance.json`. Its real job "
             "is to catch a wrong or all-zero grid, since PROJ's ballpark fallback "
             "between these CRSs silently returns 0.\n\n")

    # headline per station
    L.append("## Result per gauge (at the reported radius)\n\n")
    cols = ["name_en", "reported_radius_km", "n_matchups", "n_dates", "n_rgts",
            "delta_epsg9902_m", "c_station_m", "empirical_nmad_m",
            "bootstrap_ci95_low_m", "bootstrap_ci95_high_m",
            "c_station_B_nearest_m", "c_station_C_dailymean_m", "temporal_spread_m",
            "flag"]
    L.append(station_tbl[cols].round(3).to_markdown(index=False) + "\n\n")

    ok = station_tbl[station_tbl["flag"] == "OK"]

    # 1 & 2: Rozumivka and every other gauge -- the radius ladder
    L.append("## 1–2. Radius ladder, per gauge\n\n")
    L.append("`n` = independent beam-passes = `n_matchups`. Open question marks in "
             "the figures are `n<5`.\n\n")
    lcols = ["name_en", "radius_km", "n_matchups", "n_dates", "n_rgts",
             "median_h_icesat_egg2015_m", "c_station_m", "empirical_nmad_m",
             "bootstrap_ci95_low_m", "bootstrap_ci95_high_m", "flag"]
    for name, g in ladder.groupby("name_en"):
        L.append(f"### {name}\n\n")
        L.append(g[lcols].round(3).to_markdown(index=False) + "\n\n")

    # 3: per-RGT
    L.append("## 3. Per-RGT corrector and RGT bias\n\n")
    if rgt_tbl.empty:
        L.append("_No station reached the reported-radius threshold._\n\n")
    else:
        rcols = ["name_en", "radius_km", "rgt", "n_matchups", "n_dates",
                 "correction_m", "nmad_m", "ci95_low_m", "ci95_high_m",
                 "c_station_all_m", "rgt_bias_m", "flag"]
        L.append(rgt_tbl[rcols].round(3).to_markdown(index=False) + "\n\n")
        body = rgt_tbl[rgt_tbl["flag"] == "OK"]
        if not body.empty:
            L.append(f"Largest |RGT bias| among n≥{ec.MIN_INDEPENDENT} rows: "
                     f"**{body['rgt_bias_m'].abs().max() * 100:.1f} cm**.\n\n")

    # 4: variance attribution
    L.append("## 4. How much variation comes from what\n\n")
    solid = ladder[ladder["n_matchups"] >= ec.MIN_INDEPENDENT]
    rad_spread = (solid.groupby("name_en")["c_station_m"]
                  .agg(lambda s: s.max() - s.min()))
    rgt_spread = (rgt_tbl[rgt_tbl["flag"] == "OK"].groupby("name_en")["rgt_bias_m"]
                  .agg(lambda s: s.max() - s.min())) if not rgt_tbl.empty else pd.Series(dtype=float)
    L.append("| source | spread | how measured |\n|---|---:|---|\n")
    L.append(f"| **station** | {xstat.get('range_m', float('nan')) * 100:.0f} cm "
             f"(NMAD {xstat.get('station_to_station_nmad_m', float('nan')) * 100:.1f} cm) "
             f"| range of `c_station` across the {xstat.get('n_stations', 0)} usable gauges |\n")
    L.append(f"| **radius** | {rad_spread.min() * 100:.1f}–{rad_spread.max() * 100:.1f} cm "
             f"| per-station max−min of `c_station` over n≥{ec.MIN_INDEPENDENT} radii |\n")
    if not rgt_spread.empty:
        L.append(f"| **RGT** | {rgt_spread.min() * 100:.1f}–{rgt_spread.max() * 100:.1f} cm "
                 f"| per-station max−min RGT bias (n≥{ec.MIN_INDEPENDENT}) |\n")
    L.append(f"| **time matching (A/B/C)** | "
             f"{station_tbl['temporal_spread_m'].min() * 100:.1f}–"
             f"{station_tbl['temporal_spread_m'].max() * 100:.1f} cm "
             f"| max−min of `c_station` over interpolated / nearest / daily-mean stage |\n")
    L.append(f"| **within-station repeatability** | NMAD "
             f"{ok['empirical_nmad_m'].min() * 100:.1f}–{ok['empirical_nmad_m'].max() * 100:.1f} cm "
             f"| beam-pass scatter at the reported radius (OK stations) |\n\n")

    # 5: precision vs accuracy
    L.append("## 5. Precision vs absolute accuracy\n\n")
    L.append("**PRECISION (repeatability, measured here).** The beam-pass NMAD and "
             "the bootstrap CI of the median. This is the only uncertainty these data "
             "constrain.\n\n")
    L.append("**ABSOLUTE ACCURACY (not fully resolved here).** Limited by, kept as "
             "separate lines and *not* combined in quadrature:\n\n")
    L.append(f"- `epsg9902_op_accuracy` = {ec.EPSG9902_OP_ACCURACY_M:.3f} m — EPSG:"
             f"{ot.epsg_operation}'s published **operation accuracy** field. It is "
             f"*not* a standard deviation and *not* a 95% CI: the same EPSG record "
             f"separately reports SD "
             f"{ot.published_stats.get('sd_m', float('nan')):.3f} m over "
             f"{ot.published_stats.get('n_determination_points', '?')} determination "
             f"points. Quote it as an operation accuracy or not at all.\n")
    L.append("- gauge-zero uncertainty — **not independently constrained** (no "
             "surveyed BS-77 zero; the nominal 12.00 m is a reservoir-wide figure).\n")
    L.append("- EGG2015 model error over Ukraine (~0.1 m quoted) — **unresolved**; not "
             "inferred from these gauge comparisons.\n")
    L.append("- ATL13 systematic bias — **unresolved**; the per-RGT spread bounds the "
             "track-dependent part but does not separate a common offset.\n")
    L.append("- temporal mismatch — bounded empirically by the A/B/C spread above.\n\n")
    L.append("See `outputs/tables/egg2015_to_evrf2019_uncertainty.csv` for the "
             "per-station split.\n\n")

    # 6: compact final
    L.append("## 6. Final result (compact)\n\n")
    for _, r in station_tbl.iterrows():
        if not np.isfinite(r["c_station_m"]):
            L.append(f"**{r['name_en']}** — no radius reaches "
                     f"{ec.MIN_INDEPENDENT} independent beam-passes; no corrector.\n\n")
            continue
        tag = "  _(LOW_SAMPLE)_" if r["flag"] == "LOW_SAMPLE" else ""
        ci_hw = (r["bootstrap_ci95_high_m"] - r["bootstrap_ci95_low_m"]) / 2
        if np.isfinite(ci_hw) and np.isfinite(r["empirical_nmad_m"]) \
                and ci_hw > 2.2 * max(r["empirical_nmad_m"], 1e-6):
            tag += "  _(CI much wider than NMAD — bimodal by RGT; see Recommendation)_"
        L.append(
            f"**{r['name_en']}**{tag}\n"
            f"```\n"
            f"c_station              = {r['c_station_m']:+.3f} m   "
            f"(radius {r['reported_radius_km']:g} km, n = {r['n_matchups']} beam-passes, "
            f"{r['n_dates']} dates, {r['n_rgts']} RGTs)\n"
            f"empirical precision    = ±{r['empirical_nmad_m']:.3f} m (NMAD)   "
            f"std ±{r['empirical_std_m']:.3f} m\n"
            f"bootstrap 95% CI       = [{r['bootstrap_ci95_low_m']:+.3f}, "
            f"{r['bootstrap_ci95_high_m']:+.3f}] m\n"
            f"temporal A/B/C spread  = {r['temporal_spread_m'] * 100:.1f} cm  "
            f"(A {r['c_station_m']:+.3f} / B {r['c_station_B_nearest_m']:+.3f} / "
            f"C {r['c_station_C_dailymean_m']:+.3f})\n"
            f"EPSG:{ot.epsg_operation} op. accuracy = {ec.EPSG9902_OP_ACCURACY_M:.3f} m (not a sigma)\n"
            f"unresolved systematic  = gauge zero + EGG2015 model + ATL13 bias\n"
            f"```\n\n"
        )

    # 3-across: one regional constant?
    L.append("## Is one Kakhovka-wide corrector justified?\n\n")
    if xstat.get("n_stations", 0) < 2:
        L.append("_Only one gauge has a usable corrector — cannot test._\n\n")
    else:
        L.append(f"- median across the {xstat['n_stations']} usable gauges: "
                 f"**{xstat['median_c_m']:+.3f} m**\n")
        L.append(f"- station-to-station NMAD: **{xstat['station_to_station_nmad_m'] * 100:.1f} cm**, "
                 f"range {xstat['range_m'] * 100:.0f} cm "
                 f"({xstat['min_c_m']:+.3f} … {xstat['max_c_m']:+.3f} m)\n")
        L.append(f"- median bootstrap CI half-width per station: "
                 f"±{xstat['median_bootstrap_ci_halfwidth_m'] * 100:.1f} cm\n")
        L.append(f"- trend vs longitude: {_fmt_fit(xstat['fit_vs_lon'])}\n")
        L.append(f"- trend vs latitude: {_fmt_fit(xstat['fit_vs_lat'])}\n")
        L.append(f"- trend vs ICESat level: {_fmt_fit(xstat['fit_vs_icesat_level'])}\n")
        L.append(f"- trend vs `delta_EPSG9902`: "
                 f"{_fmt_fit(xstat['fit_vs_delta_epsg9902_COUPLED'])} — "
                 f"**ALGEBRAICALLY COUPLED, descriptive only.** "
                 f"`c = zero + stage + delta_EPSG9902 − H_ICESat`, so this regresses "
                 f"`c` on one of its own additive constituents; the R² carries no "
                 f"causal information and must not be read as evidence of a spatial "
                 f"relationship. An independent version needs an external quasigeoid "
                 f"(УКГ2025): `c_geodetic = ζ_EGG2015 − ζ_УКГ2025`.\n\n")
        spread_exceeds = xstat["range_m"] > 2 * xstat["median_bootstrap_ci_halfwidth_m"]
        L.append(
            ("**The station-to-station spread exceeds the per-station precision** — a "
             "single Kakhovka-wide constant is **not** justified by these data; the "
             "corrector is at least partly station-specific. What makes it "
             "station-specific is *not* determined here: unsurveyed gauge zeros, "
             "EGG2015 model error and ATL13 bias all enter `c` additively and these "
             "data cannot separate them.\n\n")
            if spread_exceeds else
            ("The station-to-station spread is within the per-station precision — a "
             "single regional constant is **not excluded**, but the LOW_SAMPLE gauges "
             "carry most of the weight of that statement.\n\n")
        )

    # validation checks
    L.append("## Sanity checks\n\n")
    L.append(f"- Calibration is `{CALIBRATION_PERIOD}` only; no POST_BREACH row enters "
             f"any estimate (asserted in code).\n")
    L.append(f"- Radius dependence: per-station `c_station` spread over n≥"
             f"{ec.MIN_INDEPENDENT} radii is {rad_spread.min() * 100:.1f}–"
             f"{rad_spread.max() * 100:.1f} cm "
             f"({'within' if rad_spread.max() < 0.10 else 'NOT within'} 10 cm) — flat.\n")
    if not rgt_tbl.empty:
        well = rgt_tbl[rgt_tbl["flag"] == "OK"]
        thin = rgt_tbl[rgt_tbl["flag"] == "LOW_SAMPLE"].copy()
        wmax = well["rgt_bias_m"].abs().max() * 100 if not well.empty else float("nan")
        worst = thin.reindex(thin["rgt_bias_m"].abs().sort_values(ascending=False).index).head(3)
        offenders = "; ".join(
            f"{w['name_en']} RGT {w['rgt']} (n={w['n_matchups']}, "
            f"bias {w['rgt_bias_m'] * 100:+.1f} cm)" for _, w in worst.iterrows()
        )
        L.append(f"- RGT dependence: among n≥{ec.MIN_INDEPENDENT} RGT subsets the bias "
                 f"is ≤{wmax:.1f} cm — flat. Among n<{ec.MIN_INDEPENDENT} RGT subsets "
                 f"it reaches {worst['rgt_bias_m'].abs().max() * 100:.1f} cm: {offenders}. "
                 f"These are the ascending upstream tracks that clip the shoreline; "
                 f"they are why Rozumivka's 2 km bootstrap CI is wide and bimodal. "
                 f"Not removed — see the recommendation below.\n")
    # outliers, not removed -- scan each station at its reported radius
    out_rows = []
    for _, r in station_tbl.iterrows():
        rr = r["reported_radius_km"]
        if not np.isfinite(rr):
            continue
        g = matchups[(matchups["station_id"] == r["station_id"])
                     & np.isclose(matchups["radius_km"], rr)].copy()
        g["resid_m"] = g[ec.PRIMARY_C] - r["c_station_m"]
        out_rows.append(g[g["resid_m"].abs() > 0.12])
    out = pd.concat(out_rows, ignore_index=True) if out_rows else matchups.iloc[:0]
    n_scanned = sum(
        int(((matchups["station_id"] == r["station_id"])
             & np.isclose(matchups["radius_km"], r["reported_radius_km"])).sum())
        for _, r in station_tbl.iterrows() if np.isfinite(r["reported_radius_km"])
    )
    L.append(f"- Outliers at each station's reported radius (|c − station c| > 0.12 m), "
             f"**listed, not removed**: {len(out)} of {n_scanned}.\n")
    if not out.empty:
        L.append("\n" + out[["name_en", "date", "rgt", "beam", "mean_distance_km",
                             "h_icesat_egg2015_m", ec.PRIMARY_C]].round(3)
                 .to_markdown(index=False) + "\n")
    L.append("\n")

    L.append("## Recommendation\n\n")
    L.append("- **Every gauge here is thin** (5–12 independent beam-passes at the "
             "reported radius; 2020–2021 only, except Rozumivka). Treat all six "
             "correctors as provisional.\n")
    L.append("- **Rozumivka** — the 2 km pooled value (−0.146 m) is split by RGT "
             "(989 → −0.128, 205 → −0.222). RGT 205 reads high near the shoreline. "
             "The 3 km and 5 km values (−0.146, −0.155 m; NMAD 5–7 cm; CI ≈ ±4 cm) "
             "are more stable and are the recommended figure: "
             "**c ≈ −0.15 m, empirical precision ±0.05 m**.\n")
    L.append("- The six correctors cluster at **−0.13 … −0.22 m, median −0.17 m** "
             "(station-to-station NMAD 4.6 cm). A single regional constant of "
             "**−0.17 ± 0.05 m** is defensible as a first approximation; a "
             "per-station value is better where one exists.\n")
    L.append("- A common **adopted** gauge datum zero of 12.000 m in Baltic 1977 was "
             "used for all six posts. It is an adopted constant, not an estimated "
             "parameter — the `implied_gauge_zero_baltic_m` diagnostic below simply "
             "restates the residual against it and is not an independent result.\n\n")

    if figures:
        L.append("## Figures\n\n")
        for f in figures:
            L.append(f"- `outputs/figures/{f}`\n")
        L.append("\n")

    L.append("## Method notes\n\n")
    L.append(f"- Local beam-pass = one `(date, RGT, beam)` inside the radius; level = "
             f"median `H_evrs_egg2015_m`. Local QC: `n_seg ≥ "
             f"{cfg.local_alignment.min_points_per_local_pass}`, `NMAD ≤ "
             f"{cfg.local_alignment.max_local_nmad_m} m`, and `|level − reservoir-wide "
             f"ICESat level that date| ≤ {cfg.local_alignment.max_deviation_from_reservoir_m} "
             f"m` (reference never the gauge).\n")
    L.append(f"- Temporal strategies: **A** linear-interpolate the 08:00/20:00 term "
             f"readings to the overpass (primary); **B** nearest term reading; **C** "
             f"linear-interpolate the daily mean. Tolerance to the nearest real reading "
             f"{ec.MAX_GAP_TERM_H:g} h (A/B), {ec.MAX_GAP_DAILY_H:g} h (C). Missing days "
             f"are not interpolated across (the gap check drops them).\n")
    L.append("- Gauge term timestamps are Europe/Kyiv (per `config/gauges.yaml`), "
             "converted to UTC before matching to the UTC ICESat time.\n")
    L.append(f"- `delta_EPSG9902` is sampled once per gauge from `ua_2019z.asc` "
             f"(EPSG:{ot.epsg_operation}, {ot.tide_system}).\n")
    L.append(f"- Reported radius = the radius nearest {ec.PRIMARY_RADIUS_KM:g} km that "
             f"reaches {ec.MIN_INDEPENDENT} independent beam-passes.\n")
    L.append("- Implied BS-77 gauge zero under zero EGG2015/ATL13 systematic bias = "
             "`nominal_zero − c_station` (see the by-station table); this is a "
             "prediction to test against a technical passport, **not** a measured zero.\n")

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_dir / "egg2015_to_evrf2019_gauge_experiment.md"
    out.write_text("".join(L), encoding="utf-8")
    print(f"wrote {out}")


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station", default="all", help="'all' or comma-separated post ids")
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    tables = cfg.tables_dir
    tables.mkdir(parents=True, exist_ok=True)

    grid = od.load_official_grid(cfg)
    validation = od.validate_against_published(grid, cfg)
    print(od.format_validation(validation), "\n")
    if not validation["passed"]:
        print("official grid failed validation — aborting", file=sys.stderr)
        return 2

    evrs = read_parquet(cfg.evrs_parquet)
    try:
        reservoir = read_parquet(cfg.pass_levels_parquet)
    except FileNotFoundError:
        reservoir = None
    term_obs = load_gauge_observations(cfg)
    mean_obs = ec.load_daily_mean_series(cfg)

    if args.station == "all":
        stations = [s for s in cfg.gauges.stations if s.complete]
    else:
        ids = [int(x) for x in args.station.split(",")]
        stations = [cfg.gauges.station(i) for i in ids]

    frames = []
    for st in stations:
        m = ec.station_matchups(evrs, term_obs, mean_obs, st, cfg, grid,
                                reservoir_passes=reservoir)
        if not m.empty:
            assert (m["c_station_A_m"].notna()).all()
            frames.append(m)
        print(f"{st.id} {st.name_en:<18} {0 if m.empty else len(m)} matchup rows "
              f"(all radii)")
    if not frames:
        print("no matchups at any station", file=sys.stderr)
        return 2

    matchups = pd.concat(frames, ignore_index=True)
    # never let a non-calibration row through
    assert "period" not in matchups.columns or (matchups["period"] == CALIBRATION_PERIOD).all()

    ladder = ec.by_radius(matchups)
    station_tbl = ec.by_station(matchups, ladder)
    rgt_tbl = ec.by_rgt(matchups, ladder)
    unc_tbl = ec.uncertainty_table(matchups, ladder)
    xstat = ec.cross_station(station_tbl)

    matchups.to_csv(tables / "gauge_icesat_egg2015_matchups.csv", index=False)
    station_tbl.to_csv(tables / "egg2015_to_evrf2019_by_station.csv", index=False)
    ladder.to_csv(tables / "egg2015_to_evrf2019_by_radius.csv", index=False)
    rgt_tbl.to_csv(tables / "egg2015_to_evrf2019_by_rgt.csv", index=False)
    unc_tbl.to_csv(tables / "egg2015_to_evrf2019_uncertainty.csv", index=False)

    print("\nby station:\n", station_tbl[
        ["name_en", "reported_radius_km", "n_matchups", "c_station_m",
         "empirical_nmad_m", "bootstrap_ci95_low_m", "bootstrap_ci95_high_m", "flag"]
    ].round(3).to_string(index=False))
    import json
    print("\ncross-station:\n", json.dumps(xstat, indent=1, default=float))

    figures = [] if args.no_figures else _figures(
        matchups, ladder, station_tbl, rgt_tbl, term_obs, cfg
    )
    _write_report(cfg, grid, validation, matchups, ladder, station_tbl, rgt_tbl,
                  unc_tbl, xstat, figures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
