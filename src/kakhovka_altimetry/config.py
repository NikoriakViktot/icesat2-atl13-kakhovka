"""Load and validate the YAML configuration under ``config/``.

The three files are merged into one :class:`Config` dataclass so the rest of the
pipeline never touches raw dicts or file paths.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Repository root = two levels up from this file (src/kakhovka_altimetry/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def _resolve(path: str | Path) -> Path:
    """Resolve a config-relative path against the repo root."""
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass(frozen=True)
class RegimeConfig:
    pre_breach_end: dt.date
    breach_start: dt.date
    post_breach_start: dt.date

    def label_for(self, when: dt.date | dt.datetime) -> str:
        """Return the period label for a date/datetime."""
        from . import (
            REGIME_BREACH_DRAWDOWN,
            REGIME_POST_BREACH,
            REGIME_PRE_BREACH,
        )

        d = when.date() if isinstance(when, dt.datetime) else when
        if d <= self.pre_breach_end:
            return REGIME_PRE_BREACH
        if d < self.post_breach_start:
            return REGIME_BREACH_DRAWDOWN
        return REGIME_POST_BREACH


@dataclass(frozen=True)
class QCConfig:
    min_points_per_pass: int
    max_mad_m: float
    max_range_m: float
    min_track_length_km: float
    max_stdev_water_surf_m: float
    max_along_track_slope_m_per_km: float


@dataclass(frozen=True)
class MatchupConfig:
    max_time_difference_hours: float
    max_distance_to_gauge_km: float
    gauge_interpolation: str


@dataclass(frozen=True)
class LocalAlignmentConfig:
    """Phase 2a — local vertical tie at one gauge, by distance to the post."""

    station_id: int
    radii_km: tuple[float, ...]
    main_radius_km: float
    diagnostic_radius_km: float
    min_points_per_local_pass: int
    max_local_nmad_m: float
    max_deviation_from_reservoir_m: float
    min_matchups_for_confidence: int


@dataclass(frozen=True)
class ATL13XConfig:
    refid: int
    coord_lon: float
    coord_lat: float
    domain: str
    organization: str | None


@dataclass(frozen=True)
class ProductConfig:
    short_name: str
    version: str
    start_date: dt.date
    end_date: dt.date | None


@dataclass(frozen=True)
class EGG2015Config:
    path: Path
    grid_crs: str
    quantity: str
    reference_ellipsoid: str
    height_system: str
    units: str
    resampling: str

    @property
    def available(self) -> bool:
        return self.path.exists()


@dataclass(frozen=True)
class GaugeStation:
    id: str
    name: str
    slug: str
    name_en: str
    lon: float | None
    lat: float | None
    gauge_zero_baltic_m: float | None
    active_regimes: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return None not in (self.lon, self.lat, self.gauge_zero_baltic_m)


@dataclass(frozen=True)
class DownstreamStation:
    """A river / estuary post BELOW the Kakhovka dam (lower Dnipro, Dnipro-Buh
    liman). Not part of the reservoir pool and never fed to the Phase 2c
    corrector engine. ``gauge_zero_baltic_m`` is ``None`` for every one of these
    -- there is no surveyed zero -- so the series is stage/anomaly only, never an
    absolute WSE (the Kherson yearbook's ``water_level_m_abs`` is the one partial
    exception, handled in :mod:`kakhovka_altimetry.downstream`).
    """

    id: str
    name: str
    name_en: str
    slug: str
    lon: float
    lat: float
    role: str
    gauge_zero_baltic_m: float | None
    yearbook_csv: Path | None
    parquet_dir: Path | None
    # donor version=*/{daily,monthly}/post_id=<id>
    parquet_versions_root: Path | None = None
    # hand-transcribed day x month cm grid (absolute height uses gauge_zero_baltic_m)
    yearbook_grid_csv: Path | None = None
    # coordinate is an approximation (city centre), not a surveyed gauge position
    coords_approx: bool = False


@dataclass(frozen=True)
class DownstreamBody:
    """An ATL13 reference water body below the dam pulled in its own SlideRule
    request: the lower-Dnipro river (``kherson``) and the Dnipro-Buh liman
    (``dnipro_estuary``). Each has its own curated granule list and a spatial
    clip (bbox or polygon) applied to the pass-level table.
    """

    name: str
    slug: str
    refid: int
    coord_lon: float
    coord_lat: float
    seed_granules_file: Path
    clip_polygon: Path | None
    clip_bbox: tuple[float, float, float, float] | None
    repo_root: Path = field(default=REPO_ROOT)

    @property
    def raw_parquet(self) -> Path:
        return self.repo_root / "data" / "raw" / "atl13" / f"{self.slug}_atl13x_raw.parquet"

    @property
    def segments_parquet(self) -> Path:
        return self.repo_root / "data" / "processed" / f"{self.slug}_atl13_segments.parquet"

    @property
    def evrs_parquet(self) -> Path:
        return self.repo_root / "data" / "processed" / f"{self.slug}_atl13_evrs.parquet"

    @property
    def pass_levels_parquet(self) -> Path:
        return self.repo_root / "data" / "processed" / f"{self.slug}_atl13_pass_levels.parquet"

    @property
    def manifest(self) -> Path:
        return CONFIG_DIR / f"resources_manifest_downstream_{self.slug}.csv"


@dataclass(frozen=True)
class GaugesConfig:
    raw_dir: Path
    raw_format: str            # "reservoir_parquet" | "csv"
    timezone: str
    stage_units: str
    stations: tuple[GaugeStation, ...]
    downstream: tuple[DownstreamStation, ...] = ()

    def station(self, station_id: str) -> GaugeStation:
        for s in self.stations:
            if s.id == station_id:
                return s
        raise KeyError(station_id)

    def downstream_station(self, station_id: str) -> DownstreamStation:
        for s in self.downstream:
            if s.id == station_id:
                return s
        raise KeyError(station_id)


@dataclass(frozen=True)
class AlignmentConfig:
    """Phase-2 empirical vertical alignment constant between gauge stage and
    ICESat-2/EGG2015 WSE. It is NOT a Baltic-to-EVRS datum offset -- it also
    absorbs the gauge zero elevation and systematic ICESat/vertical-model bias.
    """

    adopted_constant_m: float | None      # applied by the pipeline once chosen (else None)
    per_station: dict[str, float]
    atl13_bias_m: float                   # assumed systematic ATL13 bias (m); notes only
    notes: str

    def constant_for(self, station_id) -> float | None:
        return self.per_station.get(station_id, self.adopted_constant_m)

    def adopted_for(self, station_id) -> bool:
        return self.constant_for(station_id) is not None


@dataclass(frozen=True)
class OfficialTransformConfig:
    """Official Baltic-1977 -> EVRF2019 grid (EPSG:9902) and the budget terms."""

    path: Path
    source: str
    source_url: str
    epsg_operation: int
    target_frame: str
    tide_system: str
    published_stats: dict[str, float]
    validation_tolerance_m: float
    expected_nodes: int | None
    evrf2019_minus_evrf2007_m: float
    tide_system_correction_m: float
    egg2015_accuracy_m: float
    atl13_bias_m: float

    @property
    def available(self) -> bool:
        return self.path.exists()

    @property
    def frame_terms_m(self) -> float:
        """Terms converting the official target frame to our EGG2015/EVRF2007 one."""
        return self.evrf2019_minus_evrf2007_m + self.tide_system_correction_m


@dataclass(frozen=True)
class Config:
    aoi_bbox: tuple[float, float, float, float]
    downstream_bodies: tuple[DownstreamBody, ...]
    aoi_polygon: Path
    aoi_polygon_layer: str
    atl13x: ATL13XConfig
    product: ProductConfig
    regimes: RegimeConfig
    qc: QCConfig
    matchup: MatchupConfig
    local_alignment: LocalAlignmentConfig
    egg2015: EGG2015Config
    egm2008_use_product_column: bool
    alignment: AlignmentConfig
    official_transform: OfficialTransformConfig
    gauges: GaugesConfig
    repo_root: Path = field(default=REPO_ROOT)

    # Convenience paths (all git-ignored except where noted).
    @property
    def seed_granules_file(self) -> Path:
        return CONFIG_DIR / "atl13_seed_granules.txt"

    @property
    def resources_manifest(self) -> Path:
        return CONFIG_DIR / "resources_manifest.csv"

    @property
    def processed_dir(self) -> Path:
        return self.repo_root / "data" / "processed"

    @property
    def interim_dir(self) -> Path:
        return self.repo_root / "data" / "interim"

    @property
    def raw_atl13_dir(self) -> Path:
        return self.repo_root / "data" / "raw" / "atl13"

    @property
    def raw_atl13x_parquet(self) -> Path:
        return self.raw_atl13_dir / "kakhovka_atl13x_raw.parquet"

    @property
    def tables_dir(self) -> Path:
        return self.repo_root / "outputs" / "tables"

    @property
    def reports_dir(self) -> Path:
        return self.repo_root / "outputs" / "reports"

    @property
    def segments_parquet(self) -> Path:
        return self.processed_dir / "kakhovka_atl13_segments.parquet"

    @property
    def evrs_parquet(self) -> Path:
        return self.processed_dir / "kakhovka_atl13_evrs.parquet"

    @property
    def pass_levels_parquet(self) -> Path:
        return self.processed_dir / "kakhovka_atl13_pass_levels.parquet"

    @property
    def gauge_matchups_parquet(self) -> Path:
        return self.processed_dir / "kakhovka_atl13_gauge_matchups.parquet"

    def downstream_body(self, slug: str) -> DownstreamBody:
        for b in self.downstream_bodies:
            if b.slug == slug:
                return b
        raise KeyError(slug)


def _as_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def load_config() -> Config:
    """Read ``config/{kakhovka,vertical_datums,gauges}.yaml`` into a :class:`Config`."""
    k = _load_yaml("kakhovka.yaml")
    v = _load_yaml("vertical_datums.yaml")
    g = _load_yaml("gauges.yaml")

    aoi = k["aoi"]
    x = k["atl13x"]
    p = k["product"]
    r = k["regimes"]
    q = k["qc"]
    m = k["matchup"]
    la = k.get("local_alignment", {})

    egg = v["egg2015"]
    al = v.get("alignment", {})
    ot = v.get("official_transform", {})

    stations = tuple(
        GaugeStation(
            id=s["id"],
            name=s.get("name", s["id"]),
            slug=s.get("slug", f"post_{s['id']}"),
            name_en=s.get("name_en", s.get("name", str(s["id"]))),
            lon=s.get("lon"),
            lat=s.get("lat"),
            gauge_zero_baltic_m=s.get("gauge_zero_baltic_m"),
            active_regimes=tuple(s.get("active_regimes", [])),
        )
        for s in g.get("stations", [])
    )

    downstream = tuple(
        DownstreamStation(
            id=s["id"],
            name=s.get("name", str(s["id"])),
            name_en=s.get("name_en", s.get("name", str(s["id"]))),
            slug=s.get("slug", f"post_{s['id']}"),
            lon=float(s["lon"]),
            lat=float(s["lat"]),
            role=s.get("role", "downstream_boundary"),
            gauge_zero_baltic_m=s.get("gauge_zero_baltic_m"),
            yearbook_csv=_resolve(s["series"]["yearbook_csv"])
            if s.get("series", {}).get("yearbook_csv") else None,
            parquet_dir=_resolve(s["series"]["parquet_dir"])
            if s.get("series", {}).get("parquet_dir") else None,
            parquet_versions_root=_resolve(s["series"]["parquet_versions_root"])
            if s.get("series", {}).get("parquet_versions_root") else None,
            yearbook_grid_csv=_resolve(s["series"]["yearbook_grid_csv"])
            if s.get("series", {}).get("yearbook_grid_csv") else None,
            coords_approx=bool(s.get("coords_approx", False)),
        )
        for s in g.get("downstream", [])
    )

    downstream_bodies = tuple(
        DownstreamBody(
            name=b["name"],
            slug=b["slug"],
            refid=int(b["refid"]),
            coord_lon=float(b["coord"]["lon"]),
            coord_lat=float(b["coord"]["lat"]),
            seed_granules_file=_resolve(b["seed_granules"]),
            clip_polygon=_resolve(b["clip"]["polygon"])
            if b.get("clip", {}).get("polygon") else None,
            clip_bbox=tuple(b["clip"]["bbox"])
            if b.get("clip", {}).get("bbox") else None,
        )
        for b in k.get("downstream_bodies", [])
    )

    return Config(
        aoi_bbox=tuple(aoi["bbox"]),  # type: ignore[arg-type]
        downstream_bodies=downstream_bodies,
        aoi_polygon=_resolve(aoi["polygon"]) if aoi.get("polygon") else Path("/nonexistent"),
        aoi_polygon_layer=aoi.get("polygon_layer") or None,
        atl13x=ATL13XConfig(
            refid=int(x["refid"]),
            coord_lon=float(x["coord"]["lon"]),
            coord_lat=float(x["coord"]["lat"]),
            domain=x.get("domain", "slideruleearth.io"),
            organization=x.get("organization"),
        ),
        product=ProductConfig(
            short_name=p.get("short_name", "ATL13"),
            version=str(p.get("version", "007")),
            start_date=_as_date(p.get("start_date", "2018-10-13")),
            end_date=_as_date(p.get("end_date")),
        ),
        regimes=RegimeConfig(
            pre_breach_end=_as_date(r["pre_breach_end"]),
            breach_start=_as_date(r["breach_start"]),
            post_breach_start=_as_date(r.get("post_breach_start") or r["post_reservoir_start"]),
        ),
        qc=QCConfig(
            min_points_per_pass=int(q["min_points_per_pass"]),
            max_mad_m=float(q["max_mad_m"]),
            max_range_m=float(q["max_range_m"]),
            min_track_length_km=float(q["min_track_length_km"]),
            max_stdev_water_surf_m=float(q["max_stdev_water_surf_m"]),
            max_along_track_slope_m_per_km=float(q["max_along_track_slope_m_per_km"]),
        ),
        matchup=MatchupConfig(
            max_time_difference_hours=float(m["max_time_difference_hours"]),
            max_distance_to_gauge_km=float(m["max_distance_to_gauge_km"]),
            gauge_interpolation=str(m.get("gauge_interpolation", "linear")),
        ),
        local_alignment=LocalAlignmentConfig(
            station_id=la.get("station_id", 80959),
            radii_km=tuple(float(x) for x in la.get("radii_km", [0.5, 1.0, 2.0, 3.0, 5.0])),
            main_radius_km=float(la.get("main_radius_km", 2.0)),
            diagnostic_radius_km=float(la.get("diagnostic_radius_km", 10.0)),
            min_points_per_local_pass=int(la.get("min_points_per_local_pass", 10)),
            max_local_nmad_m=float(la.get("max_local_nmad_m", 0.25)),
            max_deviation_from_reservoir_m=float(
                la.get("max_deviation_from_reservoir_m", 3.0)
            ),
            min_matchups_for_confidence=int(la.get("min_matchups_for_confidence", 5)),
        ),
        egg2015=EGG2015Config(
            path=_resolve(egg["path"]),
            grid_crs=egg.get("grid_crs", "EPSG:4258"),
            quantity=egg.get("quantity", "quasigeoid_height"),
            reference_ellipsoid=egg.get("reference_ellipsoid", "GRS80"),
            height_system=egg.get("height_system", "EVRF2007"),
            units=egg.get("units", "m"),
            resampling=egg.get("resampling", "bilinear"),
        ),
        egm2008_use_product_column=bool(
            v.get("egm2008", {}).get("use_product_column", True)
        ),
        alignment=AlignmentConfig(
            adopted_constant_m=al.get("adopted_constant_m"),
            per_station=dict(al.get("per_station") or {}),
            atl13_bias_m=float(al.get("atl13_bias_m", 0.0)),
            notes=al.get("notes", ""),
        ),
        official_transform=OfficialTransformConfig(
            path=_resolve(ot.get("path", "data/external/datum/ua_2019z.asc")),
            source=ot.get("source", ""),
            source_url=ot.get("source_url", ""),
            epsg_operation=int(ot.get("epsg_operation", 9902)),
            target_frame=ot.get("target_frame", "EVRF2019"),
            tide_system=ot.get("tide_system", "zero-tide"),
            published_stats=dict(ot.get("published_stats") or {}),
            validation_tolerance_m=float(ot.get("validation_tolerance_m", 0.02)),
            expected_nodes=ot.get("expected_nodes"),
            evrf2019_minus_evrf2007_m=float(ot.get("evrf2019_minus_evrf2007_m", 0.0)),
            tide_system_correction_m=float(ot.get("tide_system_correction_m", 0.0)),
            egg2015_accuracy_m=float(ot.get("egg2015_accuracy_m", 0.10)),
            atl13_bias_m=float(ot.get("atl13_bias_m", 0.0)),
        ),
        gauges=GaugesConfig(
            raw_dir=_resolve(g.get("raw", {}).get("dir", "data/raw/gauges")),
            raw_format=g.get("raw", {}).get("format", "csv"),
            timezone=g.get("raw", {}).get("timezone", "kyiv"),
            stage_units=g.get("raw", {}).get("stage_units", "cm"),
            stations=stations,
            downstream=downstream,
        ),
    )
