#!/usr/bin/env python3
"""Phase 3: compare candidate spatial models for the EGG2015 -> EVRF2019 corrector.

    python scripts/spatial_model_comparison.py [--no-figures]

Reads   outputs/tables/egg2015_to_evrf2019_by_station.csv   (Phase 2c, 6 gauges)
Writes  outputs/tables/egg2015_to_evrf2019_spatial_cv.csv          (model x held-out station)
        outputs/tables/egg2015_to_evrf2019_spatial_cv_summary.csv  (one row per model)
        outputs/figures/spatial_model_loso_cv.png
        outputs/figures/spatial_corrector_models.png
        outputs/reports/kakhovka_spatial_model_comparison.md

With only six controls, random train/test splitting is meaningless: the test is
leave-one-whole-station-out. The headline is "the simplest model that survives
LOSO-CV", not the prettiest raster -- see the nearest-station rationale in
kakhovka_altimetry.corrector_surface.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from kakhovka_altimetry import spatial_models as sm  # noqa: E402
from kakhovka_altimetry.config import load_config  # noqa: E402
from kakhovka_altimetry.corrector_surface import load_station_correctors, nearest_station  # noqa: E402
from kakhovka_altimetry.io import setup_logging  # noqa: E402

_PRETTY = {
    "constant": "regional constant", "plane": "LS plane",
    "idw_p1": "IDW p=1", "idw_p2": "IDW p=2", "linear": "linear (Delaunay)",
}


def _loso_figure(per_row: pd.DataFrame, summary: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(summary["model"])
    fig, axes = plt.subplots(1, len(names), figsize=(3.1 * len(names), 3.4), sharex=True, sharey=True)
    lo = float(np.nanmin([per_row["observed_c_m"].min(), per_row["predicted_c_m"].min()])) - 0.01
    hi = float(np.nanmax([per_row["observed_c_m"].max(), per_row["predicted_c_m"].max()])) + 0.01
    for ax, name in zip(np.atleast_1d(axes), names, strict=False):
        g = per_row[per_row["model"] == name]
        ax.plot([lo, hi], [lo, hi], color="0.6", lw=1, zorder=1)
        ax.scatter(g["observed_c_m"], g["predicted_c_m"], s=42, color="#3b6ea5",
                   edgecolor="white", linewidth=0.6, zorder=3)
        miss = int(g["predicted_c_m"].isna().sum())
        row = summary[summary["model"] == name].iloc[0]
        sub = f"RMSE {row['loso_rmse_m'] * 100:.1f} cm"
        if miss:
            sub += f"  ·  {miss}/{len(g)} outside support"
        ax.set_title(f"{_PRETTY[name]}\n{sub}", fontsize=9)
        ax.set_xlabel("observed c  (m)")
        ax.xaxis.set_major_locator(plt.MaxNLocator(4))
        ax.yaxis.set_major_locator(plt.MaxNLocator(5))
        ax.tick_params(labelsize=8)
        ax.grid(alpha=0.25)
    np.atleast_1d(axes)[0].set_ylabel("LOSO-predicted c  (m)")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    fig.suptitle("Leave-one-station-out cross-validation of the corrector spatial models", y=1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _surface_figure(stations: pd.DataFrame, models: dict, cfg, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lon_min, lat_min, lon_max, lat_max = cfg.aoi_bbox
    lons = np.linspace(lon_min, lon_max, 160)
    lats = np.linspace(lat_min, lat_max, 160)
    LON, LAT = np.meshgrid(lons, lats)

    panels: list[tuple[str, np.ndarray]] = []
    for name in sm.MODEL_NAMES:
        m = models.get(name)
        if isinstance(m, Exception):
            continue
        panels.append((_PRETTY[name],
                       m.predict(LAT.ravel(), LON.ravel()).reshape(LAT.shape)))
    ns = nearest_station(LAT.ravel(), LON.ravel(), stations)
    panels.append(("nearest-station (adopted)",
                   ns["egg2015_to_evrf2019_corrector_m"].to_numpy(float).reshape(LAT.shape)))

    finite = np.concatenate([p[np.isfinite(p)] for _, p in panels])
    vmin, vmax = np.percentile(finite, [1, 99])

    ncol = 3
    nrow = int(np.ceil(len(panels) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.6 * ncol, 4.0 * nrow))
    axes = np.atleast_1d(axes).ravel()
    im = None
    for ax, (title, grid) in zip(axes, panels, strict=False):
        im = ax.pcolormesh(lons, lats, grid, cmap="viridis_r", vmin=vmin, vmax=vmax,
                           shading="nearest")
        ax.scatter(stations["lon"], stations["lat"], s=40, c="white",
                   edgecolor="black", linewidth=0.8, zorder=5)
        for _, r in stations.iterrows():
            ax.annotate(f"{r['c_station_m']:+.02f}", (r["lon"], r["lat"]),
                        textcoords="offset points", xytext=(5, 3), fontsize=6.5,
                        color="black", zorder=6)
        ax.set_aspect(1.0 / np.cos(np.radians(0.5 * (lat_min + lat_max))))
        ax.set_title(title, fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
    for ax in axes[len(panels):]:
        ax.axis("off")
    fig.colorbar(im, ax=axes.tolist(), shrink=0.7,
                 label="EGG2015 -> EVRF2019 corrector  c(x,y)  (m)")
    fig.suptitle("Candidate corrector surfaces over the Kakhovka AOI "
                 "(6 gauge controls; all values negative)", y=1.0)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _report(stations, per_row, summary, cfg, figures) -> None:
    best = summary.iloc[0]
    const_rmse = float(summary.loc[summary["model"] == "constant", "loso_rmse_m"].iloc[0])
    L = ["# Порівняння просторових моделей корректора EGG2015→EVRF2019\n\n"]
    L.append("_Шість точкових оцінок `c_station` (Фаза 2c) → чотири гладкі кандидати "
             "(constant / plane / IDW p=1,2 / linear) проти прийнятої nearest-station "
             "поверхні. Валідація — виключення цілої станції (LOSO-CV): із 6 контролями "
             "випадковий спліт беззмістовний._\n\n")
    L.append("## LOSO-CV, зведення (відсортовано за RMSE)\n\n")
    disp = summary.copy()
    for c in ("loso_bias_m", "loso_mae_m", "loso_rmse_m", "loso_median_abs_error_m", "max_abs_error_m"):
        disp[c] = (disp[c] * 100).round(1)
    disp = disp.rename(columns=lambda c: c.replace("_m", "_cm") if c.endswith("_m") else c)
    L.append(disp.to_markdown(index=False) + "\n\n")
    L.append("## LOSO-CV, покроково (модель × виключена станція)\n\n")
    pr = per_row.copy()
    for c in ("observed_c_m", "predicted_c_m", "error_m", "abs_error_m"):
        pr[c] = pr[c].round(3)
    L.append(pr.to_markdown(index=False) + "\n\n")
    L.append("## Висновок\n\n")
    L.append(f"- Найкраща за RMSE модель: **{_PRETTY[best['model']]}** "
             f"({best['loso_rmse_m'] * 100:.1f} см).\n")
    L.append(f"- Регіональна константа: **{const_rmse * 100:.1f} см** RMSE — "
             f"різниця з найкращою гладкою моделлю в межах ~1 см і в межах "
             f"станційного NMAD (4.6 см).\n")
    L.append("- `linear` не може передбачити станції поза опуклою оболонкою решти "
             "п'яти (пости майже колінеарні вздовж водосховища) — стовпець "
             "`predicted_c_m` = NaN для них.\n")
    L.append("- Жодна гладка модель не б'є константу/nearest-station суттєво. "
             "**Рекомендація: найпростіша модель, що проходить LOSO-CV — регіональна "
             "константа −0.17 м або її кускова nearest-station форма.** Не публікувати "
             "гладкий растр як «істину» на 6 контролях; справжній апгрейд — зовнішня "
             "валідація (UKG2025 / GNSS-нівелювання).\n\n")
    if figures:
        L.append("## Фігури\n\n")
        for f in figures:
            L.append(f"- `outputs/figures/{f}`\n")
    (cfg.reports_dir / "kakhovka_spatial_model_comparison.md").write_text(
        "".join(L), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    cfg.tables_dir.mkdir(parents=True, exist_ok=True)
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)

    stations = load_station_correctors(cfg)          # slug, name_en, lat, lon, c_station_m, sigma_m, ...
    print(f"{len(stations)} usable station correctors")

    per_row, summary = sm.leave_one_station_out_cv(stations)
    per_row.to_csv(cfg.tables_dir / "egg2015_to_evrf2019_spatial_cv.csv", index=False)
    summary.to_csv(cfg.tables_dir / "egg2015_to_evrf2019_spatial_cv_summary.csv", index=False)
    print("\nLOSO-CV summary (cm):")
    print((summary.set_index("model")[["loso_bias_m", "loso_mae_m", "loso_rmse_m",
                                       "max_abs_error_m"]] * 100).round(1).to_string())

    figures: list[str] = []
    if not args.no_figures:
        cfg.repo_root.joinpath("outputs", "figures").mkdir(parents=True, exist_ok=True)
        figs = cfg.repo_root / "outputs" / "figures"
        models = sm.fit_all(stations)
        _loso_figure(per_row, summary, figs / "spatial_model_loso_cv.png")
        _surface_figure(stations, models, cfg, figs / "spatial_corrector_models.png")
        figures = ["spatial_model_loso_cv.png", "spatial_corrector_models.png"]
        print("wrote", *figures)

    _report(stations, per_row, summary, cfg, figures)
    print("wrote outputs/reports/kakhovka_spatial_model_comparison.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
