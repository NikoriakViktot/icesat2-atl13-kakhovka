"""HTTP API: register regions, queue ICESat-2 ingest jobs, read results back.

    uvicorn kakhovka_altimetry.service.api:app        # OpenAPI UI at /docs

Every endpoint except ``/health`` needs an ``X-API-Key`` header listed in the
``API_KEYS`` environment variable (``name:key`` read/write, ``name:key:ro`` read-only).
A trusted client acting for its own users (the Django BFF) sends ``X-Requested-By``;
it is recorded on jobs and regions. Browser origins allowed by CORS: ``CORS_ORIGINS``.
Requests only describe *what* to ingest (product + region + dates + options);
Earthdata / S3 credentials live in the service environment. Agent-oriented usage
notes: ``docs/agents-api.md``; frontend / BFF integration: ``docs/frontend.md``.
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .. import dem, products
from ..config import load_config
from ..regions import configured_regions, region_from_dict
from . import storage
from .repository import Repository
from .settings import ApiClient, Settings, get_settings

app = FastAPI(
    title="ICESat-2 ingest",
    version="0.2.0",
    description=(
        "Queue ICESat-2 ATL13 (inland water), ATL08 (terrain + canopy) and ATL03 "
        "(photons) pulls over any region via SlideRule; results land in S3 (parquet, "
        "COG rasters) and PostGIS. Jobs are asynchronous: POST /jobs, then poll "
        "GET /jobs/{job_id} until status is 'done' or 'failed'."
    ),
)

if get_settings().cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(get_settings().cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "X-Requested-By", "Content-Type"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )

ProductName = Literal["ATL13", "ATL08", "ATL03"]


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #
class Coord(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class RegionIn(BaseModel):
    """Any area of interest. ``coord`` is required only for ATL13 (a point on the water)."""

    slug: str = Field(pattern=r"^[a-z0-9_]{2,64}$", description="unique id, [a-z0-9_]")
    name: str | None = None
    coord: Coord | None = Field(default=None, description="ATL13: a point on the water body")
    refid: int | None = Field(default=None, description="ATL13 reference water body id")
    kind: Literal["lake", "reservoir", "river"] = Field(
        default="lake", description="ATL13 QC: still water (lake/reservoir) or river")
    vertical: Literal["egm2008", "egg2015"] = Field(
        default="egm2008", description="egm2008: global; egg2015: Europe only (EVRS)")
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="lon_min, lat_min, lon_max, lat_max (EPSG:4326)")
    polygon: dict[str, Any] | None = Field(default=None, description="GeoJSON geometry")

    @model_validator(mode="after")
    def _clip(self):
        if self.bbox is None and self.polygon is None:
            raise ValueError("region needs a bbox or a polygon")
        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if not (x0 < x1 and y0 < y1):
                raise ValueError("bbox must be lon_min < lon_max and lat_min < lat_max")
        return self

    def definition(self) -> dict[str, Any]:
        d = self.model_dump(mode="json")
        d["regimes"] = False
        return d


class Atl03Options(BaseModel):
    cnf: int = Field(default=4, ge=0, le=4, description="minimum ATL03 signal confidence")
    atl08_class: list[str] | None = Field(
        default=None, description=f"keep only these ATL08 photon classes: "
                                  f"{list(products.ATL08_CLASSES)}")


class DemOptions(BaseModel):
    resolution_m: float = Field(default=100, ge=10, le=10_000)
    variables: list[str] | None = Field(
        default=None, description="ATL08: dtm, chm; ATL03: dtm; ATL13: wse. Default: all")


class JobIn(BaseModel):
    product: ProductName = "ATL13"
    region_slug: str | None = Field(default=None, description="a configured/registered region")
    region: RegionIn | None = Field(default=None, description="or an ad-hoc region (registered)")
    start: dt.date | None = None
    end: dt.date | None = None
    include_cmr: bool | None = Field(
        default=None, description="search CMR for granules; default: yes unless the region "
                                  "has a curated ATL13 seed list")
    limit: int | None = Field(default=None, ge=1, description="max granules this job")
    batch_size: int | None = Field(default=None, ge=1, le=200)
    compare: list[Literal["cop30", "fabdem"]] = Field(
        default_factory=list, description="reference DEMs to compare ICESat-2 against")
    dem: DemOptions | None = Field(default=None, description="grid points into COG rasters")
    atl03: Atl03Options | None = None

    @model_validator(mode="after")
    def _checks(self):
        if (self.region_slug is None) == (self.region is None):
            raise ValueError("give exactly one of region_slug / region")
        if self.start and self.end and self.start > self.end:
            raise ValueError("start is after end")
        if self.atl03 is not None and self.product != "ATL03":
            raise ValueError("atl03 options only apply to product ATL03")
        if self.atl03 and self.atl03.atl08_class:
            bad = set(self.atl03.atl08_class) - set(products.ATL08_CLASSES)
            if bad:
                raise ValueError(f"unknown atl08_class {sorted(bad)}")
        if self.dem and self.dem.variables:
            known = products.get(self.product).dem_variables
            bad = set(self.dem.variables) - set(known)
            if bad:
                raise ValueError(f"{self.product} raster variables are {sorted(known)}")
        if self.product == "ATL13" and self.region is not None and self.region.coord is None:
            raise ValueError("ATL13 needs region.coord (a point on the water body)")
        return self


class JobOut(BaseModel):
    job_id: str
    region: str
    product: str = "ATL13"
    status: str = Field(description="queued | running | done | failed")
    stage: str | None = Field(default=None, description="discover | acquire | process | load")
    stats: dict[str, Any] = {}
    params: dict[str, Any] = {}
    error: str | None = None
    created_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    client: str | None = Field(default=None, description="API key name that created the job")
    requested_by: str | None = Field(default=None, description="end user (X-Requested-By)")


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
) -> ApiClient:
    client = settings.api_keys.get(x_api_key or "")
    if client is None:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")
    return client


def require_write(client: Annotated[ApiClient, Depends(require_key)]) -> ApiClient:
    if client.read_only:
        raise HTTPException(status_code=403, detail=f"API key {client.name!r} is read-only")
    return client


def requested_by(
    x_requested_by: Annotated[str | None, Header(
        max_length=200, description="end user the calling client acts for (BFF)")] = None,
) -> str | None:
    return x_requested_by or None


Auth = Depends(require_key)
Repo = Annotated[Repository, Depends(repo_dep)]
Writer = Annotated[ApiClient, Depends(require_write)]
RequestedBy = Annotated[str | None, Depends(requested_by)]


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


def _register(repo: Repository, region: RegionIn, client: ApiClient,
              user: str | None) -> dict[str, Any]:
    if region.slug in configured_regions(load_config()):
        raise HTTPException(409, f"{region.slug!r} is a configured region; use region_slug")
    definition = region.definition()
    footprint = region_from_dict(definition).clip_geometry()
    if not repo.upsert_region(definition, footprint.wkt, client=client.name,
                              requested_by=user):
        raise HTTPException(409, f"region {region.slug!r} belongs to another owner; "
                                 f"choose another slug")
    return definition


def _known_region(repo: Repository, slug: str) -> None:
    if slug in configured_regions(load_config()) or repo.get_region(slug) is not None:
        return
    raise HTTPException(404, f"unknown region {slug!r}; register it with POST /regions")


def _csv(df, filename: str) -> StreamingResponse:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products", tags=["meta"], dependencies=[Auth])
def list_products() -> list[dict[str, Any]]:
    """Supported products, their raster variables and reference DEMs."""
    return [{
        "product": p.name, "sliderule_api": p.api, "version": p.version,
        "height": p.height_col, "needs_coord": p.needs_coord,
        "points_in_postgis": p.points_in_db, "default_batch_size": p.default_batch,
        "raster_variables": {k: v[1] for k, v in p.dem_variables.items()},
        "reference_dems": list(dem.REFERENCE_DEMS),
    } for p in products.PRODUCTS.values()]


@app.post("/regions", status_code=201, tags=["regions"])
def register_region(body: RegionIn, repo: Repo, client: Writer,
                    user: RequestedBy) -> dict[str, Any]:
    """Register (or update) an area of interest under ``slug``. Only the owner that
    created a slug (same API client and same ``X-Requested-By``) can update it."""
    return _register(repo, body, client, user)


@app.get("/regions", tags=["regions"], dependencies=[Auth])
def list_regions(repo: Repo, requested_by: str | None = None, client: str | None = None,
                 configured: bool = True) -> list[dict[str, Any]]:
    """Configured regions (unless ``configured=false``) + registered ones, optionally
    only those of one owner (``client`` / ``requested_by``)."""
    out = []
    if configured and not (requested_by or client):
        out = [{**r.to_dict(), "configured": True, "counts": repo.counts(r.slug)}
               for r in configured_regions(load_config()).values()]
    for d in repo.list_regions(client=client, requested_by=requested_by):
        out.append({**d, "configured": False, "counts": repo.counts(d["slug"])})
    return out


@app.get("/regions/{slug}", tags=["regions"], dependencies=[Auth])
def get_region(slug: str, repo: Repo) -> dict[str, Any]:
    configured = configured_regions(load_config())
    if slug in configured:
        return {**configured[slug].to_dict(), "configured": True, "counts": repo.counts(slug)}
    row = repo.get_region_row(slug)
    if row is None:
        raise HTTPException(404, "region not found")
    return {**row["definition"], "configured": False, "client": row["client"],
            "requested_by": row["requested_by"], "counts": repo.counts(slug)}


@app.post("/jobs", status_code=202, response_model=JobOut, tags=["jobs"])
def create_job(body: JobIn, background: BackgroundTasks, repo: Repo, client: Writer,
               user: RequestedBy,
               settings: Annotated[Settings, Depends(settings_dep)]) -> JobOut:
    """Queue an ingest job. Poll ``GET /jobs/{job_id}`` for progress."""
    if body.region is not None:
        slug = _register(repo, body.region, client, user)["slug"]
    else:
        slug = body.region_slug
        _known_region(repo, slug)
    if body.product == "ATL13" and body.region is None:
        cfg_regions = configured_regions(load_config())
        d = cfg_regions[slug].to_dict() if slug in cfg_regions else repo.get_region(slug)
        if not (d and d.get("coord")):
            raise HTTPException(422, f"ATL13 needs a coord on region {slug!r}")
    params = body.model_dump(mode="json", exclude={"region"})
    params["region_slug"] = slug
    job_id = repo.create_job(slug, params, body.product, client=client.name,
                             requested_by=user)
    _enqueue(job_id, settings, background)
    return _job_out(repo.get_job(job_id))


@app.get("/jobs", response_model=list[JobOut], tags=["jobs"], dependencies=[Auth])
def list_jobs(repo: Repo, region: str | None = None, product: ProductName | None = None,
              requested_by: str | None = None, client: str | None = None,
              limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[JobOut]:
    """Newest first; filter by owner with ``client`` / ``requested_by``."""
    return [_job_out(r) for r in repo.list_jobs(region, product, limit, client=client,
                                                requested_by=requested_by)]


@app.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"], dependencies=[Auth])
def get_job(job_id: str, repo: Repo) -> JobOut:
    try:
        row = repo.get_job(job_id)
    except Exception:  # noqa: BLE001 - malformed uuid
        row = None
    if row is None:
        raise HTTPException(404, "job not found")
    return _job_out(row)


@app.get("/regions/{slug}/pass-levels", tags=["results"], dependencies=[Auth])
def pass_levels(slug: str, repo: Repo, start: dt.date | None = None,
                end: dt.date | None = None, qc_pass: bool | None = None,
                format: Literal["geojson", "csv"] = "geojson"):  # noqa: A002
    """ATL13 water levels, one per (date, rgt, beam)."""
    if format == "csv":
        return _csv(repo.pass_levels_frame(slug, start=start, end=end, qc_pass=qc_pass),
                    f"{slug}_pass_levels.csv")
    return JSONResponse(repo.pass_levels_geojson(slug, start=start, end=end, qc_pass=qc_pass),
                        media_type="application/geo+json")


@app.get("/regions/{slug}/points", tags=["results"], dependencies=[Auth])
def points(slug: str, repo: Repo, product: Literal["ATL13", "ATL08"] = "ATL08",
           start: dt.date | None = None, end: dt.date | None = None,
           limit: Annotated[int, Query(ge=1, le=1_000_000)] = 100_000,
           format: Literal["csv", "json"] = "csv"):  # noqa: A002
    """ATL13 segments / ATL08 segments as rows (ATL03 photons live only in S3)."""
    df = repo.points_frame(product, slug, start=start, end=end, limit=limit)
    if format == "json":
        return Response(df.to_json(orient="records", date_format="iso"),
                        media_type="application/json")
    return _csv(df, f"{slug}_{product.lower()}_points.csv")


@app.get("/rasters", tags=["results"], dependencies=[Auth])
def list_rasters(repo: Repo, region: str | None = None, product: ProductName | None = None,
                 variable: str | None = None, job_id: str | None = None) -> list[dict]:
    rows = repo.list_rasters(region=region, product=product, variable=variable, job_id=job_id)
    return [{**r, "raster_id": str(r["raster_id"]), "job_id": str(r["job_id"])} for r in rows]


@app.get("/rasters/{raster_id}", tags=["results"], dependencies=[Auth])
def get_raster(raster_id: str, repo: Repo) -> dict:
    row = repo.get_raster(raster_id)
    if row is None:
        raise HTTPException(404, "raster not found")
    return {**row, "raster_id": str(row["raster_id"]), "job_id": str(row["job_id"])}


@app.get("/rasters/{raster_id}/download", tags=["results"], dependencies=[Auth])
def download_raster(raster_id: str, repo: Repo) -> StreamingResponse:
    """The COG itself (band 1 = value, band 2 = ICESat-2 points per cell)."""
    row = repo.get_raster(raster_id)
    if row is None:
        raise HTTPException(404, "raster not found")
    fh = storage.open_binary(row["s3_uri"])
    name = row["s3_uri"].rsplit("/", 1)[-1]

    def chunks():
        with fh:
            while data := fh.read(1 << 20):
                yield data

    return StreamingResponse(chunks(), media_type="image/tiff", headers={
        "Content-Disposition": f'attachment; filename="{row["region"]}_{name}"'})


@app.get("/dem-comparisons", tags=["results"], dependencies=[Auth])
def dem_comparisons(repo: Repo, job_id: str | None = None,
                    region: str | None = None) -> list[dict]:
    """ICESat-2 (EGM2008) minus reference DEM statistics, per job and DEM."""
    rows = repo.dem_comparisons(job_id=job_id, region=region)
    return [{**r, "job_id": str(r["job_id"])} for r in rows]


@app.get("/granules", tags=["jobs"], dependencies=[Auth])
def granules(repo: Repo, region: str | None = None, status: str | None = None,
             product: ProductName | None = None) -> list[dict]:
    rows = repo.list_granules(region, status, product)
    return [{**r, "job_id": str(r["job_id"]) if r["job_id"] else None} for r in rows]
