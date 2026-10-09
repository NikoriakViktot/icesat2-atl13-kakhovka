"""Maps and plots for the ATL13 / local-alignment work.

Cartography is built from the ATL13 water returns themselves — they *are* the
observed water surface — plus the AOI bbox. The `Kakhovka_SA_2.geojson` polygon is
deliberately not drawn: its epoch is unconfirmed and it does not contain
mid-reservoir points (see the AOI note in the README).

Every function takes an explicit ``ax`` where practical so the notebook can
compose panels, and returns the axis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config, GaugeStation

# Degrees per km at the reservoir's latitude (~47.3 N), for aspect and rings.
_KM_PER_DEG_LAT = 111.32


def _km_per_deg_lon(lat: float) -> float:
    return _KM_PER_DEG_LAT * np.cos(np.radians(lat))


def set_geo_aspect(ax, lat: float) -> None:
    """Make 1 km look the same horizontally and vertically at this latitude."""
    ax.set_aspect(1.0 / np.cos(np.radians(lat)))


def draw_rings(ax, station: GaugeStation, radii_km, *, color="k", lw=0.8):
    """Distance rings around a gauge, drawn in degrees but circular on the ground."""
    th = np.linspace(0, 2 * np.pi, 361)
    kx, ky = _km_per_deg_lon(station.lat), _KM_PER_DEG_LAT
    for r in radii_km:
        ax.plot(
            station.lon + (r / kx) * np.cos(th),
            station.lat + (r / ky) * np.sin(th),
            color=color, lw=lw, ls="--", alpha=0.55, zorder=4,
        )
        ax.annotate(f"{r:g} km", (station.lon, station.lat + (r / ky)),
                    fontsize=7, color=color, ha="center", va="bottom",
                    alpha=0.8, zorder=5)
    return ax


def overview_map(
    evrs: pd.DataFrame, cfg: Config, ax=None, *,
    period: str = "PRE_BREACH", sample: int = 60_000, seed: int = 0,
):
    """Whole reservoir: ATL13 water returns coloured by EVRS level + all posts."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(13, 7))

    d = evrs[(evrs["period"] == period) & evrs["water_mask_pass"].fillna(False)]
    if len(d) > sample:
        d = d.sample(sample, random_state=seed)

    lo, hi = np.nanpercentile(d["H_evrs_egg2015_m"], [2, 98])
    sc = ax.scatter(d["lon"], d["lat"], c=d["H_evrs_egg2015_m"], s=1.2,
                    cmap="viridis", vmin=lo, vmax=hi, linewidths=0, zorder=2)
    plt.colorbar(sc, ax=ax, label="ATL13 water surface, m EVRS", shrink=0.85)

    for st in cfg.gauges.stations:
        if not st.complete:
            continue
        ax.plot(st.lon, st.lat, "o", ms=8, mfc="red", mec="white", mew=1.4, zorder=6)
        ax.annotate(f"{st.name_en}\n{st.id}", (st.lon, st.lat),
                    textcoords="offset points", xytext=(8, 6), fontsize=8,
                    weight="bold", zorder=7,
                    bbox=dict(fc="white", ec="none", alpha=0.7, pad=1.2))

    lon_min, lat_min, lon_max, lat_max = cfg.aoi_bbox
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    set_geo_aspect(ax, float(np.mean([lat_min, lat_max])))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"Kakhovka reservoir — ATL13 water surface ({period}) and gauges")
    ax.grid(alpha=0.15)
    return ax


