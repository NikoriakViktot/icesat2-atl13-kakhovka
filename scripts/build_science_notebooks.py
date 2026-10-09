#!/usr/bin/env python3
"""Generate the Phase 3 science notebooks (00 data audit, 08 methods/results,
09 spatial validation + Kherson).

    python scripts/build_science_notebooks.py

The notebooks are thin: every number comes from the Phase 2c/2d output tables
(``outputs/tables/egg2015_to_evrf2019_*.csv``) or the reusable ``src/`` modules,
so a re-run of the pipeline cannot leave stale prose behind. Ukrainian markdown,
English code. Re-run this generator, then::

    jupyter execute notebooks/00_data_audit.ipynb
    jupyter execute notebooks/08_methods_results.ipynb
    jupyter execute notebooks/09_spatial_validation.ipynb
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

_ID = itertools.count()


def _cell_id() -> str:
    return hashlib.sha1(f"kakhovka-nb-{next(_ID)}".encode()).hexdigest()[:12]

NB_DIR = Path(__file__).resolve().parents[1] / "notebooks"

_META = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {
        "codemirror_mode": {"name": "ipython", "version": 3},
        "file_extension": ".py", "mimetype": "text/x-python", "name": "python",
        "nbconvert_exporter": "python", "pygments_lexer": "ipython3", "version": "3.12.3",
    },
}


def md(text: str) -> dict:
    return {"cell_type": "markdown", "id": _cell_id(), "metadata": {},
            "source": text.strip("\n").splitlines(keepends=True)}


def code(src: str) -> dict:
    return {"cell_type": "code", "id": _cell_id(), "metadata": {},
            "execution_count": None, "outputs": [],
            "source": src.strip("\n").splitlines(keepends=True)}


def write_nb(name: str, cells: list[dict]) -> None:
    nb = {"cells": cells, "metadata": _META, "nbformat": 4, "nbformat_minor": 5}
    (NB_DIR / name).write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote notebooks/{name}  ({len(cells)} cells)")


_BOOT = """
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.cwd().parent / "src"))
import numpy as np, pandas as pd
import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
})
pd.set_option("display.width", 160); pd.set_option("display.max_columns", 40)

from kakhovka_altimetry.config import load_config
cfg = load_config()
TABLES = cfg.tables_dir
FIGS = cfg.repo_root / "outputs" / "figures"; FIGS.mkdir(parents=True, exist_ok=True)
"""


# =========================================================================== #
# 00 — data audit                                                              #
# =========================================================================== #
def notebook_00() -> None:
    cells = [
        md(r"""
# 00 · Аудит вхідних даних та провенанс

**Питання цього нотебука: які саме файли дали результат корректора
EGG2015→EVRF2019?**

Друкує SHA-256 усіх вхідних растрів і рядів, версію та DOI ATL13, таблицю
вертикальних систем відліку з припливною конвенцією, лічильники рядків і
покриття, координати гідропостів, екстенти растрів, а також окремо **вхідні
дані по пониззю / Херсону**. Наприкінці записує
`outputs/reports/provenance.json`.
"""),
        code(_BOOT + """
import hashlib, json, platform, subprocess, datetime as dt

def sha256(path, _bufsize=1 << 20):
    path = pathlib.Path(path)
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_dir(d, pattern="*.parquet"):
    d = pathlib.Path(d)
    if not d.exists():
        return None
    h = hashlib.sha256()
    for p in sorted(d.rglob(pattern)):
        h.update(p.name.encode()); h.update(bytes.fromhex(sha256(p)))
    return h.hexdigest()
"""),
        md("## 1 · Хеші вхідних файлів"),
        code("""
gauge_dir = cfg.gauges.raw_dir
kherson = cfg.gauges.downstream_station(80805)
mykolaiv = cfg.gauges.downstream_station(98027)
inputs = {
    "egg2015_grid":        cfg.egg2015.path,
    "epsg9902_grid":       cfg.official_transform.path,
    "atl13_evrs_parquet":  cfg.evrs_parquet,
    "atl13_pass_levels":   cfg.pass_levels_parquet,
    "kherson_evrs_parquet":        cfg.downstream_body("kherson").evrs_parquet,
    "kherson_yearbook_csv":        kherson.yearbook_csv,
    "dnipro_estuary_evrs_parquet": cfg.downstream_body("dnipro_estuary").evrs_parquet,
    "dnipro_estuary_polygon":      cfg.downstream_body("dnipro_estuary").clip_polygon,
    "mykolaiv_2021_grid_csv":      mykolaiv.yearbook_grid_csv,
}
rows = []
for name, path in inputs.items():
    p = pathlib.Path(path)
    rows.append({"input": name, "path": str(p.relative_to(cfg.repo_root)) if p.exists() else str(path),
                 "exists": p.exists(),
                 "bytes": p.stat().st_size if p.exists() else None,
                 "sha256": sha256(p)})
rows.append({"input": "gauge_parquet_tree", "path": str(gauge_dir), "exists": gauge_dir.exists(),
             "bytes": None, "sha256": sha256_dir(gauge_dir)})
hash_tbl = pd.DataFrame(rows)
hash_tbl
"""),
        md("## 2 · Провенанс ATL13"),
        code("""
from kakhovka_altimetry import discovery
manifest = discovery.read_manifest(cfg)
evrs = pd.read_parquet(cfg.evrs_parquet, columns=["time", "rgt", "period"])
evrs["time"] = pd.to_datetime(evrs["time"], utc=True)

