# AGENTS.md — working on this repository

Instructions for AI coding agents (Claude Code, Codex, Cursor, …) and humans
changing the code. Repository: `github.com/NikoriakViktot/icesat2-ingest` (renamed
from `icesat2-atl13-kakhovka`; the Python package keeps the name
`kakhovka_altimetry` so scripts and notebooks keep working). To **call** the running
service, read [`docs/agents-api.md`](docs/agents-api.md) and
[`docs/agent-playbooks.md`](docs/agent-playbooks.md) instead. Full docs index:
[`docs/README.md`](docs/README.md).

## What this repo is

Two layers that share one library (`src/kakhovka_altimetry/`):

1. **Kakhovka research pipeline** (`scripts/`, `notebooks/`, `outputs/`): ICESat-2
   ATL13 → EGG2015 → EVRS water levels of the Kakhovka reservoir, gauge
   alignment, datum work. Batch scripts, local parquet. See `README.md`.
2. **ICESat-2 ingest service** (`src/kakhovka_altimetry/service/`): FastAPI + RQ
   worker. Any region, products ATL13 / ATL08 / ATL03, reference DEMs (Copernicus
   GLO-30, FABDEM), gridded COG rasters. Raw and processed data in S3, results in
   PostGIS.

## Layout

```
src/kakhovka_altimetry/
  products.py      product registry: SlideRule API, request parms, normalisers
  regions.py       Region (clip, coord/refid, kind, vertical, regimes) + config/registry
  pipeline.py      pure steps: candidate_granules, fetch_batch, segments_from_raw,
                   to_heights, pass_levels (ATL13), dem_mask
  heights.py       ellipsoid -> orthometric: EGG2015 (Europe) or EGM2008 (PROJ grid)
  dem.py           Cop30Source / FabdemSource tiles, compare(), grid_points(), write_cog()
  discovery.py     granule names (any ATLxx), CMR search (SlideRule proxy, earthaccess fallback)
  atl13.py, vertical.py, aggregate.py, qc.py ...   the research pipeline's core
  service/
    api.py         FastAPI app (routes + pydantic schemas)
    worker.py      run_job(): discover -> acquire -> process -> load; CLI entry point
    repository.py  psycopg: COPY -> staging -> INSERT .. ON CONFLICT upserts
    storage.py     S3 layout (Layout) and fsspec helpers
    settings.py    env-driven Settings
migrations/        Alembic (0001 base schema, 0002 multi-product)
tests/             pytest; test_service_integration.py needs docker
docs/              architecture, data-model, heights-and-dems, deployment, operations,
                   agents-api, agent-playbooks; openapi.json + agent-tools.json (generated)
scripts/export_agent_docs.py   regenerates docs/openapi.json + docs/agent-tools.json
scripts/deploy_server.sh       SSH deploy / update of the prod stack (or `local`)
docker-compose.prod.yml        prod overrides: 127.0.0.1 ports, restarts, 2 workers
```

## Commands

```bash
uv venv .venv-service --python 3.12
uv pip install --python .venv-service/bin/python -r requirements-service.txt
uv pip install --python .venv-service/bin/python --no-deps -e .

.venv-service/bin/ruff check src tests migrations           # line length 100
.venv-service/bin/python -m pytest -q -p no:logging          # ~100 tests, ~20 s
.venv-service/bin/python -m pytest -q tests/test_pipeline_steps.py   # no docker

cp .env.example .env
docker compose --profile tools build                         # ALL images, incl. migrate
docker compose up -d                                         # db, s3, redis, api, worker
docker compose run --rm migrate                              # alembic upgrade head
# API http://localhost:58000/docs ; Postgres :55433 ; S3 :58333 ; Redis :56379

# regenerate docs/openapi.json + docs/agent-tools.json after changing api.py
# (tests/test_docs_in_sync.py fails while they are stale)
.venv-service/bin/python scripts/export_agent_docs.py

# deploy to a server (docs/deployment.md)
scripts/deploy_server.sh user@host [--egg /path/egg_2015.tif]
```

The legacy `.venv` in the repo was copied from another machine and does not run.
Use `.venv-service`.

## Invariants: do not break these

- **Vertical naming discipline.** `H_evrs_egg2015_m = h − ζ_EGG2015` is an
  EVRF2007-consistent normal height, *not* EVRF2019. ATL13 `ht_ortho`
  (`H_egm2008_m`) is a control only and is **never** fed into the EGG2015 branch.
  Service tables use datum-neutral names (`wse_m`, `h_m`, `median_wse_m`) **plus** a
  `vertical_datum` column. Never drop that column.
