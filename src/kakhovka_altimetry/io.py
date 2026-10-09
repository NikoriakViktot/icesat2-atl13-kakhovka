"""Small parquet IO helpers with consistent logging.

Paths may be local (``Path`` / str) or remote URIs (``s3://bucket/key``). Remote
URIs go through ``fsspec`` / ``s3fs``; credentials and a custom endpoint (local S3)
come from the standard ``AWS_*`` environment variables, e.g. ``AWS_ENDPOINT_URL``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("kakhovka_altimetry")

PathLike = str | Path


def is_remote(path: PathLike) -> bool:
    return isinstance(path, str) and "://" in path


def write_parquet(df: pd.DataFrame, path: PathLike, *, label: str | None = None) -> PathLike:
    if is_remote(path):
        df.to_parquet(path, index=False)
        name = path.rstrip("/").rsplit("/", 1)[-1]
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        name = path.stem
    log.info("wrote %s (%d rows, %d cols) -> %s", label or name, len(df), df.shape[1], path)
    return path


def read_parquet(path: PathLike) -> pd.DataFrame:
    if is_remote(path):
        import fsspec

        fs, fs_path = fsspec.core.url_to_fs(path)
        if not fs.exists(fs_path):
            raise FileNotFoundError(f"{path} not found -- run the upstream pipeline step first.")
        return pd.read_parquet(path)
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run the upstream pipeline step first."
        )
    return pd.read_parquet(path)


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