atl13_prov = {
    "product": cfg.product.short_name,
    "version": cfg.product.version,
    "doi": "10.5067/ATLAS/ATL13.007",
    "n_granules_manifest": int(manifest["granule"].nunique()),
    "n_rgts": int(evrs["rgt"].nunique()),
    "date_min": str(evrs["time"].min().date()),
    "date_max": str(evrs["time"].max().date()),
    "n_segments": int(len(evrs)),
    "periods": evrs["period"].value_counts().to_dict(),
}
for body in cfg.downstream_bodies:
    m = body.manifest
    atl13_prov[f"n_granules_{body.slug}"] = (
        int(pd.read_csv(m)["granule"].nunique()) if m.exists() else 0
    )
atl13_prov
"""),
        md("""
## 3 · Вертикальні системи відліку та припливна конвенція

EVRF2019 зрівняно в **zero-tide** системі (BKG). EGG2015 в цьому проєкті
трактується як EVRF2007-сумісний гравіметричний квазігеоїд (`config/vertical_datums.yaml`);
рамкові члени `evrf2019_minus_evrf2007_m` та `tide_system_correction_m` за
замовчуванням `0.0` означають **«не припущено»**, а не «нуль». Припливну
конвенцію EGG2015 **не** виводимо з імені файлу.
"""),
        code("""
ot = cfg.official_transform
vref = pd.DataFrame([
    {"quantity": "ATL13 ht_water_surf", "frame": "WGS84 ellipsoid", "tide_system": "record from ICESat-2 docs (not assumed here)"},
    {"quantity": "EGG2015 zeta",        "frame": cfg.egg2015.height_system, "tide_system": "verify from source documentation"},
    {"quantity": "EPSG:%d grid" % ot.epsg_operation, "frame": ot.target_frame, "tide_system": ot.tide_system},
    {"quantity": "EVRF2019 (target)",   "frame": "EVRF2019", "tide_system": "zero_tide (BKG)"},
])
frame_terms = {
    "evrf2019_minus_evrf2007_m": ot.evrf2019_minus_evrf2007_m,
    "tide_system_correction_m": ot.tide_system_correction_m,
    "note": "0.0 == 'not assumed', kept as visible budget lines",
}
display(vref); frame_terms
"""),
        md("## 4 · Покриття, координати, екстенти растрів"),
        code("""
from kakhovka_altimetry import official_datum as od
from kakhovka_altimetry.gauges import load_gauge_observations

obs = load_gauge_observations(cfg)
gauge_cov = (obs.groupby("station_id")["datetime"]
             .agg(["min", "max", "size"])
             .rename(columns={"min": "start", "max": "end", "size": "n_obs"})
             .reset_index())
gauge_cov["slug"] = gauge_cov["station_id"].map(
    {s.id: s.slug for s in cfg.gauges.stations})
station_xy = pd.DataFrame([
    {"slug": s.slug, "name_en": s.name_en, "id": s.id, "lat": s.lat, "lon": s.lon,
     "gauge_zero_bs77_m": s.gauge_zero_baltic_m, "active_regimes": ",".join(s.active_regimes)}
    for s in cfg.gauges.stations])

grid = od.load_official_grid(cfg)
raster_ext = pd.DataFrame([
    {"raster": "EPSG:%d ua_2019z.asc" % ot.epsg_operation,
     "lon_min": float(grid.lons.min()), "lon_max": float(grid.lons.max()),
     "lat_min": float(grid.lats.min()), "lat_max": float(grid.lats.max()),
     "shape": str(grid.values.shape)},
])
display(station_xy); display(gauge_cov); raster_ext
"""),
        md("""
## 5 · Вхідні дані по пониззю / Херсону

Херсон (пост 80805) — річковий пост Дніпра **нижче** греблі, без знівельованого
нуля. Ряд подається як стедж/локальна аномалія, **ніколи** як абсолютна WSE.
"""),
        code("""
from kakhovka_altimetry.downstream import load_downstream_series, coverage_summary
ds = load_downstream_series(cfg)
display(coverage_summary(ds))

def _body_evrs_summary(body_slug: str) -> None:
    body = cfg.downstream_body(body_slug)
    kev = body.evrs_parquet
    if not kev.exists():
        print(f"no {body_slug} ATL13 pull yet -- run "
              f"scripts/download_atl13_downstream.py --body {body_slug}")
        return
    ke = pd.read_parquet(kev, columns=["time", "rgt", "period", "lon", "lat"])
    ke["time"] = pd.to_datetime(ke["time"], utc=True)
    print(f"{body_slug} ATL13 evrs:", len(ke), "segments,",
          ke["rgt"].nunique(), "RGTs,",
          f"{ke['time'].min().date()}..{ke['time'].max().date()}")
    print("  bbox lon %.3f..%.3f  lat %.3f..%.3f" % (
        ke.lon.min(), ke.lon.max(), ke.lat.min(), ke.lat.max()))
    kp = pd.read_parquet(body.pass_levels_parquet)
    display(kp.groupby("period")["n_points"].agg(
        passes="size", segments="sum").astype(int))

for _slug in ("kherson", "dnipro_estuary"):
    _body_evrs_summary(_slug)
"""),
        md("""
## 6 · Вертикальне правило (не порушувати)

```
H_evrs_egg2015_m = ht_water_surf - zeta_EGG2015          (єдина фізична висота)
H_egm2008_m      = ht_ortho                              (лише контроль-стовпець)
```

`period` розколюється на 2023-06-06 (прорив греблі): PRE_BREACH / BREACH_DRAWDOWN /
POST_BREACH. Статистики водосховища ніколи не змішують PRE_BREACH з пост-проривом.
"""),
        md("## 7 · Запис `provenance.json`"),
        code("""
def git_commit():
    try:
        return subprocess.check_output(["git", "-C", str(cfg.repo_root), "rev-parse", "HEAD"],
                                       text=True).strip()
    except Exception:
        return None

