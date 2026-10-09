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
class ApiClient:
    """Who is calling: one entry of ``API_KEYS``."""

    name: str
    read_only: bool = False


def parse_api_keys(raw: str | None) -> dict[str, ApiClient]:
    """``API_KEYS`` -> {key: client}. Comma-separated entries, each one of

    * ``<key>``                  client ``default``, read/write (legacy form)
    * ``<name>:<key>``           named client, read/write (e.g. the Django BFF)
    * ``<name>:<key>:ro``        named client, read-only (e.g. a browser frontend)
    """
    out: dict[str, ApiClient] = {}
    for entry in (raw or "").split(","):
        parts = [p.strip() for p in entry.strip().split(":")]
        if not parts[0]:
            continue
        if len(parts) == 1:
            out[parts[0]] = ApiClient("default")
        elif len(parts) == 2:
            out[parts[1]] = ApiClient(parts[0])
        elif len(parts) == 3 and parts[2] in ("ro", "rw"):
            out[parts[1]] = ApiClient(parts[0], read_only=parts[2] == "ro")
        else:
            raise ValueError(f"bad API_KEYS entry {entry!r}: use key | name:key | name:key:ro")
    return out


@dataclass(frozen=True, eq=False)
class Settings:
    database_url: str
    s3_bucket: str
    s3_prefix: str
    redis_url: str
    api_keys: dict[str, ApiClient]
    cors_origins: tuple[str, ...]   # browser origins allowed to call the API
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
        api_keys=parse_api_keys(_env("API_KEYS", "")),
        cors_origins=tuple(o.strip() for o in (_env("CORS_ORIGINS", "") or "").split(",")
                           if o.strip()),
        job_runner=_env("JOB_RUNNER", "rq"),
        egg2015_uri=_env("EGG2015_URI"),
        cache_dir=Path(_env("CACHE_DIR", "/tmp/icesat2-cache")),
        batch_size=int(_env("BATCH_SIZE", "50")),
        fetch_retries=int(_env("FETCH_RETRIES", "3")),
    )
