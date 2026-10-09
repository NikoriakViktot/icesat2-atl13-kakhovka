"""S3 layout of the service. Every URI the worker touches is built here.

    <root>/reference/egg_2015.tif
    <root>/reference/{cop30,fabdem}/<tile>.tif              (reference-DEM tile cache)
    <root>/<product>/v<ver>/<region>/raw/run=<job_id>/batch_<nnn>.parquet
    <root>/<product>/v<ver>/<region>/processed/points/run=<job_id>.parquet
    <root>/<product>/v<ver>/<region>/processed/pass_levels/run=<job_id>.parquet  (ATL13)
    <root>/<product>/v<ver>/<region>/dem/run=<job_id>/<variable>_<res>m.tif      (COG)
    <root>/<product>/v<ver>/<region>/manifest/run=<job_id>.csv

``<product>`` is lower case (``atl13``, ``atl08``, ``atl03``).

The raw layer is immutable (one ``run=`` per job), so any processing can be re-run
from S3 without hitting SlideRule again.
"""

from __future__ import annotations

from pathlib import Path

import fsspec
import pandas as pd

from .settings import Settings


class Layout:
    def __init__(self, settings: Settings, region: str, version: str = "007",
                 product: str = "ATL13"):
        self.root = settings.s3_root
        self.base = f"{self.root}/{product.lower()}/v{version}/{region}"

    def reference_prefix(self, dem_name: str) -> str:
        """Tile cache of a reference DEM (``cop30``, ``fabdem``)."""
        return f"{self.root}/reference/{dem_name}"

    def raster(self, job_id: str, variable: str, resolution_m: float) -> str:
        return f"{self.base}/dem/run={job_id}/{variable}_{resolution_m:g}m.tif"

    def raw_batch(self, job_id: str, batch: int) -> str:
        return f"{self.base}/raw/run={job_id}/batch_{batch:03d}.parquet"

    def raw_dir(self, job_id: str) -> str:
        return f"{self.base}/raw/run={job_id}"

    def points(self, job_id: str) -> str:
        return f"{self.base}/processed/points/run={job_id}.parquet"

    def pass_levels(self, job_id: str) -> str:
        return f"{self.base}/processed/pass_levels/run={job_id}.parquet"

    def manifest(self, job_id: str) -> str:
        return f"{self.base}/manifest/run={job_id}.csv"


def list_parquet(uri_dir: str) -> list[str]:
    fs, path = fsspec.core.url_to_fs(uri_dir)
    if not fs.exists(path):
        return []
    proto = uri_dir.split("://", 1)[0]
    return sorted(f"{proto}://{p}" for p in fs.ls(path, detail=False) if p.endswith(".parquet"))


def read_concat(uris: list[str]) -> pd.DataFrame:
    frames = [pd.read_parquet(u) for u in uris]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def put_file(local: Path, uri: str) -> None:
    fs, path = fsspec.core.url_to_fs(uri)
    fs.put(str(local), path)


def open_binary(uri: str):
    return fsspec.open(uri, "rb").open()


def write_text(uri: str, text: str) -> None:
    with fsspec.open(uri, "w", encoding="utf-8") as fh:
        fh.write(text)


def fetch_to_cache(uri: str, cache_dir: Path) -> Path:
    """Download ``uri`` once into ``cache_dir`` and return the local path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / uri.rstrip("/").rsplit("/", 1)[-1]
    if not local.exists():
        fs, path = fsspec.core.url_to_fs(uri)
        tmp = local.with_suffix(local.suffix + ".part")
        fs.get(path, str(tmp))
        tmp.rename(local)
    return local