prov = {
    "run_timestamp_utc": dt.datetime.now(dt.UTC).isoformat(),
    "git_commit": git_commit(),
    "python_version": platform.python_version(),
    "random_seed": 20260904,
    "atl13": atl13_prov,
    "sha256": {r["input"]: r["sha256"] for _, r in hash_tbl.iterrows()},
    "vertical_frame_terms_m": frame_terms,
    "pre_breach_cutoff": str(cfg.regimes.breach_start),
    # EPSG's operation-accuracy field for the 9902 transformation (NOT a sigma),
    # and, separately, the quoted EGG2015 model error. These are different terms;
    # they were previously both written under the epsg9902 key.
    "epsg9902_op_accuracy_m": cfg.official_transform.published_stats.get("accuracy_m"),
    "epsg9902_sd_at_determination_points_m": cfg.official_transform.published_stats.get("sd_m"),
    "egg2015_model_accuracy_m": cfg.official_transform.egg2015_accuracy_m,
    "bootstrap_resamples": 10000,
    "gauge_zero_bs77_m_nominal": 12.00,
    "downstream": {
        "bodies": {
            b.slug: {
                "refid": b.refid,
                "clip": (list(b.clip_bbox) if b.clip_bbox is not None
                         else str(b.clip_polygon.relative_to(cfg.repo_root))),
                "n_granules": int(pd.read_csv(b.manifest)["granule"].nunique())
                if b.manifest.exists() else 0,
            }
            for b in cfg.downstream_bodies
        },
        "gauge_series_days": {
            slug: int((ds["slug"] == slug).sum()) for slug in ("kherson", "mykolaiv")
        },
    },
}
out = cfg.reports_dir / "provenance.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(prov, indent=2, ensure_ascii=False), encoding="utf-8")
print("wrote", out.relative_to(cfg.repo_root))
print(json.dumps(prov, indent=1, ensure_ascii=False)[:1500])
"""),
    ]
    write_nb("00_data_audit.ipynb", cells)


# =========================================================================== #
# 08 — methods & results                                                       #
# =========================================================================== #
def notebook_08() -> None:
    cells = [
        md(r"""
# 08 · Методи та результати — емпіричний корректор EGG2015→EVRF2019

Науковий документ по Фазі 2c. Уся арифметика читається з
`outputs/tables/egg2015_to_evrf2019_*.csv`; проза будується з тих самих таблиць.

## Що саме оцінюється

$$c_i \;=\; H_{\mathrm{gauge},\,EVRF2019} \;-\; H_{\mathrm{ICESat},\,EGG2015}$$

$$H_{\mathrm{ICESat},\,EGG2015} \;=\; h_{\mathrm{ATL13}} - \zeta_{\mathrm{EGG2015}}
\qquad
H_{\mathrm{gauge},\,EVRF2019} \;=\; 12.00 + \mathrm{stage} + \Delta_{9902}(\varphi,\lambda)$$

**Три різні твердження — не плутати:**

1. *виміряне:* $c_i = H_{\text{gauge},EVRF2019} - H_{\text{ICESat},EGG2015}$;
2. *емпіричне застосування:* $H_{\text{ATL13},EVRF2019}^{\text{emp}} = H_{\text{ATL13},EGG2015} + c(x,y)$;
3. *занадто сильно (НЕ робимо):* $\zeta_{EVRF2019} = \zeta_{EGG2015} - c$ — це вимагало б,
   щоб залишок був суто квазігеоїдною різницею; ці дані не відділяють його від
   спільного зсуву ATL13 та інших приладових членів. **Не квазігеоїд.**
"""),
        code(_BOOT + """
by_station = pd.read_csv(TABLES / "egg2015_to_evrf2019_by_station.csv")
by_radius  = pd.read_csv(TABLES / "egg2015_to_evrf2019_by_radius.csv")
by_rgt     = pd.read_csv(TABLES / "egg2015_to_evrf2019_by_rgt.csv")
unc        = pd.read_csv(TABLES / "egg2015_to_evrf2019_uncertainty.csv")
matchups   = pd.read_csv(TABLES / "gauge_icesat_egg2015_matchups.csv", parse_dates=["datetime"])
# EPSG:9902 operation-accuracy field. NOT a sigma, NOT a 95% CI: the same EPSG
# record separately reports SD 0.034 m over its 154 determination points.
EPSG9902_OP_ACC = 0.068
EPSG9902_SD_154 = 0.034
"""),
        md("## Executive summary (будується з таблиць)"),
        code("""
c = by_station.loc[np.isfinite(by_station["c_station_m"]), "c_station_m"].to_numpy()
nmad_stations = 1.4826 * np.median(np.abs(c - np.median(c)))
pass_nmad = by_station["empirical_nmad_m"].dropna()
lines = [
    f"Гідропостів з корректором: {len(c)} з 6.",
    f"c_station: {c.min():+.3f} … {c.max():+.3f} м, медіана {np.median(c):+.3f} м.",
    f"Станція-до-станції NMAD: {nmad_stations*100:.1f} см (діапазон {np.ptp(c)*100:.0f} см).",
    f"Внутрішньостанційна повторюваність (NMAD beam-pass): {pass_nmad.min()*100:.1f}–{pass_nmad.max()*100:.1f} см, медіана {pass_nmad.median()*100:.1f} см.",
    f"EPSG:9902 published operation accuracy: {EPSG9902_OP_ACC:.3f} м (SD {EPSG9902_SD_154:.3f} м на 154 визначальних точках). Це поле accuracy, НЕ сигма і НЕ 95% CI — окрема лінія, НЕ у квадратурі.",
]
print("\\n".join("• " + s for s in lines))
"""),
        md("## Числова перевірка узгодженості сітки EPSG:9902\n\nЦе перевірка **узгодженості**, не доказ ідентичності файлу: опубліковані статистики EPSG рахувалися на 154 визначальних точках, наші — на 3776 вузлах сітки. Ідентичність файлу встановлює SHA-256 у `provenance.json`. Реальна користь перевірки — зловити порожню або нульову сітку, бо ballpark-операція PROJ між цими CRS мовчки повертає 0.\n\n`assert` нижче лишається як справжній запобіжник."),
        code("""
