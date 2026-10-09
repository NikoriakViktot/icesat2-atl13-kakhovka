# Architecture

A request describes *what* to ingest (product, area, dates, options). A worker does
the slow part (NASA → S3 → processing → PostGIS) asynchronously; the API reads the
results back.

```
 client / AI agent
        │  HTTP + X-API-Key
        ▼
 ┌─────────────┐  enqueue job_id   ┌─────────┐   ┌──────────────────────────────────────────┐
 │ api         │ ────────────────▶ │ redis   │──▶│ worker (RQ)                              │
 │ FastAPI     │                   │ queue   │   │ 1 discover  CMR / curated granule list   │──▶ SlideRule CMR proxy
 │ :8000       │ ◀── job status ── └─────────┘   │ 2 acquire   SlideRule atl13x/atl08x/atl03x│──▶ SlideRule (NASA data)
 └─────┬───────┘                                 │ 3 process   heights, clip, QC, DEMs, grids│──▶ COP30 (AWS) / FABDEM (Bristol)
       │ reads                                   │ 4 load      upserts into PostGIS          │
       ▼                                         └───────┬───────────────────────┬──────────┘
 ┌─────────────┐ ◀───────────────────────────────────────┘                       │
 │ db PostGIS  │   icesat2.* tables                                         ┌────▼─────┐
 └─────────────┘                                                            │ s3       │ raw + processed parquet,
                                                                            │          │ COG rasters, tile caches
                                                                            └──────────┘
```

## Components

| service | image | role | host port (dev) |
|---|---|---|---|
| `api` | `Dockerfile` | FastAPI: validation, region registry, job creation, result reads | 58000 |
| `worker` | `Dockerfile` | `rq worker icesat2`: runs `service.worker.run_job` | — |
| `db` | `postgis/postgis:16-3.4` | all structured results | 55433 |
| `s3` | `chrislusf/seaweedfs:3.80` (dev) / AWS S3 (prod) | files: parquet, COGs, reference tiles | 58333 |
| `redis` | `redis:7-alpine` | job queue | 56379 |
| `migrate` | `Dockerfile` | `alembic upgrade head` (profile `tools`) | — |

The API and the worker are the same image; only the command differs.

## Job lifecycle

`POST /jobs` validates the body, registers an inline region, writes a row to
`icesat2.jobs` (`status=queued`) and enqueues the id. The worker then:

1. **discover**: candidate granules = the region's curated ATL13 seed list
   and/or a CMR search over the region's bbox (product short name + version 007),
   filtered to `[start, end]`. Granules already `loaded` / `empty` for this
   (region, product) are dropped; `limit` cuts the rest. The list goes to
   `manifest/run=<job>.csv`, and the granules are marked `pending`.
2. **acquire**: batches of `batch_size` granules → one SlideRule request each
   (`products.request_parms`): ATL13 picks the water body by `coord` (+`refid`);
   ATL08 / ATL03 send the region polygon (`poly`). Each batch is written to
   `raw/run=<job>/batch_NNN.parquet` immediately. Granules in a batch with no rows
   become `empty`, the rest `fetched`. Network errors are retried with
   exponential backoff (`FETCH_RETRIES`).
3. **process**: raw parquet → normalised frame (`products.normalise`) → granule
   attribution by `(rgt, cycle)` → `pipeline.to_heights` (clip, geoid, `H_m`,
   `H_egm2008_m`, `period`) → optional reference DEMs (`compare`) → ATL13 pass
   levels → optional rasters (`dem`). Written to `processed/…` and `dem/…`.
4. **load**: upserts into PostGIS (points unless ATL03, pass levels, DEM
   statistics, raster registry), granules → `loaded`, job → `done`.

Any exception marks the job `failed` with the stage and a short traceback in
`error`. Re-running a job (or the same request as a new job) is safe: discovery
skips finished granules, and every write is an upsert.

## Code map

| module | responsibility |
|---|---|
| `products.py` | product registry; SlideRule request parameters; normalisers |
| `regions.py` | `Region` (clip, coord/refid, kind, vertical, regimes); configured regions from `config/kakhovka.yaml` |
| `discovery.py` | granule-name parsing (any `ATLxx`), CMR search |
| `pipeline.py` | pure steps shared by scripts and the worker |
| `heights.py` | ellipsoidal → orthometric/normal heights (EGG2015, EGM2008) |
| `dem.py` | reference-DEM tiles (COP30, FABDEM), comparison statistics, gridding, COG writing |
| `aggregate.py`, `qc.py` | ATL13 per-pass aggregation and QC (shared with the research pipeline) |
| `service/api.py` | routes and request/response schemas |
| `service/worker.py` | `run_job`, the CLI `python -m kakhovka_altimetry.service.worker` |
| `service/repository.py` | SQL: jobs, regions, granules, upserts, reads |
| `service/storage.py` | S3 layout and fsspec helpers |
| `service/settings.py` | configuration from environment variables |

## Design decisions

- **SlideRule instead of raw HDF5.** SlideRule subsets server-side (water body /
  polygon), so tens of MB move instead of hundreds of 100+ MB granules. The raw
  SlideRule return is kept verbatim in S3, so processing can be redone offline.
- **Immutable raw layer per job** (`raw/run=<job_id>/`). Reprocessing never needs NASA.
- **Upserts with natural keys** (`(region, beam, time)` for points) instead of
  surrogate ids, so retries and re-runs converge to the same rows.
- **Datum-neutral column names + `vertical_datum`.** A water level in EGM2008 and
  one in EVRS never hide behind the same unlabeled column.
- **Reference DEMs read from their own tiles**, not from SlideRule raster
  sampling, whose vertical frame proved inconsistent (see
  [heights-and-dems.md](heights-and-dems.md)).
- **ATL03 photons only in S3.** They run to tens of thousands per granule per few km²;
  PostGIS gets their statistics and rasters.
- **Rasters without interpolation.** ICESat-2 tracks are km apart; a cell has a
  value only if points fell in it, and band 2 says how many.
