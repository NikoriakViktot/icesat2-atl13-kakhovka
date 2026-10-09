"""Service settings, all from the environment (see ``.env.example``).

S3 credentials and a custom endpoint (local S3) are read by s3fs/botocore from the
standard ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` / ``AWS_ENDPOINT_URL``
variables; Earthdata credentials from ``EARTHDATA_USERNAME`` / ``EARTHDATA_PASSWORD``
(read by earthaccess). None of these are ever accepted in a request body.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    s3_bucket: str
    s3_prefix: str
    redis_url: str
    api_keys: frozenset[str]
    job_runner: str            # "rq" | "inline"
    egg2015_uri: str | None    # s3://... ; None -> config/vertical_datums.yaml path
    cache_dir: Path
    batch_size: int
    fetch_retries: int

    @property
    def s3_root(self) -> str:
        return f"s3://{self.s3_bucket}/{self.s3_prefix.strip('/')}"


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=_env("DATABASE_URL", "postgresql://icesat2:icesat2@localhost:55433/icesat2"),
        s3_bucket=_env("S3_BUCKET", "icesat2"),
        s3_prefix=_env("S3_PREFIX", "icesat2"),
        redis_url=_env("REDIS_URL", "redis://localhost:56379/0"),
        api_keys=frozenset(k.strip() for k in (_env("API_KEYS", "") or "").split(",") if k.strip()),
        job_runner=_env("JOB_RUNNER", "rq"),
        egg2015_uri=_env("EGG2015_URI"),
        cache_dir=Path(_env("CACHE_DIR", "/tmp/icesat2-cache")),
        batch_size=int(_env("BATCH_SIZE", "50")),
        fetch_retries=int(_env("FETCH_RETRIES", "3")),
    )