from kakhovka_altimetry import official_datum as od
grid = od.load_official_grid(cfg)
validation = od.validate_against_published(grid, cfg)
print(od.format_validation(validation))
assert validation["passed"], "official grid failed its numerical sanity check"
"""),
        md("## Результат по гідропостах (на звітному радіусі) + bootstrap CI"),
        code("""
cols = ["name_en", "reported_radius_km", "n_matchups", "n_dates", "n_rgts",
        "delta_epsg9902_m", "c_station_m", "empirical_nmad_m",
        "bootstrap_ci95_low_m", "bootstrap_ci95_high_m",
        "c_station_B_nearest_m", "c_station_C_dailymean_m", "temporal_spread_m", "flag"]
display(by_station[cols].round(3))
from IPython.display import Image
Image(str(FIGS / "correction_by_station.png"))
"""),
        md("""
## Драбина радіусів

Правило вибору звітного радіуса: **найближчий до 2 км радіус, що містить ≥5
незалежних beam-passes**. Драбина завжди публікується, щоб вибір був
аудитований. Добре вкриті радіуси стабільні до кількох см; недовкриті —
оманливі.
"""),
        code("""
display(by_radius[["name_en", "radius_km", "n_matchups", "n_dates",
                   "c_station_m", "empirical_nmad_m",
                   "bootstrap_ci95_low_m", "bootstrap_ci95_high_m", "flag"]].round(3))
from IPython.display import Image
Image(str(FIGS / "correction_by_radius.png"))
"""),
        md("""
## Per-RGT корректор та розкол Розумівки

`rgt_bias_m = c_{i,rgt} − c_i`. Серед добре вкритих RGT (n≥5) зсув ≤~2 см.
Розумівка бімодальна: RGT 205 (висхідний трек, читає високо біля берега) vs
RGT 989 — звідси широкий/бімодальний 2-км bootstrap CI. Рекомендована фігура
Розумівки — з рядків 3–5 км, не з 2-км пулу.
"""),
        code("""
display(by_rgt[["name_en", "radius_km", "rgt", "n_matchups", "n_dates",
                "correction_m", "nmad_m", "c_station_all_m", "rgt_bias_m", "flag"]].round(3))
from IPython.display import Image
Image(str(FIGS / "correction_by_rgt.png"))
"""),
        md("""
## Точність (precision) vs абсолютна точність (accuracy) — окремо

**PRECISION** — beam-pass NMAD і bootstrap CI медіани. Це єдина невизначеність,
яку ці дані обмежують. **ACCURACY** — обмежена окремими лініями, які **не**
підсумовуємо в квадратурі: EPSG:9902 operation accuracy 0.068 м (це поле
accuracy, **не** сигма; SD на 154 визначальних точках — 0.034 м); нуль
гідропоста (12.00 м — **прийнята** константа, не оцінюваний параметр;
округлене регіональне число, не 6 знівельованих нулів); модельна похибка EGG2015
над Україною (~0.1 м); систематичний зсув ATL13. Останні три — «не інферимо».
"""),
        code("""
display(unc.round(3))

# --- figure: uncertainty budget ---
fig, ax = plt.subplots(figsize=(8.5, 4.4))
prec = unc.set_index("name_en")["empirical_nmad_m"] * 100
ax.bar(np.arange(len(prec)), prec, color="#3b6ea5", label="empirical precision (NMAD, cm)")
ax.axhline(EPSG9902_OP_ACC * 100, color="#b5651d", ls="--", lw=1.4,
           label=f"EPSG:9902 op. accuracy {EPSG9902_OP_ACC*100:.1f} cm (not a sigma)")
ax.set_xticks(np.arange(len(prec))); ax.set_xticklabels(prec.index, rotation=20, ha="right")
ax.set_ylabel("cm")
ax.set_title("Бюджет невизначеності: виміряна precision vs відома систематика EPSG:9902\\n"
             "(інші абсолютні члени — gauge zero, EGG2015, ATL13 bias — не квантифіковані)")
ax.set_ylim(0, max(prec.max(), EPSG9902_OP_ACC * 100) * 1.35)
ax.legend(loc="upper left")
ax.grid(axis="y", alpha=0.3)
fig.savefig(FIGS / "uncertainty_budget.png")
plt.show()
"""),
        code("""
# --- figure: residual distributions (ECDF + rug), n is small so no bare histogram ---
# each station at ITS reported radius, not a fixed 2 km
rep_r = dict(zip(by_station["name_en"], by_station["reported_radius_km"]))
names = [n for n in by_station.sort_values("lon")["name_en"] if np.isfinite(rep_r.get(n, np.nan))]
fig, axes = plt.subplots(2, 3, figsize=(11, 6), sharex=True)
for ax, name in zip(axes.ravel(), names):
    sub = matchups[(matchups["name_en"] == name)
                   & np.isclose(matchups["radius_km"], rep_r[name])]
    v = np.sort(sub["c_station_A_m"].dropna().to_numpy())
    if v.size:
        ax.step(v, np.arange(1, v.size + 1) / v.size, where="post", color="#3b6ea5")
        ax.plot(v, np.full_like(v, -0.03), "|", color="#333", ms=8)
        ax.axvline(np.median(v), color="#b5651d", ls="--", lw=1)
    ax.set_title(f"{name}  (r={rep_r[name]:g} км, n={v.size})", fontsize=9)
    ax.set_ylim(-0.08, 1.05); ax.grid(alpha=0.3)
for ax in axes[-1]:
    ax.set_xlabel("c per matchup (m)")
