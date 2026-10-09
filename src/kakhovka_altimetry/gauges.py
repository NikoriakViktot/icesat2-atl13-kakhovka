"""Phase 2 — Baltic-system gauge stage series.

    stage_m       : water level above the (nominal) gauge zero, from the raw data
    WSE_baltic_m  : gauge_zero_baltic_m + stage_m   (nominal absolute WSE, BS-77)

V1 does not use this module. Phase 2 matches ``stage_m`` to ICESat-2 pass levels
and estimates the empirical vertical alignment constant (see
:mod:`kakhovka_altimetry.datum`).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config

OBS_COLUMNS = [
    "station_id",
    "datetime",           # UTC
    "stage_m",
    "WSE_baltic_m",
]

# Accepted column aliases in the generic per-station files.
_TIME_ALIASES = ("datetime", "date", "timestamp", "time", "дата", "датачас")
_STAGE_ALIASES = ("stage", "level", "h", "h_mean", "рівень", "уровень", "hcm", "stage_cm")

# Term-reading hours (local) for the donor "reservoir_parquet" format.
_TERM_HOURS = {"h_08": 8, "h_20": 20}


def _read_generic_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        raw = pd.read_excel(path)
    elif path.suffix.lower() == ".parquet":
        raw = pd.read_parquet(path)
    else:
        raw = pd.read_csv(path, sep=None, engine="python")
    cols = {c.lower().strip(): c for c in raw.columns}

    tcol = next((cols[a] for a in _TIME_ALIASES if a in cols), None)
    scol = next((cols[a] for a in _STAGE_ALIASES if a in cols), None)
    if tcol is None or scol is None:
        raise ValueError(
            f"{path.name}: could not find time/stage columns; got {list(raw.columns)}"
        )
    out = pd.DataFrame(
        {
            "datetime": pd.to_datetime(raw[tcol], errors="coerce"),
            "stage_raw": pd.to_numeric(raw[scol], errors="coerce"),
        }
    )
    return out.dropna(subset=["datetime", "stage_raw"])


def _read_reservoir_parquet(station_id: str, root: Path) -> pd.DataFrame:
    """Donor hydro-platform layout: ``<root>/post_id=<id>/year=*.parquet`` with
    daily ``h_08`` / ``h_20`` term readings (cm above gauge zero). Returns a long
    frame of (local naive datetime, stage_raw[cm]) with two rows per day.
    """
    files = sorted((root / f"post_id={station_id}").glob("year=*.parquet"))
    if not files:
        return pd.DataFrame(columns=["datetime", "stage_raw"])
    daily = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    daily["date"] = pd.to_datetime(daily["date"])
    rows = []
    for col, hour in _TERM_HOURS.items():
        if col not in daily.columns:
            continue
        part = daily[["date", col]].dropna()
        rows.append(pd.DataFrame({
            "datetime": part["date"] + pd.Timedelta(hours=hour),
            "stage_raw": pd.to_numeric(part[col], errors="coerce"),
        }))
    if not rows:  # fall back to the daily mean at local noon
        part = daily[["date", "h_mean"]].dropna()
        rows.append(pd.DataFrame({
            "datetime": part["date"] + pd.Timedelta(hours=12),
            "stage_raw": pd.to_numeric(part["h_mean"], errors="coerce"),
        }))
    return pd.concat(rows, ignore_index=True).dropna().sort_values("datetime")


def load_gauge_observations(cfg: Config) -> pd.DataFrame:
    """Load and normalise every station's raw data into the long OBS table.

    Discovery depends on ``gauges.raw.format``:
      * ``reservoir_parquet`` -> ``<dir>/post_id=<station_id>/year=*.parquet``
      * ``csv`` (default)      -> ``<dir>/<station_id>.{csv,xlsx,xls,parquet}``
    """
    tz = "Europe/Kyiv" if cfg.gauges.timezone == "kyiv" else "UTC"
    to_m = 0.01 if cfg.gauges.stage_units == "cm" else 1.0
    fmt = cfg.gauges.raw_format

    frames: list[pd.DataFrame] = []
    for st in cfg.gauges.stations:
        if fmt == "reservoir_parquet":
            raw = _read_reservoir_parquet(st.id, cfg.gauges.raw_dir)
        else:
            matches = sorted(cfg.gauges.raw_dir.glob(f"{st.id}.*"))
            raw = (
                pd.concat([_read_generic_file(p) for p in matches], ignore_index=True)
                if matches else pd.DataFrame(columns=["datetime", "stage_raw"])
            )
        if raw.empty:
            continue
        ts = raw["datetime"]
        ts = ts.dt.tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT") \
            if ts.dt.tz is None else ts.dt.tz_convert(tz)
        raw["datetime"] = ts.dt.tz_convert("UTC")
        raw["stage_m"] = raw["stage_raw"] * to_m
        raw["station_id"] = st.id

        if st.gauge_zero_baltic_m is None:
            raw["WSE_baltic_m"] = np.nan
        else:
            raw["WSE_baltic_m"] = st.gauge_zero_baltic_m + raw["stage_m"]

        frames.append(
            raw[OBS_COLUMNS]
            .sort_values("datetime")
            .drop_duplicates(subset=["station_id", "datetime"])
        )

    if not frames:
        return pd.DataFrame(columns=OBS_COLUMNS)
    return pd.concat(frames, ignore_index=True).sort_values(
        ["station_id", "datetime"]
    ).reset_index(drop=True)


def gauge_value_at(
    obs: pd.DataFrame,
    station_id: str,
    when: pd.Timestamp,
    *,
    column: str = "stage_m",
    method: str = "linear",
    max_gap_hours: float = 24.0,
) -> tuple[float, bool, float]:
    """Value of ``column`` for ``station_id`` at ``when``.

    Returns ``(value, interpolated, time_difference_hours)`` where
    ``time_difference_hours`` is to the nearest actual observation. NaN value if
    the nearest observation is further than ``max_gap_hours``.
    """
    when = pd.Timestamp(when)
    when = when.tz_convert("UTC") if when.tzinfo else when.tz_localize("UTC")

    s = obs.loc[obs["station_id"] == station_id, ["datetime", column]].dropna()
    if s.empty:
        return float("nan"), False, float("nan")
    s = s.sort_values("datetime")
    t_ns = (
        pd.to_datetime(s["datetime"], utc=True)
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
        .to_numpy(dtype="datetime64[ns]")
        .astype("int64")
    )
    vals = s[column].to_numpy(float)
    w_ns = int(when.tz_localize(None).to_datetime64().astype("datetime64[ns]").astype("int64"))

    NS_PER_HOUR = 3_600_000_000_000
    dt_hours = np.abs(t_ns - w_ns) / NS_PER_HOUR
    nearest_i = int(np.argmin(dt_hours))
    nearest_gap = float(dt_hours[nearest_i])
    if nearest_gap > max_gap_hours:
        return float("nan"), False, nearest_gap

    if method == "nearest" or t_ns.size == 1:
        return float(vals[nearest_i]), False, nearest_gap

    if w_ns <= t_ns[0] or w_ns >= t_ns[-1]:
        return float(vals[nearest_i]), False, nearest_gap
    value = float(np.interp(w_ns, t_ns, vals))
    return value, True, nearest_gap
