"""Phase 3 — river / estuary gauge series BELOW the Kakhovka dam.

Two coastal posts carry a genuine **absolute BS-77 height** (graph zero
``h0 = -5.00 m``, so ``H_BS77 = -5.00 + level_cm/100``): **Kherson** (80805, lower
Dnipro) and **Mykolaiv** (98027, Southern Bug at the Dnipro-Buh liman). Both are
wind-setup/setdown ("згонно-нагонні") dominated and sit near sea level. Nova
Kakhovka-Dnipro (80802) has no series.

Donor sources, stitched per post (earlier wins on an overlapping date):

* ``yearbook_csv``            — daily ``water_level_cm`` + ``water_level_m_abs``
  (already ``h0 + cm/100``), Kherson 2019-2023.
* ``yearbook_grid_csv``       — hand-transcribed day x month cm grid, Mykolaiv 2021.
* ``parquet_dir/year=*``      — donor term readings (``h_08``/``h_20``/``h_mean``),
  Kherson 2025.
* ``parquet_versions_root``   — donor version-fragmented ``level`` parquet
  (``version=*/{daily,monthly}/post_id=<id>``), Mykolaiv 2019/2020/2023.

The graph zeros are very likely rounded nominals, not surveyed benchmarks, so a
corrector built from either still absorbs a gauge-zero error — and Mykolaiv's
coordinate is a city-centre approximation, an extra caveat on ``c_Mykolaiv``.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .config import Config, DownstreamStation

_SRC_COLS = ["date", "h_cm", "h_m_local", "h_bs77_m", "source"]

SERIES_COLUMNS = [
    "date", "station_id", "slug", "name_en",
    "h_cm", "h_m_local", "h_bs77_m", "source", "period", "post_breach",
]

# earlier = preferred when two sources give the same date
_SOURCE_PRIORITY = {
    "yearbook_csv": 0, "yearbook_grid": 1,
    "donor_parquet": 2, "donor_parquet_versioned": 3,
}


def _empty_src() -> pd.DataFrame:
    return pd.DataFrame(columns=_SRC_COLS)


def _h_bs77(h_cm: pd.Series, st: DownstreamStation) -> pd.Series:
    if st.gauge_zero_baltic_m is None:
        return pd.Series(np.nan, index=h_cm.index)
    return st.gauge_zero_baltic_m + pd.to_numeric(h_cm, errors="coerce") / 100.0


def _from_yearbook(st: DownstreamStation) -> pd.DataFrame:
    if st.yearbook_csv is None or not st.yearbook_csv.exists():
        return _empty_src()
    df = pd.read_csv(st.yearbook_csv, parse_dates=["date"])
    if "stat_type" in df.columns:
        df = df[df["stat_type"].astype(str) == "daily"]
    h_cm = pd.to_numeric(df.get("water_level_cm"), errors="coerce")
    abs_m = pd.to_numeric(df.get("water_level_m_abs"), errors="coerce")
    # water_level_m_abs is already h0 + cm/100 -> a genuine absolute BS-77 height
    return pd.DataFrame({
        "date": pd.to_datetime(df["date"]).astype("datetime64[ns]"),
        "h_cm": h_cm.to_numpy(),
        "h_m_local": abs_m.to_numpy(),
        "h_bs77_m": abs_m.to_numpy(),
        "source": "yearbook_csv",
    }).dropna(subset=["date"])


def _from_yearbook_grid(st: DownstreamStation) -> pd.DataFrame:
    if st.yearbook_grid_csv is None or not st.yearbook_grid_csv.exists():
        return _empty_src()
    year_m = re.search(r"(19|20)\d{2}", st.yearbook_grid_csv.stem)
    if not year_m:
        return _empty_src()
    year = int(year_m.group(0))
    grid = pd.read_csv(st.yearbook_grid_csv, comment="#")
    month_cols = [c for c in grid.columns if re.fullmatch(r"m\d{2}", str(c))]
    long = grid.melt(id_vars="day", value_vars=month_cols,
                     var_name="m", value_name="h_cm").dropna(subset=["h_cm"])
    long["month"] = long["m"].str.slice(1).astype(int)
    long["date"] = pd.to_datetime(
        dict(year=year, month=long["month"], day=long["day"].astype(int)),
        errors="coerce",
    )
    long = long.dropna(subset=["date"])
    return pd.DataFrame({
        "date": long["date"].astype("datetime64[ns]"),
        "h_cm": long["h_cm"].to_numpy(float),
        "h_m_local": np.nan,
        "h_bs77_m": _h_bs77(long["h_cm"], st).to_numpy(),
        "source": "yearbook_grid",
    })


def _from_parquet(st: DownstreamStation) -> pd.DataFrame:
    if st.parquet_dir is None or not st.parquet_dir.exists():
        return _empty_src()
    files = sorted(st.parquet_dir.glob("year=*.parquet"))
    if not files:
        return _empty_src()
    raw = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    col = "h_mean" if "h_mean" in raw.columns else ("h_08" if "h_08" in raw.columns else None)
    if col is None:
        return _empty_src()
    h_cm = pd.to_numeric(raw[col], errors="coerce")
    return pd.DataFrame({
        "date": pd.to_datetime(raw["date"]).astype("datetime64[ns]"),
        "h_cm": h_cm.to_numpy(),
        "h_m_local": np.nan,
        "h_bs77_m": _h_bs77(h_cm, st).to_numpy(),
        "source": "donor_parquet",
    }).dropna(subset=["date", "h_cm"])


def _from_version_parquets(st: DownstreamStation) -> pd.DataFrame:
    """Donor version-fragmented ``level`` parquet, deduped preferring a real
    ``version=*`` snapshot over a ``tmp_*`` one.
    """
    root = st.parquet_versions_root
    if root is None or not root.exists():
        return _empty_src()
    frames = []
    for grain in ("daily", "monthly"):
        for f in sorted(root.glob(f"*/{grain}/post_id={st.id}/**/*.parquet")):
            snap = f.relative_to(root).parts[0]
            d = pd.read_parquet(f)
            d = d[d.get("variable", "level").astype(str) == "level"]
            if d.empty:
                continue
            frames.append(pd.DataFrame({
                "date": pd.to_datetime(d["date"]).astype("datetime64[ns]"),
                "h_cm": pd.to_numeric(d["value"], errors="coerce").to_numpy(),
                "_snap_tmp": snap.startswith("tmp_"),
                "_grain_monthly": grain == "monthly",
            }))
        if frames:  # prefer daily; only fall through to monthly if nothing daily
            break
    if not frames:
        return _empty_src()
    s = pd.concat(frames, ignore_index=True).dropna(subset=["date", "h_cm"])
    s = (s.sort_values(["date", "_snap_tmp", "_grain_monthly"])
         .drop_duplicates(subset="date", keep="first"))
    return pd.DataFrame({
        "date": s["date"].to_numpy(),
        "h_cm": s["h_cm"].to_numpy(float),
        "h_m_local": np.nan,
        "h_bs77_m": _h_bs77(s["h_cm"], st).to_numpy(),
        "source": "donor_parquet_versioned",
    })


def load_downstream_series(cfg: Config, station_id: str | int | None = None) -> pd.DataFrame:
    """Stitched daily series for every configured downstream post (or one).

    On an overlapping date the source earliest in :data:`_SOURCE_PRIORITY` wins.
    ``h_cm`` is above the post graph zero; ``h_bs77_m`` is the absolute BS-77
    height where a graph zero is known (Kherson, Mykolaiv), NaN otherwise;
    ``h_m_local`` is the Kherson yearbook anomaly column.
    """
    stations = cfg.gauges.downstream
    if station_id is not None:
        stations = [s for s in stations if str(s.id) == str(station_id)]

    frames: list[pd.DataFrame] = []
    for st in stations:
        parts = [p for p in (_from_yearbook(st), _from_yearbook_grid(st),
                              _from_parquet(st), _from_version_parquets(st)) if not p.empty]
        if not parts:
            continue
        s = pd.concat(parts, ignore_index=True)
        s["_prio"] = s["source"].map(_SOURCE_PRIORITY).fillna(9)
        s = (s.sort_values(["date", "_prio"])
             .drop_duplicates(subset="date", keep="first")
             .drop(columns="_prio").reset_index(drop=True))
        s["station_id"] = st.id
        s["slug"] = st.slug
        s["name_en"] = st.name_en
        s["period"] = [cfg.regimes.label_for(x) for x in s["date"].dt.date]
        s["post_breach"] = s["date"] >= pd.Timestamp(cfg.regimes.breach_start)
        frames.append(s[SERIES_COLUMNS])

    if not frames:
        return pd.DataFrame(columns=SERIES_COLUMNS)
    return pd.concat(frames, ignore_index=True).sort_values(
        ["station_id", "date"]
    ).reset_index(drop=True)


def bs77_daily(cfg: Config, slug: str) -> pd.DataFrame:
    """Daily absolute BS-77 height for one coastal post (``kherson`` / ``mykolaiv``).

    Columns: ``date`` (naive ns), ``h_bs77_m``, ``h0_bs77_m`` (the post graph
    zero), ``period``. Only rows with a finite absolute height. The graph zero is
    a rounded nominal (-5.00 m for both) — a corrector built on it still absorbs
    a gauge-zero error.
    """
    st = next((s for s in cfg.gauges.downstream if s.slug == slug), None)
    cols = ["date", "h_bs77_m", "h0_bs77_m", "period"]
    if st is None or st.gauge_zero_baltic_m is None:
        return pd.DataFrame(columns=cols)
    s = load_downstream_series(cfg, st.id)
    s = s[np.isfinite(s["h_bs77_m"])].copy()
    if s.empty:
        return pd.DataFrame(columns=cols)
    s["h0_bs77_m"] = float(st.gauge_zero_baltic_m)
    return s[cols].sort_values("date").reset_index(drop=True)


def kherson_bs77_daily(cfg: Config) -> pd.DataFrame:
    """Back-compat alias — Kherson daily absolute BS-77 height."""
    return bs77_daily(cfg, "kherson")


def load_body_pass_levels(cfg: Config, slug: str, *, clean: bool = True) -> pd.DataFrame:
    """Beam-pass levels for a downstream ATL13 body (``kherson`` / ``dnipro_estuary``).

    With ``clean`` (default) keep only a plausible open-water surface:
    ``nmad_m < 0.20``, ``n_points >= 15``, ``abs(median_wse_evrs_m) < 3`` — this
    drops the rare pool / bank contamination near the water-body edges.
    """
    path = cfg.downstream_body(slug).pass_levels_parquet
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `python scripts/download_atl13_downstream.py --body {slug}`"
        )
    df = pd.read_parquet(path)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    if clean:
        df = df[(df["nmad_m"] < 0.20) & (df["n_points"] >= 15)
                & (df["median_wse_evrs_m"].abs() < 3.0)]
    return df.reset_index(drop=True)


def estuary_wse_summary(passes: pd.DataFrame) -> pd.DataFrame:
    """Median / NMAD / p05-p95 of ``median_wse_evrs_m`` by year and overall."""
    def _row(g: pd.DataFrame, label) -> dict:
        v = g["median_wse_evrs_m"].to_numpy(float)
        return {
            "year": label, "n_passes": int(v.size),
            "median_wse_evrs_m": float(np.median(v)) if v.size else np.nan,
            "nmad_m": float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else np.nan,
            "p05_m": float(np.percentile(v, 5)) if v.size else np.nan,
            "p95_m": float(np.percentile(v, 95)) if v.size else np.nan,
        }
    rows = [_row(g, int(y)) for y, g in passes.groupby(passes["datetime"].dt.year)]
    rows.append(_row(passes, "ALL"))
    return pd.DataFrame(rows)


def coverage_summary(series: pd.DataFrame) -> pd.DataFrame:
    """One row per downstream post: span, n days, sources, breach-wave peak."""
    rows = []
    for (sid, slug, name), g in series.groupby(["station_id", "slug", "name_en"]):
        post = g[g["post_breach"]]
        rows.append({
            "station_id": sid, "slug": slug, "name_en": name,
            "start": g["date"].min(), "end": g["date"].max(),
            "n_days": int(len(g)),
            "years": ",".join(map(str, sorted(g["date"].dt.year.unique()))),
            "sources": ",".join(sorted(g["source"].unique())),
            "has_bs77": bool(np.isfinite(g["h_bs77_m"]).any()),
            "h_cm_min": float(g["h_cm"].min()), "h_cm_max": float(g["h_cm"].max()),
            # max in the post-breach window: the June-2023 flood wave for Kherson
            # (Dnipro below the dam); just the ordinary 2023 max for Mykolaiv (Buh).
            "postbreach_h_cm_max": float(post["h_cm"].max()) if not post.empty else float("nan"),
        })
    return pd.DataFrame(rows)