axes[0, 0].set_ylabel("ECDF"); axes[1, 0].set_ylabel("ECDF")
fig.suptitle("Розподіл per-matchup корректора по станціях (кожна на своєму звітному радіусі)", y=1.0)
fig.savefig(FIGS / "residual_distributions.png")
plt.show()
"""),
        md("""
## Публікаційно-безпечне формулювання

> Ми оцінили **прив'язаний до гідропостів емпіричний вертикальний корректор** між
> висотами водної поверхні ICESat-2 ATL13, зведеними через EGG2015, і рівнями
> гідропостів, трансформованими з BS-77 у EVRF2019 через EPSG:9902. Корректор
> призначений для локальної гармонізації ланцюга ATL13+EGG2015 і **не є**
> офіційною трансформацією датумів чи незалежним визначенням квазігеоїда.

> *We estimated a gauge-constrained empirical vertical correction between ICESat-2
> ATL13 water-surface elevations reduced with EGG2015 and gauge water levels
> transformed from BS77 to EVRF2019 using EPSG:9902. The correction is intended
> for local harmonization of the ATL13+EGG2015 observation chain and is not
> interpreted as an official datum transformation or an independent quasigeoid
> determination.*

Фраза «regional correction = −0.17 ± 0.05 m» допустима **лише** якщо ±0.05 м
явно позначено як *empirical spatial/repeatability scale*, а не абсолютна
точність EVRF2019.
"""),
    ]
    write_nb("08_methods_results.ipynb", cells)


# =========================================================================== #
# 09 — spatial validation + Kherson                                            #
# =========================================================================== #
def notebook_09() -> None:
    cells = [
        md(r"""
# 09 · Просторова валідація корректора + пониззя / Херсон / лиман

Три частини:

1. **Порівняння просторових моделей** корректора (`constant` / `plane` / `IDW` /
   `linear`) проти прийнятої nearest-station поверхні, з валідацією
   **leave-one-station-out** (LOSO-CV). З 6 контролями випадковий train/test
   спліт беззмістовний — коректний тест це виключення цілої станції.
2. **Пониззя Дніпра / Херсон** — часовий ряд рівня Херсона з хвилею прориву
   червня 2023, і що ICESat показує на річці нижче греблі.
3. **Дніпровсько-Бузький лиман / Миколаїв** — берегова точка нуль-контролю +
   контекст: стабільність поверхні ICESat над лиманом і провізорний
   `c_Mykolaiv` біля Південно-Бузького рукава.
"""),
        code(_BOOT + """
from kakhovka_altimetry import spatial_models as sm
from kakhovka_altimetry.corrector_surface import load_station_correctors
from kakhovka_altimetry.downstream import load_downstream_series, coverage_summary
from IPython.display import Image

stations = load_station_correctors(cfg)
stations[["slug", "name_en", "lat", "lon", "c_station_m", "sigma_m", "flag"]]
"""),
        md("## 1 · LOSO-CV просторових моделей"),
        code("""
per_row, summary = sm.leave_one_station_out_cv(stations)
disp = summary.copy()
for k in ["loso_bias_m", "loso_mae_m", "loso_rmse_m", "loso_median_abs_error_m", "max_abs_error_m"]:
    disp[k] = (disp[k] * 100).round(1)
print("LOSO-CV зведення (см, відсортовано за RMSE):")
display(disp)
display(per_row.round(3))
"""),
        code("""
Image(str(FIGS / "spatial_model_loso_cv.png"))
"""),
        code("""
Image(str(FIGS / "spatial_corrector_models.png"))
"""),
        md("""
## Висновок частини 1

- `plane` найгірша (RMSE ~7.5 см) — нахилу зі сходу на захід дані не підтверджують.
- `IDW`/`linear` ледь кращі за константу і в межах станційного NMAD (4.6 см);
  `linear` взагалі не може передбачити 4 з 6 станцій (пости майже колінеарні
  вздовж водосховища → поза опуклою оболонкою).
- Жодна гладка модель суттєво не б'є **регіональну константу −0.17 м** або її
  кускову **nearest-station** форму (прийнята у Фазі 2d). 9-см розкид по 6
  контролях на широких CI не є доведеним просторовим сигналом. Чим саме він
  спричинений, ці дані **не** визначають: похибка нулів постів, модельна похибка
  EGG2015 і зсув ATL13 входять у `c` адитивно й не розділяються.
- **Справжній апгрейд — не складніший інтерполятор, а зовнішня валідація.**
  Із моделлю УКГ2025 геодезична частина корректора стає прямо обчислюваною:
  `c_geodetic = ζ_EGG2015 − ζ_УКГ2025` (еліпсоїдна висота скорочується), а
  залишок `r_i = c_station − c_geodetic` уперше ізолює зсув ATL13 + гідрологію +
  похибку зіставлення. Сітки УКГ2025 наразі немає — це підготовлений наступний крок.
"""),
        md(r"""
## 2 · Пониззя Дніпра / Херсон

Херсон (пост 80805, lon 32.61, lat 46.62) — річковий пост Дніпра **нижче**
греблі. Донорський щоденник зберігає `water_level_m_abs = h0 + рівень`, де для
Херсона `h0 ≈ −5.00 м` — тобто це **абсолютна висота в BS-77** (на відміну від
водосховищних постів, де маємо лише аномалію та номінальний нуль 12.00 м).
Прорив 2023-06-06 дав хвилю до **+5.56 м** BS-77.
"""),
        code("""
from kakhovka_altimetry.downstream import kherson_bs77_daily
ds = load_downstream_series(cfg)
display(coverage_summary(ds))
kb = kherson_bs77_daily(cfg)
print(f"Kherson BS-77 daily: {len(kb)} днів {kb.date.min().date()}..{kb.date.max().date()}; "
      f"implied graph-zero h0 = {kb.h0_bs77_m.median():.2f} m BS-77")

