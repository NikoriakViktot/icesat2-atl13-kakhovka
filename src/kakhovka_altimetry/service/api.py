"""HTTP API: queue ingest jobs and read results back from PostGIS.

    uvicorn kakhovka_altimetry.service.api:app

Every endpoint except ``/health`` needs an ``X-API-Key`` header listed in the
``API_KEYS`` environment variable. The request only describes *what* to ingest
(region + dates); Earthdata / S3 credentials live in the service environment.
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from ..config import load_config
from ..regions import KINDS, configured_regions
from .repository import Repository
from .settings import Settings, get_settings

app = FastAPI(title="ICESat-2 ATL13 ingest", version="0.1.0")


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #
class Coord(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class RegionIn(BaseModel):
    """An ad-hoc region: one ATL13 reference water body + its clip."""

    slug: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    name: str | None = None
    refid: int
    coord: Coord
    kind: Literal["reservoir", "river"] = "river"
    bbox: tuple[float, float, float, float] | None = None
    polygon: dict[str, Any] | None = Field(default=None, description="GeoJSON geometry")

    @model_validator(mode="after")
    def _clip(self):
        if self.bbox is None and self.polygon is None:
            raise ValueError("region needs a bbox or a polygon")
        return self


class JobIn(BaseModel):
    region_slug: str | None = Field(default=None, description="a configured region")
    region: RegionIn | None = Field(default=None, description="or an ad-hoc region")
    start: dt.date | None = None
    end: dt.date | None = None
    include_cmr: bool = Field(default=False, description="merge a live CMR search")
    limit: int | None = Field(default=None, ge=1, description="max granules this job")
    batch_size: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def _one_region(self):
        if (self.region_slug is None) == (self.region is None):
            raise ValueError("give exactly one of region_slug / region")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start is after end")
        return self


class JobOut(BaseModel):
    job_id: str
    region: str
    status: str
    stage: str | None = None
    stats: dict[str, Any] = {}
    params: dict[str, Any] = {}
    error: str | None = None
    created_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None


# --------------------------------------------------------------------------- #
# Dependencies                                                                 #
# --------------------------------------------------------------------------- #
def settings_dep() -> Settings:
    return get_settings()


def repo_dep(settings: Annotated[Settings, Depends(settings_dep)]) -> Repository:
    return Repository(settings.database_url)


def require_key(
    settings: Annotated[Settings, Depends(settings_dep)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if not x_api_key or x_api_key not in settings.api_keys:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


Auth = Depends(require_key)
Repo = Annotated[Repository, Depends(repo_dep)]


def _enqueue(job_id: str, settings: Settings, background: BackgroundTasks) -> None:
    from . import worker

    if settings.job_runner == "inline":
        background.add_task(_run_quietly, job_id)
        return
    from redis import Redis
    from rq import Queue

    Queue("icesat2", connection=Redis.from_url(settings.redis_url)).enqueue(
        worker.run_job, job_id, job_timeout=6 * 3600, result_ttl=86400,
    )


def _run_quietly(job_id: str) -> None:
    from . import worker

    try:
        worker.run_job(job_id)
    except Exception:  # noqa: BLE001 - recorded in icesat2.jobs by run_job
        pass


def _job_out(row: dict) -> JobOut:
    return JobOut(**{**row, "job_id": str(row["job_id"])})


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", status_code=202, response_model=JobOut, dependencies=[Auth])
def create_job(body: JobIn, background: BackgroundTasks, repo: Repo,
               settings: Annotated[Settings, Depends(settings_dep)]) -> JobOut:
    if body.region_slug is not None:
        regions = configured_regions(load_config())
        if body.region_slug not in regions:
            raise HTTPException(404, f"unknown region {body.region_slug!r}; "
                                     f"configured: {sorted(regions)}")
        slug = body.region_slug
    else:
        slug = body.region.slug
        if slug in configured_regions(load_config()):
            raise HTTPException(409, f"{slug!r} is a configured region; use region_slug")
    params = body.model_dump(mode="json")
    job_id = repo.create_job(slug, params)
    _enqueue(job_id, settings, background)
    return _job_out(repo.get_job(job_id))


@app.get("/jobs", response_model=list[JobOut], dependencies=[Auth])
def list_jobs(repo: Repo, region: str | None = None,
              limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[JobOut]:
    return [_job_out(r) for r in repo.list_jobs(region, limit)]


@app.get("/jobs/{job_id}", response_model=JobOut, dependencies=[Auth])
def get_job(job_id: str, repo: Repo) -> JobOut:
    try:
        row = repo.get_job(job_id)
    except Exception:  # noqa: BLE001 - malformed uuid
        row = None
    if row is None:
        raise HTTPException(404, "job not found")
    return _job_out(row)


@app.get("/regions", dependencies=[Auth])
def list_regions(repo: Repo) -> list[dict[str, Any]]:
    configured = configured_regions(load_config())
    out = [{
        "slug": r.slug, "name": r.name, "kind": r.kind, "refid": r.refid,
        "coord": {"lon": r.coord_lon, "lat": r.coord_lat}, "bbox": r.search_bbox,
        "configured": True, **repo.counts(r.slug),
    } for r in configured.values()]
    for slug in repo.known_regions():
        if slug not in configured:
            out.append({"slug": slug, "configured": False, **repo.counts(slug)})
    return out


@app.get("/regions/{slug}/pass-levels", dependencies=[Auth])
def pass_levels(slug: str, repo: Repo, start: dt.date | None = None, end: dt.date | None = None,
                qc_pass: bool | None = None,
                format: Literal["geojson", "csv"] = "geojson"):  # noqa: A002
    if format == "csv":
        df = repo.pass_levels_frame(slug, start=start, end=end, qc_pass=qc_pass)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{slug}_pass_levels.csv"'})
    return JSONResponse(repo.pass_levels_geojson(slug, start=start, end=end, qc_pass=qc_pass),
                        media_type="application/geo+json")


@app.get("/granules", dependencies=[Auth])
def granules(repo: Repo, region: str | None = None, status: str | None = None) -> list[dict]:
    rows = repo.list_granules(region, status)
    return [{**r, "job_id": str(r["job_id"]) if r["job_id"] else None} for r in rows]


assert set(KINDS) == {"reservoir", "river"}  # keep RegionIn.kind in sync with regions.KINDS
