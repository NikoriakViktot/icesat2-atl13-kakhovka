"""S3 layout of the service. Every URI the worker touches is built here.

    <root>/reference/egg_2015.tif
    <root>/atl13/v<ver>/<region>/raw/run=<job_id>/batch_<nnn>.parquet
    <root>/atl13/v<ver>/<region>/processed/segments_evrs/run=<job_id>.parquet
    <root>/atl13/v<ver>/<region>/processed/pass_levels/run=<job_id>.parquet
    <root>/atl13/v<ver>/<region>/manifest/run=<job_id>.csv

The raw layer is immutable (one ``run=`` per job), so any processing can be re-run
from S3 without hitting SlideRule again.
"""

from __future__ import annotations

from pathlib import Path

import fsspec
import pandas as pd

from .settings import Settings


class Layout:
    def __init__(self, settings: Settings, region: str, version: str = "007"):
        self.root = settings.s3_root
        self.base = f"{self.root}/atl13/v{version}/{region}"

    def raw_batch(self, job_id: str, batch: int) -> str:
        return f"{self.base}/raw/run={job_id}/batch_{batch:03d}.parquet"

    def raw_dir(self, job_id: str) -> str:
        return f"{self.base}/raw/run={job_id}"

    def segments(self, job_id: str) -> str:
        return f"{self.base}/processed/segments_evrs/run={job_id}.parquet"

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