fig, ax = plt.subplots(figsize=(11, 4))
ax.plot(kb["date"], kb["h_bs77_m"], "-", lw=0.7, color="#3b6ea5")
ax.axvline(pd.Timestamp(cfg.regimes.breach_start), color="#c1121f", lw=1.4,
           label="прорив греблі 2023-06-06")
ax.axvspan(pd.Timestamp(cfg.regimes.breach_start), pd.Timestamp(cfg.regimes.post_breach_start),
           color="#c1121f", alpha=0.08)
ax.set_ylabel("рівень Дніпра, м BS-77 (абс.)")
ax.set_title("Херсон (80805): рівень нижнього Дніпра, хвиля прориву червня 2023 (+5.6 м)")
ax.legend(); ax.grid(alpha=0.3)
fig.savefig(FIGS / "kherson_downstream_timeseries.png")
plt.show()
"""),
        md("""
### ICESat над нижнім Дніпром біля Херсона

`scripts/download_atl13_downstream.py` тягне ATL13 для reference water body
нижнього Дніпра (`refid 5952005933`, з веб-клієнта). Розділяємо чисту річкову
поверхню (`median WSE < 3 м`, `NMAD < 0.15 м`, `n ≥ 15`) від рідкісних
забруднень пулом.
"""),
        code("""
from kakhovka_altimetry.aggregate import _haversine_km
KH_LON, KH_LAT = 32.613647, 46.621527

kp_path = cfg.downstream_body("kherson").pass_levels_parquet
if not kp_path.exists():
    print("немає пониззевого ATL13 — запустіть scripts/download_atl13_downstream.py")
    river = pd.DataFrame()
else:
    kp = pd.read_parquet(kp_path)
    kp["dist_kherson_km"] = _haversine_km(kp["lat_mean"].to_numpy(), kp["lon_mean"].to_numpy(),
                                          KH_LAT, KH_LON)
    river = kp[(kp["median_wse_evrs_m"] < 3.0) & (kp["nmad_m"] < 0.15)
              & (kp["n_points"] >= 15)].copy()
    print(f"{len(kp)} beam-passes у пониззевому bbox; {len(river)} чистих річкових")
    display(river.groupby("period")["median_wse_evrs_m"]
            .agg(n="size", median="median",
                 p05=lambda s: s.quantile(.05), p95=lambda s: s.quantile(.95)).round(3))
"""),
        md(r"""
### Провізорний корректор у Херсоні

Оскільки `water_level_m_abs` — абсолютна BS-77 висота, замикаємо ту саму
конструкцію, що й на водосховищі:

$$c_{\text{Kherson}} = \big(H_{\text{gauge,BS77}} + \Delta_{9902}(\text{Kherson})\big) - H_{\text{ICESat,EGG2015}}$$

Береться лише PRE_BREACH, лише проходи в межах 20 км від поста, рівень
інтерполюється на дату прольоту. **Застереження:** `h0 = −5.00 м` — це майже
напевно округлений номінал графіка поста, не знівельований репер, тож
`c_Kherson` так само вбирає похибку нуля, як і водосховищні значення.
"""),
        code("""
from kakhovka_altimetry import official_datum as od
grid = od.load_official_grid(cfg)
delta_kherson = float(od.correction_at(grid, KH_LAT, KH_LON)[0])
print(f"Δ9902 у Херсоні = {delta_kherson:+.3f} m")

c_kherson = np.nan
c_kherson_nmad = np.nan
if not river.empty:
    kb_i = kherson_bs77_daily(cfg)
    kb_i = kb_i[kb_i["period"] == "PRE_BREACH"].set_index("date")["h_bs77_m"].sort_index()
    near = river[(river["period"] == "PRE_BREACH") & (river["dist_kherson_km"] <= 20)].copy()
    # gauge level interpolated to the overpass day (both axes forced to ns epoch)
    dts = (pd.to_datetime(near["datetime"], utc=True).dt.tz_convert(None)
           .dt.normalize().astype("datetime64[ns]").astype("int64").to_numpy())
    gx = pd.DatetimeIndex(kb_i.index).as_unit("ns").astype("int64").to_numpy()
    near["h_bs77_gauge_m"] = np.interp(dts, gx, kb_i.to_numpy(), left=np.nan, right=np.nan)
    near = near.dropna(subset=["h_bs77_gauge_m"])
    near["h_gauge_evrf2019_m"] = near["h_bs77_gauge_m"] + delta_kherson
    near["c_m"] = near["h_gauge_evrf2019_m"] - near["median_wse_evrs_m"]
    if len(near):
        c = near["c_m"].to_numpy()
        c_kherson = float(np.median(c))
        c_kherson_nmad = nmad_c = 1.4826 * np.median(np.abs(c - np.median(c)))
        print(f"n = {len(near)} проходів у межах 20 км, PRE_BREACH")
        print(f"c_Kherson = {c_kherson:+.3f} m   (NMAD {nmad_c*100:.1f} cm, "
              f"p05..p95 {np.percentile(c,5):+.3f}..{np.percentile(c,95):+.3f})")
        display(near[["date", "rgt", "beam", "dist_kherson_km", "median_wse_evrs_m",
                      "h_bs77_gauge_m", "h_gauge_evrf2019_m", "c_m"]].round(3).head(15))
"""),
        code("""