def station_map(
    evrs: pd.DataFrame, station: GaugeStation, cfg: Config, ax=None, *,
    view_km: float = 12.0, period: str = "PRE_BREACH", radii_km=None,
    distance_km: np.ndarray | None = None,
):
    """Zoom on one post: ATL13 segments coloured by RGT + distance rings."""
    import matplotlib.pyplot as plt

    from .local_alignment import distance_to_station

    if ax is None:
        _, ax = plt.subplots(figsize=(6.5, 6))
    radii_km = radii_km or cfg.local_alignment.radii_km

    d = distance_to_station(evrs, station) if distance_km is None else distance_km
    keep = (d <= view_km) & (evrs["period"] == period).to_numpy(bool)
    keep &= evrs["water_mask_pass"].fillna(False).to_numpy(bool)
    sub = evrs.loc[keep]

    if sub.empty:
        ax.text(0.5, 0.5, "no ATL13 water returns in view", transform=ax.transAxes,
                ha="center", va="center", fontsize=10)
    else:
        rgts = sorted(sub["rgt"].unique())
        cmap = plt.get_cmap("tab10")
        for i, rgt in enumerate(rgts):
            s = sub[sub["rgt"] == rgt]
            ax.scatter(s["lon"], s["lat"], s=3, color=cmap(i % 10),
                       label=f"RGT {int(rgt)} (n={len(s)})", linewidths=0, zorder=2)
        ax.legend(fontsize=7, markerscale=3, loc="best", framealpha=0.85)

    draw_rings(ax, station, radii_km)
    ax.plot(station.lon, station.lat, "*", ms=16, mfc="red", mec="white",
            mew=1.2, zorder=8)

    kx, ky = _km_per_deg_lon(station.lat), _KM_PER_DEG_LAT
    ax.set_xlim(station.lon - view_km / kx, station.lon + view_km / kx)
    ax.set_ylim(station.lat - view_km / ky, station.lat + view_km / ky)
    set_geo_aspect(ax, station.lat)
    ax.set_title(f"{station.name_en} ({station.id})", fontsize=10)
    ax.set_xlabel("longitude", fontsize=8)
    ax.set_ylabel("latitude", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.15)
    return ax


