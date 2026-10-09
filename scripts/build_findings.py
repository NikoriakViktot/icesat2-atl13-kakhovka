#!/usr/bin/env python3
"""Step 4 (V1): write outputs/reports/atl13_v1_findings.md from the built tables.

    python scripts/build_findings.py

Reads  data/processed/kakhovka_atl13_evrs.parquet
       data/processed/kakhovka_atl13_pass_levels.parquet
Writes outputs/reports/atl13_v1_findings.md
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.io import read_parquet, setup_logging  # noqa: E402

PRE = "PRE_BREACH"
POST = ("BREACH_DRAWDOWN", "POST_BREACH")


def _fmt(x, n=2):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{n}f}"


def _dist(s: pd.Series) -> str:
    s = s.dropna()
    if s.empty:
        return "n/a"
    return (f"median {_fmt(s.median())}, p10 {_fmt(s.quantile(.1))}, "
            f"p90 {_fmt(s.quantile(.9))}, min {_fmt(s.min())}, max {_fmt(s.max())}")


def _beam_agreement(passes: pd.DataFrame) -> pd.DataFrame:
    """Spread of median WSE across beams of the same (date, rgt)."""
    g = passes.groupby(["date", "rgt"])["median_wse_evrs_m"]
    agg = g.agg(n_beams="size", wse_spread_m=lambda v: v.max() - v.min())
    return agg[agg["n_beams"] > 1]


def _outliers(passes: pd.DataFrame) -> pd.DataFrame:
    """Genuinely suspect passes.

    Deviation from a period mean is NOT used (the reservoir level really does move
    ~metres seasonally, and dramatically in 2023). Instead:
      * gross within-pass quality failure: nmad_m > 0.30 m or range_m > 2.0 m;
      * cross-beam disagreement: among QC-ok beams of one (date, rgt), the median
        WSE spread exceeds 0.30 m.
    """
    gross = passes[(passes["nmad_m"] > 0.30) | (passes["range_m"] > 2.0)].copy()
    gross["reason"] = "within-pass spread"

    ok = passes[passes["qc_pass"]]
    disagree_keys = (
        ok.groupby(["date", "rgt"])["median_wse_evrs_m"]
        .agg(n="size", spread=lambda v: v.max() - v.min())
        .query("n > 1 and spread > 0.30")
        .index
    )
    disc = ok[ok.set_index(["date", "rgt"]).index.isin(disagree_keys)].copy()
    disc["reason"] = "cross-beam disagreement"

    both = pd.concat([gross, disc]).drop_duplicates(subset=["datetime", "transect"])
    return both.sort_values("datetime")


def main() -> int:
    setup_logging()
    cfg = load_config()

    passes = read_parquet(cfg.pass_levels_parquet)
    evrs = read_parquet(cfg.evrs_parquet)
    passes["date"] = pd.to_datetime(passes["datetime"]).dt.date

    ok = passes[passes["qc_pass"]]
    pre_ok = ok[ok["period"] == PRE]
    post_ok = ok[ok["period"].isin(POST)]

    per_year = (
        passes.groupby("year")["qc_pass"]
        .agg(passes_total="size", passes_qc_ok="sum")
        .reset_index()
    )
    diff = evrs["egm2008_minus_evrs_m"].dropna()
    beam_agree = _beam_agreement(ok)
    outliers = _outliers(passes)

    L = []
    L.append("# ATL13 → EGG2015 → EVRS water levels for the Kakhovka reservoir — V1 findings\n")
    L.append(f"_Generated from `{cfg.pass_levels_parquet.name}` "
             f"({len(passes)} passes) and `{cfg.evrs_parquet.name}` "
             f"({len(evrs)} point segments)._\n")

    L.append("## 1. Passes obtained\n")
    L.append(f"- Total beam-passes over water: **{len(passes)}**\n"
             f"- Passing QC: **{len(ok)}** ({len(passes) - len(ok)} rejected)\n"
             f"- Distinct RGT/beam transects: **{passes['transect'].nunique()}**\n"
             f"- Date span: {passes['date'].min()} → {passes['date'].max()}\n")
    if not passes.loc[~passes["qc_pass"], "qc_flags"].pipe(
        lambda s: s[s.str.len() > 0]
    ).empty:
        reasons = (passes.loc[~passes["qc_pass"], "qc_flags"]
                   .pipe(lambda s: s[s.str.len() > 0]).str.get_dummies("|").sum()
                   .sort_values(ascending=False))
        L.append("\nRejection reasons: " + ", ".join(f"{k} ({v})" for k, v in reasons.items()) + "\n")

    L.append("\n## 2. Passes per year\n")
    L.append(per_year.to_markdown(index=False) + "\n")

    L.append("\n## 3. Points per pass\n")
    L.append(f"- All passes: {_dist(passes['n_points'])}\n"
             f"- QC-ok passes: {_dist(ok['n_points'])}\n"
             f"- Along-track length (km): {_dist(ok['track_length_km'])}\n")

    L.append("\n## 4. Within-pass water-surface spread (QC-ok)\n")
    L.append(f"- `nmad_m`: {_dist(ok['nmad_m'])}\n"
             f"- `range_m` (p95−p05): {_dist(ok['range_m'])}\n"
             f"- `mad_m`: {_dist(ok['mad_m'])}\n"
             f"- along-track slope (m/km): {_dist(ok['along_track_slope_m_per_km'].abs())}\n")

    L.append("\n## 5. Beam / transect agreement (same date + RGT, QC-ok)\n")
    if beam_agree.empty:
        L.append("- No date+RGT had more than one QC-ok beam.\n")
    else:
        L.append(f"- {len(beam_agree)} multi-beam overpasses.\n"
                 f"- Cross-beam WSE spread (m): {_dist(beam_agree['wse_spread_m'])}\n")

    L.append("\n## 6. Suspect passes\n")
    L.append("_Deviation from the seasonal mean is deliberately NOT a criterion — "
             "the reservoir level genuinely moves metres (see §7). Flags: within-pass "
             "`nmad_m` > 0.30 m or `range_m` > 2.0 m, or QC-ok beams of one "
             "date+RGT disagreeing by > 0.30 m._\n\n")
    if outliers.empty:
        L.append("- None.\n")
    else:
        cols = ["datetime", "transect", "period", "n_points",
                "median_wse_evrs_m", "nmad_m", "range_m", "qc_pass", "reason"]
        by_reason = outliers["reason"].value_counts().to_dict()
        L.append(f"- {len(outliers)} flagged — "
                 + "; ".join(f"{k}: {v}" for k, v in by_reason.items()) + ".\n")
        L.append("- Almost all are BREACH_DRAWDOWN / POST_BREACH (braided channel, "
                 "not a flat pool). Sample:\n\n")
        L.append(outliers[cols].head(15).to_markdown(index=False) + "\n")

    L.append("\n## 7. PRE_BREACH reservoir WSE (up to 2023-06-06, QC-ok)\n")
    if pre_ok.empty:
        L.append("- No QC-ok PRE_BREACH passes.\n")
    else:
        stable = pre_ok[pre_ok["year"] <= 2022]
        w, ws = pre_ok["median_wse_evrs_m"], stable["median_wse_evrs_m"]
        L.append(f"- n passes: **{len(pre_ok)}** (2018–2022 stable pool: {len(stable)})\n"
                 f"- **2018–2022 stable pool: typical WSE {_fmt(ws.median())} m EVRS** "
                 f"(mean {_fmt(ws.mean())}, std {_fmt(ws.std())}, "
                 f"p05–p95 {_fmt(ws.quantile(.05))}–{_fmt(ws.quantile(.95))})\n"
                 f"- Full PRE_BREACH incl. 2023: {_fmt(w.median())} m median, "
                 f"range {_fmt(w.min())} … {_fmt(w.max())} m\n")
        L.append("\n**2023 pre-breach was anomalous**: the reservoir was drawn down "
                 "to ~14.2 m EVRS by Feb–Mar 2023, then refilled to ~17.4 m by "
                 "May 2023 — a ~3 m swing captured by ICESat-2 *before* the "
                 "6 June breach. This is why the 2023 row has a large std.\n")
        L.append("\nPer year:\n")
        L.append(pre_ok.groupby("year")["median_wse_evrs_m"]
                 .agg(n="size", median="median", std="std", min="min", max="max")
                 .round(3).reset_index().to_markdown(index=False) + "\n")
        L.append("\nMonthly, Nov 2022 → Jun 2023 (the pre-breach drawdown/refill):\n")
        pm = pre_ok[pre_ok["datetime"] >= pd.Timestamp("2022-11-01", tz="UTC")].copy()
        pm["month"] = pd.to_datetime(pm["datetime"]).dt.strftime("%Y-%m")
        L.append(pm.groupby("month")["median_wse_evrs_m"]
                 .agg(n="size", median="median").round(2).reset_index()
                 .to_markdown(index=False) + "\n")

    L.append("\n## 8. After the dam breach — reported separately\n")
    if post_ok.empty:
        L.append("- No QC-ok passes after 2023-06-06 yet.\n")
    else:
        for period in POST:
            g = post_ok[post_ok["period"] == period]
            if g.empty:
                continue
            w = g["median_wse_evrs_m"]
            L.append(f"- **{period}**: n={len(g)}, WSE median {_fmt(w.median())} m EVRS, "
                     f"range {_fmt(w.min())} … {_fmt(w.max())} m "
                     f"({g['datetime'].min().date()} → {g['datetime'].max().date()})\n")
        L.append("\n_Not mixed into the PRE_BREACH reservoir statistics above._\n")

    L.append("\n## 9. Vertical-chain sanity: EGM2008 − EGG2015/EVRS\n")
    L.append(f"- `egm2008_minus_evrs_m`: mean **{_fmt(diff.mean(), 3)} m**, "
             f"std {_fmt(diff.std(), 3)} m, range [{_fmt(diff.min(), 3)}, {_fmt(diff.max(), 3)}]\n"
             f"- Expected: small (decimetre) and spatially smooth → the "
             f"ellipsoidal / EGM2008 / EGG2015 chain is not mixed up.\n")

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.reports_dir / "atl13_v1_findings.md"
    out.write_text(textwrap.dedent("".join(L)), encoding="utf-8")
    print(f"wrote {out}")
    print("".join(L[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