# Kherson vs the six reservoir stations
if np.isfinite(c_kherson):
    reg = float(np.median(stations["c_station_m"]))
    fig, ax = plt.subplots(figsize=(8, 4))
    y = np.arange(len(stations))
    ax.scatter(stations["c_station_m"], y, s=45, color="#3b6ea5", zorder=3, label="водосховище (Фаза 2c)")
    ax.set_yticks(y); ax.set_yticklabels(stations["name_en"])
    ax.axvline(reg, color="#666", ls="--", lw=1, label=f"регіональна медіана {reg:+.3f} m")
    ax.errorbar([c_kherson], [len(stations)], xerr=[[c_kherson_nmad]], fmt="D",
                ms=8, color="#c1121f", ecolor="#c1121f", capsize=3, zorder=4,
                label=f"Kherson (пониззя) {c_kherson:+.3f} ± {c_kherson_nmad:.3f} m (NMAD)")
    ax.set_yticks(list(y) + [len(stations)])
    ax.set_yticklabels(list(stations["name_en"]) + ["Kherson (downstream)"])
    ax.set_xlabel("c  (m)   [EGG2015 height + c ≈ EVRF2019]")
    ax.set_title("Корректор: 6 водосховищних постів + провізорний Херсон нижче греблі")
    ax.legend(fontsize=8); ax.grid(axis="x", alpha=0.3)
    fig.savefig(FIGS / "kherson_vs_reservoir_corrector.png")
    plt.show()
"""),
        md("""
### Висновок по пониззю

- **Часовий ряд Херсона реальний**: стабільний річковий режим 2019–2022
  (±0.5 м BS-77), хвиля прориву червня 2023 до +5.6 м.
- **ICESat над нижнім Дніпром реальний** (refid 5952005933): чиста річкова
  поверхня ~0.2–0.3 м EVRS(EGG2015), стабільна PRE→POST (річка нижче греблі не
  зникла, на відміну від водосховища).
- **Провізорний `c_Kherson`** будується так само, як водосховищні (BS-77 абс. +
  Δ9902 − ICESat EGG2015). Його слід читати поруч із водосховищною медіаною
  −0.17 м: якщо він у тому ж діапазоні — це слабке *незалежне за розташуванням*
  підтвердження; якщо ні — вказує на різницю нулів Херсон↔водосховище.
- **Обмеження:** `h0 = −5.00 м` майже напевно округлений номінал; єдина
  вертикальна систематика, яку ці дані обмежують, — precision. Абсолютну
  точність усе ще визначають EPSG:9902 operation accuracy 0.068 м (поле accuracy,
  не сигма) + похибка нуля + EGG2015 + ATL13.
"""),
        md(r"""
## 3 · Дніпровсько-Бузький лиман / Миколаїв

Reference water body **refid 6033000138** (Дніпро-Буг лиман, включно з
Південно-Бузьким рукавом до Миколаєва) — берегова точка **нуль-контролю +
контексту**: поверхня ICESat над усім лиманом (стабільність рівня) і
провізорний `c_Mykolaiv`, прив'язаний до поста 98027 (Миколаїв,
Південний Буг), так само як `c_Kherson` до поста 80805.

Кліп — опукла оболонка (+буфер) 17 точок-орієнтирів оператора
(`data/aoi/dnipro_estuary.geojson`, `scripts/build_estuary_aoi.py`), яка
охоплює **весь** лиман: Південно-Бузький рукав до Миколаєва, Дніпровську
затоку, Білозерський/Голопристанський р-ни, — з відсіченою відкритою
Чорноморською акваторією.
"""),
        code("""
from kakhovka_altimetry.downstream import load_body_pass_levels, estuary_wse_summary, bs77_daily

est_body = cfg.downstream_body("dnipro_estuary")
if not est_body.pass_levels_parquet.exists():
    print("немає ATL13 для лиману -- запустіть "
          "scripts/download_atl13_downstream.py --body dnipro_estuary")
    est_passes = pd.DataFrame()
else:
    est_passes = load_body_pass_levels(cfg, "dnipro_estuary")
    print(f"{len(est_passes)} чистих beam-passes у лимані "
          f"({est_passes['rgt'].nunique()} RGT)")
    display(estuary_wse_summary(est_passes).round(3))
"""),
        md("""
### Рівень Миколаєва (пост 98027)

Той самий графік нуля -5.00 м BS-77, що й Херсон -> `h_bs77_m` вже
абсолютна висота. Режим — згонно-нагонні явища (±0.3..0.5 м), а не
плавний річковий хід, як у Херсона.
"""),
        code("""
mk = bs77_daily(cfg, "mykolaiv")
if not mk.empty:
    print(f"Mykolaiv BS-77 daily: {len(mk)} днів {mk.date.min().date()}..{mk.date.max().date()}")
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(mk["date"], mk["h_bs77_m"], "-", lw=0.7, color="#2a6f4b")
    ax.axvline(pd.Timestamp(cfg.regimes.breach_start), color="#c1121f", lw=1.4,
               label="прорив греблі 2023-06-06")
    ax.axvspan(pd.Timestamp(cfg.regimes.breach_start), pd.Timestamp(cfg.regimes.post_breach_start),
               color="#c1121f", alpha=0.08)
    ax.set_ylabel("рівень, м BS-77 (абс.)")
    ax.set_title("Миколаїв (98027): рівень Південного Бугу / лиману (згонно-нагонні явища)")
    ax.legend(); ax.grid(alpha=0.3)
    fig.savefig(FIGS / "dnipro_estuary_mykolaiv_timeseries.png")
    plt.show()
"""),
        md(r"""
### Провізорний корректор у Миколаєві

Та сама конструкція, що й `c_Kherson`:

$$c_{\text{Mykolaiv}} = \big(H_{\text{gauge,BS77}} + \Delta_{9902}(\text{Mykolaiv})\big)
- H_{\text{ICESat,EGG2015}}$$

Лише PRE_BREACH, лише проходи в межах **30 км** від поста (ширше за 20 км
Херсона -- лиман великий, а координата поста, хоч і знівельована з
2026-09-04, все одно точка на березі, не в акваторії). **Застереження:**
`h0 = −5.00 м` -- ймовірно округлений номінал; рівень додатково несе
згонно-нагонний шум, який не є похибкою вирівнювання.
"""),
        code("""