def station_panel(evrs: pd.DataFrame, cfg: Config, *, view_km: float = 12.0,
                  ncols: int = 3, period: str = "PRE_BREACH"):
    """A grid of :func:`station_map` for every complete station."""
    import matplotlib.pyplot as plt

    stations = [s for s in cfg.gauges.stations if s.complete]
    nrows = int(np.ceil(len(stations) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.2 * ncols, 5.0 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for ax, st in zip(axes, stations, strict=False):
        station_map(evrs, st, cfg, ax=ax, view_km=view_km, period=period)
    for ax in axes[len(stations):]:
        ax.axis("off")
    fig.suptitle(f"ATL13 coverage around each Kakhovka gauge ({period})", y=1.0)
    fig.tight_layout()
    return fig


def alignment_map(summary: pd.DataFrame, evrs: pd.DataFrame, cfg: Config, ax=None):
    """Posts coloured by their alignment constant, over the ATL13 footprint."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(13, 7))

    d = evrs[(evrs["period"] == "PRE_BREACH") & evrs["water_mask_pass"].fillna(False)]
    d = d.sample(min(len(d), 40_000), random_state=0)
    ax.scatter(d["lon"], d["lat"], s=0.8, color="0.80", linewidths=0, zorder=1)

    ok = summary[summary["alignment_constant_m"].notna()]
    if not ok.empty:
        sc = ax.scatter(ok["lon"], ok["lat"], c=ok["alignment_constant_m"],
                        s=170, cmap="coolwarm", edgecolor="k", linewidth=1.0,
                        zorder=5)
        plt.colorbar(sc, ax=ax, label="alignment_constant_m (m)", shrink=0.85)
    for _, r in summary.iterrows():
        txt = (f"{r['name_en']}\n{r['alignment_constant_m']:.3f} m (n={r['n_reported']})"
               if pd.notna(r["alignment_constant_m"])
               else f"{r['name_en']}\nno tie")
        ax.annotate(txt, (r["lon"], r["lat"]), textcoords="offset points",
                    xytext=(9, 7), fontsize=8, zorder=7,
                    bbox=dict(fc="white", ec="0.6", alpha=0.85, pad=1.5))

    lon_min, lat_min, lon_max, lat_max = cfg.aoi_bbox
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    set_geo_aspect(ax, float(np.mean([lat_min, lat_max])))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Empirical vertical alignment constant per gauge (PRE_BREACH)")
    ax.grid(alpha=0.15)
    return ax


def longitudinal_profile(summary: pd.DataFrame, ax=None):
    """Alignment constant vs distance from the dam — is there a spatial trend?"""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4.5))
    s = summary[summary["alignment_constant_m"].notna()].sort_values(
        "distance_from_dam_km"
    )
    if s.empty:
        ax.text(0.5, 0.5, "no ties", transform=ax.transAxes, ha="center")
        return ax

    yerr = np.vstack([
        s["alignment_constant_m"] - s["ci95_low_m"],
        s["ci95_high_m"] - s["alignment_constant_m"],
    ])
    yerr = np.nan_to_num(yerr, nan=0.0)
    ax.errorbar(s["distance_from_dam_km"], s["alignment_constant_m"], yerr=yerr,
                fmt="o", capsize=4, ms=7, lw=1.2)
    pooled = float(np.median(s["alignment_constant_m"]))
    ax.axhline(pooled, color="k", ls="--", lw=1,
               label=f"median across posts = {pooled:.3f} m")
    # Alternate labels above/below so neighbours and the median line don't collide.
    for _, r in s.iterrows():
        above = r["alignment_constant_m"] >= pooled
        dy = 16 if above else -30
        ax.annotate(f"{r['name_en']}\n(n={r['n_reported']}, r={r['reported_radius_km']:g} km)",
                    (r["distance_from_dam_km"], r["alignment_constant_m"]),
                    textcoords="offset points", xytext=(0, dy), fontsize=7,
                    ha="center", zorder=6,
                    bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.0))
    ax.set_xlabel("distance from Kakhovka dam (km)")
    ax.set_ylabel("alignment_constant_m (m)")
    ax.set_title("Alignment constant along the reservoir")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    return ax


def radius_stability(ladders: dict[str, pd.DataFrame], cfg: Config, ax=None):
    """alignment_constant_m vs radius, one line per station."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))
    for name, ladder in ladders.items():
        ok = ladder[ladder["n_matchups"] > 0]
        if ok.empty:
            continue
        thin = ok["indicative"]
        ax.plot(ok["radius_km"], ok["alignment_constant_m"], "-o", ms=5, label=name)
        ax.scatter(ok.loc[thin, "radius_km"], ok.loc[thin, "alignment_constant_m"],
                   s=110, facecolors="none", edgecolors="crimson", zorder=5)
    ax.axvline(cfg.local_alignment.main_radius_km, color="k", ls=":", lw=1,
               label=f"main radius {cfg.local_alignment.main_radius_km:g} km")
    ax.set_xscale("log")
    ax.set_xticks(list(cfg.local_alignment.radii_km) +
                  [cfg.local_alignment.diagnostic_radius_km])
    ax.get_xaxis().set_major_formatter(plt.ScalarFormatter())
    ax.set_xlabel("radius around the gauge (km)")
    ax.set_ylabel("alignment_constant_m (m)")
    ax.set_title("Stability of the alignment constant vs radius\n"
                 "(red rings = below the confidence threshold)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    return ax


def residual_timeseries(matchups: pd.DataFrame, ax=None, *, by: str = "rgt"):
    """Per-matchup alignment residual over time, coloured by RGT."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(11, 4))
    m = matchups.copy()
    m["datetime"] = pd.to_datetime(m["datetime"])
    cmap = plt.get_cmap("tab10")
    for i, (key, g) in enumerate(m.groupby(by)):
        ax.scatter(g["datetime"], g["alignment_constant_m"], s=28,
                   color=cmap(i % 10), label=f"{by} {key}")
    med = float(np.median(m["alignment_constant_m"]))
    ax.axhline(med, color="k", ls="--", lw=1, label=f"median = {med:.3f} m")
    ax.set_ylabel("H_EVRS_ICESat − stage (m)")
    ax.set_title("Alignment residual per matchup")
    ax.legend(fontsize=8, ncol=3)
    ax.grid(alpha=0.25)
    return ax


def gauge_vs_icesat(matchups: pd.DataFrame, station: GaugeStation, ax=None):
    """ICESat WSE against gauge stage; the intercept is the alignment constant."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(6, 5.5))
    x = matchups["stage_m"].to_numpy(float)
    y = matchups["median_wse_evrs_m"].to_numpy(float)
    ax.scatter(x, y, s=36, zorder=3)
    c = float(np.median(y - x))
    xs = np.linspace(np.nanmin(x), np.nanmax(x), 10)
    ax.plot(xs, xs + c, "k--", lw=1.2, label=f"slope 1, intercept {c:.3f} m")
    ax.set_xlabel("gauge stage (m above post zero)")
    ax.set_ylabel("ICESat-2 local WSE (m EVRS)")
    ax.set_title(f"{station.name_en} ({station.id}) — n={len(matchups)}")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    return ax


# --------------------------------------------------------------------------- #
# Phase 2b — official datum comparison                                         #
# --------------------------------------------------------------------------- #
def official_correction_map(grid, decomp: pd.DataFrame, cfg: Config, ax=None, *,
                            pad_deg: float = 2.5):
    """The official BS-77 -> EVRF2019 grid around the AOI, with the posts on top."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(12, 7))

    lon_min, lat_min, lon_max, lat_max = cfg.aoi_bbox
    ix = (grid.lons >= lon_min - pad_deg) & (grid.lons <= lon_max + pad_deg)
    iy = (grid.lats >= lat_min - pad_deg) & (grid.lats <= lat_max + pad_deg)
    sub = grid.values[np.ix_(iy, ix)]

    im = ax.pcolormesh(grid.lons[ix], grid.lats[iy], sub, cmap="viridis",
                       shading="nearest")
    plt.colorbar(im, ax=ax, label="official BS-77 → EVRF2019 correction (m)",
                 shrink=0.85)
    cs = ax.contour(grid.lons[ix], grid.lats[iy], sub, colors="w",
                    linewidths=0.6, alpha=0.7)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%.2f")

    ax.add_patch(plt.Rectangle((lon_min, lat_min), lon_max - lon_min,
                               lat_max - lat_min, fill=False, ec="red", lw=1.2,
                               ls="--", zorder=4))
    for _, r in decomp.iterrows():
        ax.plot(r["lon"], r["lat"], "o", ms=7, mfc="red", mec="white", mew=1.2,
                zorder=6)
        ax.annotate(f"{r['name_en']}\n{r['delta_official_m']:.3f} m",
                    (r["lon"], r["lat"]), textcoords="offset points",
                    xytext=(8, 6), fontsize=7, zorder=7,
                    bbox=dict(fc="white", ec="0.6", alpha=0.85, pad=1.2))
    set_geo_aspect(ax, float(np.mean([lat_min, lat_max])))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"EPSG:{cfg.official_transform.epsg_operation} grid around the "
                 f"Kakhovka reservoir")
    return ax


def datum_budget_bars(decomp: pd.DataFrame, cfg: Config, ax=None):
    """Stacked official / unexplained split of the empirical constant, per post."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))
    d = decomp.dropna(subset=["delta_official_m"]).copy()
    x = np.arange(len(d))

    pub = cfg.official_transform.published_stats
    ax.axhspan(pub["min_m"], pub["max_m"], color="tab:green", alpha=0.12,
               label=f"EPSG:{cfg.official_transform.epsg_operation} national range")
    ax.axhline(pub["mean_m"], color="tab:green", ls=":", lw=1.2,
               label=f"national mean {pub['mean_m']:.3f} m")

    ax.bar(x, d["delta_official_m"], color="tab:green", label="official (EPSG grid)")
    ax.bar(x, d["delta_unexplained_m"], bottom=d["delta_official_m"],
           color="tab:orange", label="unexplained (zero err + EGG2015 + ATL13)")
    ax.plot(x, d["delta_empirical_m"], "k_", ms=26, mew=2,
            label="empirical  C − nominal zero")

    ax.set_xticks(x)
    ax.set_xticklabels(d["name_en"], rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("height difference (m)")
    ax.set_title("Where the +0.36 m goes: official datum correction vs the rest")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")
    return ax


def unexplained_by_radius(by_radius: pd.DataFrame, cfg: Config, ax=None):
    """delta_unexplained vs radius — must be flat for a datum/zero term."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))
    thr = cfg.local_alignment.min_matchups_for_confidence
    for name, g in by_radius.groupby("name_en"):
        g = g.sort_values("radius_km")
        ax.plot(g["radius_km"], g["delta_unexplained_m"], "-o", ms=5, label=name)
        thin = g[g["n_matchups"] < thr]
        ax.scatter(thin["radius_km"], thin["delta_unexplained_m"], s=110,
                   facecolors="none", edgecolors="crimson", zorder=5)
    ax.axvline(cfg.local_alignment.main_radius_km, color="k", ls=":", lw=1,
               label=f"main radius {cfg.local_alignment.main_radius_km:g} km")
    ax.set_xscale("log")
    ticks = sorted({*cfg.local_alignment.radii_km,
                    cfg.local_alignment.diagnostic_radius_km})
    ax.set_xticks(ticks)
    ax.get_xaxis().set_major_formatter(plt.ScalarFormatter())
    ax.set_xlabel("radius around the gauge (km)")
    ax.set_ylabel("delta_unexplained_m (m)")
    ax.set_title("Unexplained residual vs radius\n"
                 "(a datum/zero term must be flat here; red rings = n below "
                 "the confidence threshold)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    return ax
