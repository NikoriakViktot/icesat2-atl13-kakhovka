"""Phase 3 — candidate spatial models for the EGG2015→EVRF2019 corrector.

Phase 2c gives six point estimates ``c_station`` at the six Kakhovka gauges.
Phase 2d turned them into a **nearest-station (Voronoi)** lookup
(:mod:`kakhovka_altimetry.corrector_surface`) — deliberately *not* a smooth
interpolant, so an unreliable station (Rozumivka's RGT split, Velyka Lepetykha's
n=5) cannot bleed into its neighbours.

This module exists to *test that choice*, not to overturn it: it fits the four
smooth candidates the literature would expect — a regional **constant**, a
least-squares **plane**, inverse-distance weighting (**IDW**, p=1 and p=2), and
**linear** triangulation — and scores every one by **leave-one-station-out**
cross-validation. With only six controls, random train/test splitting is
meaningless; dropping one whole station and predicting it is the only honest
test. The recommendation that falls out is "the simplest model that survives
LOSO-CV", which so far is the regional constant / nearest-station.

All fitting is done in **metres**, in a local azimuthal-equidistant projection
centred on the control network — never in raw degrees.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

VALUE_COL = "c_station_m"
MODEL_NAMES: tuple[str, ...] = ("constant", "plane", "idw_p1", "idw_p2", "linear")


# --------------------------------------------------------------------------- #
# Local projection (degrees <-> metres)                                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LocalProjection:
    """Azimuthal-equidistant projection about ``(lat0, lon0)``. Distances and
    least-squares fits must be in metres; feeding lon/lat degrees straight into
    IDW or a plane fit distorts the ~1.5:1 lon:lat scale at this latitude.
    """

    lat0: float
    lon0: float

    def _transformer(self, inverse: bool = False):
        from pyproj import Transformer

        aeqd = f"+proj=aeqd +lat_0={self.lat0} +lon_0={self.lon0} +datum=WGS84 +units=m +no_defs"
        return (
            Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)
            if inverse
            else Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
        )

    def forward(self, lat, lon) -> tuple[np.ndarray, np.ndarray]:
        x, y = self._transformer().transform(np.asarray(lon, float), np.asarray(lat, float))
        return np.asarray(x, float), np.asarray(y, float)

    def inverse(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        lon, lat = self._transformer(inverse=True).transform(
            np.asarray(x, float), np.asarray(y, float)
        )
        return np.asarray(lat, float), np.asarray(lon, float)


def local_projection(stations: pd.DataFrame) -> LocalProjection:
    """Projection centred on the mean of the control coordinates."""
    return LocalProjection(float(stations["lat"].mean()), float(stations["lon"].mean()))


# --------------------------------------------------------------------------- #
# Models                                                                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Constant:
    name: str
    value: float

    def predict(self, lat, lon) -> np.ndarray:
        return np.full(np.shape(np.atleast_1d(lat)), self.value, float)


@dataclass(frozen=True)
class _Plane:
    name: str
    coef: np.ndarray            # (a, b, d) for c = a + b*x + d*y  (x, y in metres)
    proj: LocalProjection

    def predict(self, lat, lon) -> np.ndarray:
        x, y = self.proj.forward(np.atleast_1d(lat), np.atleast_1d(lon))
        a, b, d = self.coef
        return a + b * x + d * y


@dataclass(frozen=True)
class _IDW:
    name: str
    x: np.ndarray
    y: np.ndarray
    v: np.ndarray
    power: float
    proj: LocalProjection

    def predict(self, lat, lon) -> np.ndarray:
        px, py = self.proj.forward(np.atleast_1d(lat), np.atleast_1d(lon))
        out = np.empty(px.shape, float)
        for i in range(px.size):
            d = np.hypot(self.x - px.flat[i], self.y - py.flat[i])
            hit = d <= 1e-6
            if hit.any():
                out.flat[i] = float(self.v[hit].mean())
                continue
            w = 1.0 / d ** self.power
            out.flat[i] = float(np.sum(w * self.v) / np.sum(w))
        return out


@dataclass(frozen=True)
class _Linear:
    name: str
    proj: LocalProjection
    _interp: object

    def predict(self, lat, lon) -> np.ndarray:
        x, y = self.proj.forward(np.atleast_1d(lat), np.atleast_1d(lon))
        return np.asarray(self._interp(np.column_stack([x, y])), float)


# --------------------------------------------------------------------------- #
# Fitting                                                                      #
# --------------------------------------------------------------------------- #
def _xyv(stations: pd.DataFrame, proj: LocalProjection, value_col: str):
    s = stations[np.isfinite(stations[value_col])]
    x, y = proj.forward(s["lat"].to_numpy(float), s["lon"].to_numpy(float))
    return x, y, s[value_col].to_numpy(float)


def fit_constant(stations, proj=None, *, value_col: str = VALUE_COL) -> _Constant:
    proj = proj or local_projection(stations)
    _, _, v = _xyv(stations, proj, value_col)
    return _Constant("constant", float(np.median(v)))


def fit_plane(stations, proj=None, *, value_col: str = VALUE_COL) -> _Plane:
    proj = proj or local_projection(stations)
    x, y, v = _xyv(stations, proj, value_col)
    if v.size < 3:
        raise ValueError("plane fit needs >= 3 stations")
    A = np.column_stack([np.ones_like(x), x, y])
    coef, *_ = np.linalg.lstsq(A, v, rcond=None)
    return _Plane("plane", coef, proj)


def fit_idw(stations, proj=None, *, power: float = 2.0, value_col: str = VALUE_COL) -> _IDW:
    proj = proj or local_projection(stations)
    x, y, v = _xyv(stations, proj, value_col)
    return _IDW(f"idw_p{int(power)}", x, y, v, float(power), proj)


def fit_linear(stations, proj=None, *, value_col: str = VALUE_COL) -> _Linear:
    from scipy.interpolate import LinearNDInterpolator

    proj = proj or local_projection(stations)
    x, y, v = _xyv(stations, proj, value_col)
    if v.size < 3:
        raise ValueError("linear triangulation needs >= 3 stations")
    return _Linear("linear", proj, LinearNDInterpolator(np.column_stack([x, y]), v))


_FACTORIES = {
    "constant": lambda s, p, vc: fit_constant(s, p, value_col=vc),
    "plane": lambda s, p, vc: fit_plane(s, p, value_col=vc),
    "idw_p1": lambda s, p, vc: fit_idw(s, p, power=1, value_col=vc),
    "idw_p2": lambda s, p, vc: fit_idw(s, p, power=2, value_col=vc),
    "linear": lambda s, p, vc: fit_linear(s, p, value_col=vc),
}


def fit_all(
    stations: pd.DataFrame, *, model_names=MODEL_NAMES, value_col: str = VALUE_COL
) -> dict:
    """Fit every named model on the full control set (one shared projection)."""
    proj = local_projection(stations)
    out = {}
    for name in model_names:
        try:
            out[name] = _FACTORIES[name](stations, proj, value_col)
        except Exception as exc:  # noqa: BLE001 -- report, don't crash the comparison
            out[name] = exc
    return out


# --------------------------------------------------------------------------- #
# Leave-one-station-out cross-validation                                       #
# --------------------------------------------------------------------------- #
CV_COLUMNS = [
    "model", "held_out_station", "held_out_slug",
    "observed_c_m", "predicted_c_m", "error_m", "abs_error_m",
    "training_station_count",
]

CV_SUMMARY_COLUMNS = [
    "model", "n_folds", "n_predicted",
    "loso_bias_m", "loso_mae_m", "loso_rmse_m",
    "loso_median_abs_error_m", "max_abs_error_m",
]


def leave_one_station_out_cv(
    stations: pd.DataFrame, *, model_names=MODEL_NAMES, value_col: str = VALUE_COL,
    name_col: str = "name_en", slug_col: str = "slug",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """For each model: drop one whole station, fit on the rest, predict the
    dropped one, repeat over all stations. ``predicted_c_m`` is NaN when the
    held-out station falls outside the training model's support (e.g. the convex
    hull for ``linear``) — that is a real, reportable outcome, not an error.
    """
    s = stations[np.isfinite(stations[value_col])].reset_index(drop=True)
    rows: list[dict] = []
    for name in model_names:
        for i in range(len(s)):
            train = s.drop(index=i)
            test = s.loc[[i]]
            try:
                proj = local_projection(train)
                model = _FACTORIES[name](train, proj, value_col)
                pred = float(np.asarray(model.predict(
                    test["lat"].to_numpy(float), test["lon"].to_numpy(float)
                )).ravel()[0])
            except Exception:  # noqa: BLE001
                pred = float("nan")
            obs = float(test[value_col].iloc[0])
            err = pred - obs
            rows.append({
                "model": name,
                "held_out_station": test[name_col].iloc[0],
                "held_out_slug": test[slug_col].iloc[0],
                "observed_c_m": obs,
                "predicted_c_m": pred,
                "error_m": err,
                "abs_error_m": abs(err),
                "training_station_count": int(len(train)),
            })
    per_row = pd.DataFrame(rows, columns=CV_COLUMNS)

    summ: list[dict] = []
    for name, g in per_row.groupby("model", sort=False):
        e = g["error_m"].to_numpy(float)
        e = e[np.isfinite(e)]
        summ.append({
            "model": name,
            "n_folds": int(len(g)),
            "n_predicted": int(e.size),
            "loso_bias_m": float(np.mean(e)) if e.size else float("nan"),
            "loso_mae_m": float(np.mean(np.abs(e))) if e.size else float("nan"),
            "loso_rmse_m": float(np.sqrt(np.mean(e ** 2))) if e.size else float("nan"),
            "loso_median_abs_error_m": float(np.median(np.abs(e))) if e.size else float("nan"),
            "max_abs_error_m": float(np.max(np.abs(e))) if e.size else float("nan"),
        })
    summary = pd.DataFrame(summ, columns=CV_SUMMARY_COLUMNS).sort_values(
        "loso_rmse_m"
    ).reset_index(drop=True)
    return per_row, summary