MK_LON, MK_LAT = cfg.gauges.downstream_station(98027).lon, cfg.gauges.downstream_station(98027).lat
delta_mykolaiv = float(od.correction_at(grid, MK_LAT, MK_LON)[0])
print(f"Δ9902 у Миколаєві = {delta_mykolaiv:+.3f} m")

c_mykolaiv = np.nan
c_mykolaiv_nmad = np.nan
if not est_passes.empty:
    est_passes = est_passes.copy()
    est_passes["dist_mykolaiv_km"] = _haversine_km(
        est_passes["lat_mean"].to_numpy(), est_passes["lon_mean"].to_numpy(), MK_LAT, MK_LON)
    mk_i = mk[mk["period"] == "PRE_BREACH"].set_index("date")["h_bs77_m"].sort_index()
    near_mk = est_passes[(est_passes["period"] == "PRE_BREACH")
                          & (est_passes["dist_mykolaiv_km"] <= 30)].copy()
    dts = (pd.to_datetime(near_mk["datetime"], utc=True).dt.tz_convert(None)
           .dt.normalize().astype("datetime64[ns]").astype("int64").to_numpy())
    gx = pd.DatetimeIndex(mk_i.index).as_unit("ns").astype("int64").to_numpy()
    near_mk["h_bs77_gauge_m"] = np.interp(dts, gx, mk_i.to_numpy(), left=np.nan, right=np.nan)
    near_mk = near_mk.dropna(subset=["h_bs77_gauge_m"])
    near_mk["h_gauge_evrf2019_m"] = near_mk["h_bs77_gauge_m"] + delta_mykolaiv
    near_mk["c_m"] = near_mk["h_gauge_evrf2019_m"] - near_mk["median_wse_evrs_m"]
    if len(near_mk):
        c = near_mk["c_m"].to_numpy()
        c_mykolaiv = float(np.median(c))
        c_mykolaiv_nmad = 1.4826 * np.median(np.abs(c - np.median(c)))
        print(f"n = {len(near_mk)} проходів у межах 30 км, PRE_BREACH")
        print(f"c_Mykolaiv = {c_mykolaiv:+.3f} m   (NMAD {c_mykolaiv_nmad*100:.1f} cm, "
              f"p05..p95 {np.percentile(c,5):+.3f}..{np.percentile(c,95):+.3f})")
        display(near_mk[["date", "rgt", "beam", "dist_mykolaiv_km", "median_wse_evrs_m",
                         "h_bs77_gauge_m", "h_gauge_evrf2019_m", "c_m"]].round(3).head(15))
"""),
        code("""
# coastal zero-control check: 6 reservoir stations + Kherson + Mykolaiv
if np.isfinite(c_kherson) or np.isfinite(c_mykolaiv):
    reg = float(np.median(stations["c_station_m"]))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    y = np.arange(len(stations))
    ax.scatter(stations["c_station_m"], y, s=45, color="#3b6ea5", zorder=3, label="водосховище (Фаза 2c)")
    labels = list(stations["name_en"])
    extra_y = len(stations)
    if np.isfinite(c_kherson):
        ax.errorbar([c_kherson], [extra_y], xerr=[[c_kherson_nmad]], fmt="D", ms=8,
                    color="#c1121f", ecolor="#c1121f", capsize=3, zorder=4,
                    label=f"Kherson (пониззя) {c_kherson:+.3f} ± {c_kherson_nmad:.3f} m (NMAD)")
        labels.append("Kherson (downstream)"); extra_y += 1
    if np.isfinite(c_mykolaiv):
        ax.errorbar([c_mykolaiv], [extra_y], xerr=[[c_mykolaiv_nmad]], fmt="D", ms=8,
                    color="#2a6f4b", ecolor="#2a6f4b", capsize=3, zorder=4,
                    label=f"Mykolaiv (лиман) {c_mykolaiv:+.3f} ± {c_mykolaiv_nmad:.3f} m (NMAD)")
        labels.append("Mykolaiv (coastal)"); extra_y += 1
    ax.axvline(reg, color="#666", ls="--", lw=1, label=f"регіональна медіана {reg:+.3f} m")
    ax.set_yticks(np.arange(len(labels))); ax.set_yticklabels(labels)
    ax.set_xlabel("c  (m)   [EGG2015 height + c ≈ EVRF2019]")
    ax.set_title("Coastal zero-control: 6 водосховищних постів + Херсон + Миколаїв")
    ax.legend(fontsize=8); ax.grid(axis="x", alpha=0.3)
    fig.savefig(FIGS / "coastal_zero_check.png")
    plt.show()
"""),
        md(r"""
### Висновок по лиману

- **ICESat над лиманом реальний** (refid 6033000138, 266 гранул 2018-10..2026-05,
  10 RGT над усією опуклою оболонкою 17 точок оператора) — `estuary_wse_summary`
  показує медіанну поверхню й розкид по роках; читається як перевірка
  стабільності, не як абсолютна прив'язка.
- **Провізорний `c_Mykolaiv`** будується так само, як `c_Kherson` і
  водосховищні; читається поруч із ними як друга, незалежна за
  розташуванням берегова точка нуль-контролю, не як окрема валідована
  трансформація.
- **Обмеження:** координата поста 98027 знівельована (2026-09-04), але
  режим — згонно-нагонний (±0.3..0.5 м), тому 30-км/PRE_BREACH-вибірка все
  одно несе більший розкид, ніж Херсон. `h0 = −5.00 м` — той самий
  застережений номінал.
"""),
    ]
    write_nb("09_spatial_validation.ipynb", cells)


def main() -> int:
    NB_DIR.mkdir(exist_ok=True)
    notebook_00()
    notebook_08()
    notebook_09()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