- **EGG2015 is Europe-only.** `heights.add_heights` raises when every point falls
  outside the grid; do not "fix" that by falling back silently.
- **Dam-breach periods** (`PRE_BREACH` / `BREACH_DRAWDOWN` / `POST_BREACH`) apply
  only to regions with `regimes=True` (the configured Kakhovka-family regions).
  Everything else gets `period = "ALL"`. Never mix pre- and post-breach in
  reservoir statistics.
- **DEM comparisons happen in EGM2008:** `dh = H_egm2008_m − <dem>_m`. Copernicus
  and FABDEM are native EGM2008. Do **not** use SlideRule's `samples` /
  `esa-copernicus-30meter` for COP30: its values came back ellipsoidal at Kakhovka
  but orthometric on Lake Victoria. `dem.Cop30Source` reads the AWS Open Data tiles
  directly.
- **The research pipeline's numbers must not move.** The service reproduces
  `outputs/tables/atl13_pass_levels.csv` (46 passes, |Δ| ≤ 2 µm). Keep
  `aggregate.pass_level_table` defaults (`height_col="H_evrs_egg2015_m"`) and the
  batch scripts' behaviour unchanged.
- **Idempotency.** Points key on `(region, beam, time)` (verified unique in every
  region; `granule` is NULL for the downstream bodies, so it cannot be in the key),
  pass levels on `(region, date, rgt, beam)`, granules on `(region, product, granule)`.
  Loads must stay upserts.
- **Credentials only from the environment.** Never accept Earthdata or S3 secrets
  in API bodies.
- **Keys and ownership.** `API_KEYS` entries are `key | name:key | name:key:ro`;
  writes need a read/write key (403 otherwise). Jobs and regions record `client`
  and `X-Requested-By`; a region can be updated only by its owner (409).
  Authorisation of end users is the BFF's job (Django), not this API's.
- **FABDEM is CC BY-NC-SA 4.0** (non-commercial). Keep the attribution in docs and
  the README.

## Gotchas already paid for

- **MinIO images are no longer publicly pullable** (Docker Hub removed, quay needs
  auth). The local S3 is SeaweedFS (`docker/seaweedfs-s3.json` holds dev creds).
- **Corrupted S3 objects with non-AWS S3:** botocore ≥ 1.36 streams uploads with
  aws-chunked checksums that SeaweedFS/MinIO store verbatim. Keep
  `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` and
  `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required` in the env. moto does **not**
  reproduce this, so only the live stack catches it.
- `python:3.12-slim` lacks `libexpat1`, which rasterio's wheel needs. It is in the
  Dockerfile.
- `docker compose build` skips the `migrate` service (it is in the `tools`
  profile). Use `docker compose --profile tools build`, or migrations run old code.
- EGM2008 for ATL08/ATL03 needs `PROJ_NETWORK=ON` (set in compose); the grid is
  cached under `PROJ_USER_WRITABLE_DIRECTORY`. Unit tests monkeypatch
  `heights.egm2008_undulation`, so they never hit the network.
- SlideRule `atl13x` works with `coord` alone (same rows as `refid` + `coord`).
  SlideRule's CMR proxy (`sliderule.earthdata.cmr`) needs no Earthdata login.
- Host port 8000 is taken on the dev machine, so the API is on **58000**.

## Adding a product (e.g. ATL06)

1. `products.py`: add a `Product` (SlideRule API name, `height_col`,
   `dem_variables`, `default_batch`, `points_in_db`), a branch in `request_parms`
   and a normaliser built on `_normalise_x`.
2. If its points go to PostGIS: a migration with a partitioned
   `icesat2.<product>_segments` table, keyed on `(region, beam, time)`, plus a
   column mapping in `repository.POINT_TABLES`.
3. Extend `ProductName` in `api.py` (and the enums in
   `scripts/export_agent_docs.py`); run `scripts/export_agent_docs.py`; document the
   product in `docs/agents-api.md`, `docs/data-model.md` and `docs/agent-playbooks.md`.
4. Tests: a `fake_<product>()` frame in `tests/test_pipeline_steps.py` and a job in
   `tests/test_service_integration.py`; then a small live job against the stack.

## Before you finish

- `ruff check` clean and the full `pytest` green, including the docker integration test.
- Schema change: a new Alembic revision (never edit an applied one), applied to the
  live stack with `--profile tools build` + `run --rm migrate`.
- API change: `scripts/export_agent_docs.py`, then update `docs/agents-api.md` and,
  if the workflow changed, `docs/agent-playbooks.md`.
- Anything touching heights or DEMs: run one small live job and sanity-check
  `dem_comparison` (bias of a few dm, not tens of metres).
