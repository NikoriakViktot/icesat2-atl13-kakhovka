"""ATL13 granule discovery and the reproducibility manifest.

Two sources feed the manifest:

* ``config/atl13_seed_granules.txt`` -- the canonical, human-curated seed list
  (rebuilt from the original SlideRule web-client request).
* :func:`refresh` -- a live CMR query (via ``earthaccess``) for ATL13 v7 granules
  intersecting the AOI between ``product.start_date`` and today.

:func:`build_manifest` merges the two and writes ``config/resources_manifest.csv``
with one row per granule and the columns needed to re-run the pipeline exactly.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .config import Config

# ATL13_<yyyymmddhhmmss>_<RGT4><CC2><RR2>_<release3>_<version2>.h5
_GRANULE_RE = re.compile(
    r"^ATL13_(?P<ts>\d{14})_(?P<rgt>\d{4})(?P<cycle>\d{2})(?P<region>\d{2})_"
    r"(?P<release>\d{3})_(?P<version>\d{2})\.h5$"
)

MANIFEST_COLUMNS = [
    "granule",
    "acquisition_time",
    "rgt",
    "cycle",
    "region",
    "release",
    "version",
    "refid",
    "source",        # "seed" | "cmr" | "seed+cmr"
    "query_date",
]


@dataclass(frozen=True)
class GranuleInfo:
    granule: str
    acquisition_time: dt.datetime
    rgt: int
    cycle: int
    region: int
    release: str
    version: str

    @classmethod
    def parse(cls, name: str) -> GranuleInfo:
        name = name.strip()
        m = _GRANULE_RE.match(name)
        if not m:
            raise ValueError(f"not an ATL13 granule filename: {name!r}")
        return cls(
            granule=name,
            acquisition_time=dt.datetime.strptime(m["ts"], "%Y%m%d%H%M%S").replace(
                tzinfo=dt.UTC
            ),
            rgt=int(m["rgt"]),
            cycle=int(m["cycle"]),
            region=int(m["region"]),
            release=m["release"],
            version=m["version"],
        )


def read_seed_granules(cfg: Config) -> list[str]:
    """Return the granule filenames listed in ``config/atl13_seed_granules.txt``."""
    out: list[str] = []
    for line in cfg.seed_granules_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def refresh(cfg: Config, *, end_date: dt.date | None = None) -> list[str]:
    """Live CMR search for ATL13 v7 granules over the AOI. Returns granule names.

    Requires network access and (for some assets) Earthdata Login credentials in
    the environment / ``~/.netrc``. Raises ``RuntimeError`` with a helpful message
    if ``earthaccess`` is unavailable.
    """
    return cmr_granules(
        cfg.aoi_bbox,
        cfg.product.start_date,
        end_date or cfg.product.end_date or dt.date.today(),
        short_name=cfg.product.short_name,
        version=cfg.product.version,
    )


def cmr_granules(
    bbox: tuple[float, float, float, float],
    start: dt.date,
    end: dt.date,
    *,
    short_name: str = "ATL13",
    version: str = "007",
) -> list[str]:
    """CMR search for granules intersecting ``bbox`` in ``[start, end]``."""
    try:
        import earthaccess
    except ImportError as exc:  # pragma: no cover - env dependent
        raise RuntimeError(
            "earthaccess is not installed; `pip install earthaccess` to use refresh()"
        ) from exc

    lon_min, lat_min, lon_max, lat_max = bbox
    earthaccess.login(strategy="environment", persist=False)
    results = earthaccess.search_data(
        short_name=short_name,
        version=version,
        bounding_box=(lon_min, lat_min, lon_max, lat_max),
        temporal=(start.isoformat(), end.isoformat()),
    )
    names: list[str] = []
    for r in results:
        for link in r.data_links():
            base = link.split("/")[-1]
            if base.startswith("ATL13_") and base.endswith(".h5"):
                names.append(base)
    return sorted(set(names))


def build_manifest(
    cfg: Config,
    *,
    include_cmr: bool = False,
    end_date: dt.date | None = None,
    write: bool = True,
) -> pd.DataFrame:
    """Merge seed + (optional) CMR granules into the manifest DataFrame.

    When ``write`` is True the frame is saved to ``config/resources_manifest.csv``.
    """
    seed = set(read_seed_granules(cfg))
    cmr: set[str] = set()
    if include_cmr:
        cmr = set(refresh(cfg, end_date=end_date))

    all_names = sorted(seed | cmr)
    today = dt.date.today().isoformat()
    rows: list[dict] = []
    for name in all_names:
        info = GranuleInfo.parse(name)
        if name in seed and name in cmr:
            src = "seed+cmr"
        elif name in seed:
            src = "seed"
        else:
            src = "cmr"
        d = asdict(info)
        d["acquisition_time"] = info.acquisition_time.isoformat()
        d["refid"] = cfg.atl13x.refid
        d["source"] = src
        d["query_date"] = today
        rows.append(d)

    df = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    if write:
        cfg.resources_manifest.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cfg.resources_manifest, index=False)
    return df


def read_manifest(cfg: Config) -> pd.DataFrame:
    """Load ``config/resources_manifest.csv`` (building it from the seed if absent)."""
    path = cfg.resources_manifest
    if not path.exists():
        return build_manifest(cfg, include_cmr=False, write=True)
    df = pd.read_csv(path, dtype={"release": str, "version": str})
    df["acquisition_time"] = pd.to_datetime(df["acquisition_time"], utc=True)
    return df


def manifest_granules(cfg: Config, *, path: Path | None = None) -> list[str]:
    """Return the ordered list of granule filenames from the manifest."""
    df = read_manifest(cfg) if path is None else pd.read_csv(path)
    return list(df.sort_values("acquisition_time")["granule"])
