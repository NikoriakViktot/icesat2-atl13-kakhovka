# ICESat-2 ingest API — guide for AI agents

This service pulls ICESat-2 data for **any area on Earth**, processes it, and serves
the results. You describe *what* you want (product, area, dates, options); the
service handles NASA access, storage and processing.

- Machine-readable contract: [`openapi.json`](openapi.json) (live: `GET /openapi.json`, UI `/docs`).
- Ready-made tool definitions: [`agent-tools.json`](agent-tools.json) (JSON Schema + HTTP mapping).
- Task recipes with sanity checks: [`agent-playbooks.md`](agent-playbooks.md).
- Column meanings in depth: [`data-model.md`](data-model.md), [`heights-and-dems.md`](heights-and-dems.md).

- **Products:** `ATL13` inland water surface, `ATL08` terrain + canopy, `ATL03` photons.
- **Digital elevation models:** compare ICESat-2 against Copernicus GLO-30 (`cop30`)
  and FABDEM (`fabdem`), and grid ICESat-2 into rasters (DTM, canopy height, water
  surface) delivered as Cloud-Optimised GeoTIFFs.
- **Everything is asynchronous:** create a job, poll it, then read the results.

## 1. Connection

| | |
|---|---|
| Base URL (local stack) | `http://localhost:58000` |
| Auth | header `X-API-Key: <key>` on every call except `GET /health` |
| Format | JSON in, JSON / GeoJSON / CSV / GeoTIFF out |
| Units | metres, degrees (EPSG:4326 lon/lat), UTC timestamps, ISO dates |

Never send NASA Earthdata or S3 credentials in a request. The service has its own.

## 2. The workflow

```
GET  /products                      what can be ingested (once per session)
POST /regions                       register an area (or pass it inline in the job)
POST /jobs                          -> 202 {job_id, status: "queued"}
GET  /jobs/{job_id}                 poll until status is "done" or "failed"
GET  /regions/{slug}/pass-levels    ATL13 water levels   (GeoJSON | CSV)
GET  /regions/{slug}/points         ATL13 / ATL08 points (CSV | JSON)
GET  /dem-comparisons?job_id=...    ICESat-2 minus reference DEM statistics
GET  /rasters?job_id=...            raster metadata; /rasters/{id}/download = the COG
```

### Polling policy

- Poll `GET /jobs/{job_id}` every **5–10 s** for the first minute, then every
  **30 s**. Typical runtimes on the reference stack: ATL13 5 granules about 25 s;
  ATL08 6 granules about 90 s; ATL03 3 granules about 20 s; ATL13 5 granules over
  a large lake about 3 min.
- `stage` moves `discover → acquire → process → load`; `stats` fills in as it goes.
- Stop at `status = "done"` or `"failed"`. On `failed`, read `error` (exception
  plus a short traceback) and `stage` before retrying. Do not retry blindly.

### Idempotency: safe to repeat

- A granule that is already `loaded` (or `empty`) for the same region and product
  is **skipped**. Re-submitting the same job only fetches what is new
  (`stats.already_loaded` counts the skipped ones).
- Every database write is an upsert, so re-running a job never duplicates rows.
- To pull more of a large window gradually, repeat the same request with `limit`:
  each run takes the next `limit` granules that are not loaded yet.

## 3. Regions

A region is an area of interest with a unique `slug` (`[a-z0-9_]{2,64}`).

```json
POST /regions
{
  "slug": "lake_victoria_sw",
  "name": "Lake Victoria (SW part)",
  "bbox": [32.5, -1.5, 33.5, -0.5],
  "coord": {"lon": 33.0, "lat": -1.0},
  "kind": "lake",
  "vertical": "egm2008"
}
```

| field | required | meaning |
|---|---|---|
| `bbox` or `polygon` | one of | clip area. `bbox` = `[lon_min, lat_min, lon_max, lat_max]`; `polygon` = a GeoJSON geometry |
| `coord` | **ATL13 only** | a point **on the water**; SlideRule resolves the ATL13 water body from it |
| `refid` | no | ATL13 reference water-body id, if known |
| `kind` | no (`lake`) | ATL13 QC: `lake` / `reservoir` (still water: full per-pass QC) or `river` (basic statistics) |
| `vertical` | no (`egm2008`) | height system of `H_m` / `wse_m`: `egm2008` (global) or `egg2015` (**Europe only**, EVRS normal heights) |

- Configured regions already exist: `kakhovka` (reservoir, EGG2015), `kherson` and
  `dnipro_estuary` (rivers below the dam). They also carry the Kakhovka dam-breach
  periods. `GET /regions` lists everything with row counts.
- You can skip `POST /regions` and pass the same object as `region` inside
  `POST /jobs`. It is then registered automatically.
- Re-posting a slug **updates** it; a configured slug returns `409`.

## 4. Jobs

```json
POST /jobs
{
  "product": "ATL08",
  "region_slug": "nova_kakhovka_land",
  "start": "2021-05-01",
  "end": "2021-07-31",
  "compare": ["cop30", "fabdem"],
  "dem": {"resolution_m": 100, "variables": ["dtm", "chm"]},
  "limit": 10
}
```

| field | default | notes |
|---|---|---|
| `product` | `ATL13` | `ATL13` \| `ATL08` \| `ATL03` |
| `region_slug` / `region` | — | exactly one |
| `start`, `end` | full mission | inclusive dates; **always set them**, since an unbounded window can mean hundreds of granules |
| `include_cmr` | auto | NASA CMR granule search. Auto: on, except for configured ATL13 regions that have a curated granule list |
| `limit` | none | max granules this job; use it for first looks and big areas |
| `batch_size` | per product | granules per SlideRule request (ATL13 50, ATL08 10, ATL03 3) |
| `compare` | `[]` | reference DEMs: `cop30`, `fabdem` |
| `dem` | none | grid points to COG: `resolution_m` (10–10000), `variables` (see below) |
| `atl03` | none | ATL03 only: `cnf` (0–4, min signal confidence, default 4), `atl08_class` (e.g. `["atl08_ground"]`) |

Raster `variables` per product: ATL13 `wse`; ATL08 `dtm`, `chm`; ATL03 `dtm`.

### Choosing a request

| goal | product | key options |
|---|---|---|
| water level time series of a lake / reservoir / river | ATL13 | region `coord` on the water, `kind` |
| bare-earth terrain heights, terrain DEM validation | ATL08 | `compare: ["fabdem","cop30"]` (FABDEM is the bare-earth DEM) |
| canopy / forest height | ATL08 | `dem.variables: ["chm"]` |
| full-resolution ground surface (dense) | ATL03 | `atl03.atl08_class: ["atl08_ground"]`, `dem.resolution_m` 30 |
| check a lake level against the DEMs' water surface | ATL13 | `compare: ["cop30"]` |

### Size and cost guidance

- ATL03 is heavy: tens of thousands of photons per granule per few km². Keep areas
  small (≲ 20 × 20 km), `limit` ≤ 5, and always filter (`cnf: 4`, `atl08_class`).
  ATL03 photons are **not stored in PostGIS**, only in S3 parquet and in rasters
  and statistics.
- ICESat-2 tracks are ~3 km apart (beam pairs) and repeat every 91 days. Rasters
  are **gappy by design**: only cells with points have values (band 2 = point
  count). Coarser `resolution_m` gives more cells with data; nothing is interpolated.
- A raster above 50 million cells is refused. Lower the resolution or shrink the area.

## 5. Reading results

### Job `stats` (from `GET /jobs/{id}`)

```json
{
  "product": "ATL08", "candidates": 6, "already_loaded": 0, "to_fetch": 6,
  "raw_rows": 1247, "points": 1247,
  "dem_comparison": {
    "cop30":  {"n": 1238, "median_m": -0.44, "nmad_m": 0.84, "rmse_m": 2.58, "...": "..."},
    "fabdem": {"n": 1238, "median_m": -0.29, "nmad_m": 0.58, "rmse_m": 1.38}
  },
  "rasters": [{"variable": "dtm", "resolution_m": 100, "valid_cells": 594, "median": 16.85,
               "uri": "s3://.../dtm_100m.tif"}]
}
```

ATL13 jobs add `water_segments`, `pass_levels` and `pass_levels_qc`.

### Heights: which column is which

| column | frame | meaning |
|---|---|---|
| `h_wgs84_m` (ATL13), `h_te_median_m` (ATL08), `height_m` (ATL03) | WGS84 ellipsoid | the product's native height |
| `n_m` / `N_m` | — | geoid (EGM2008) or quasigeoid (EGG2015) height used |
| `wse_m` (ATL13), `h_m` (ATL08), `H_m` | **the region's `vertical`** | orthometric / normal height = ellipsoidal − N |
| `h_egm2008_m` / `H_egm2008_m` | EGM2008 | always present; the frame of every DEM comparison |
| `vertical_datum` | — | `EGM2008` or `EVRS_EGG2015` (EVRF2007-consistent normal height) |
| `cop30_m`, `fabdem_m` | EGM2008 | reference DEM at the point |
| `period` | — | `ALL`, or Kakhovka regions only: `PRE_BREACH` / `BREACH_DRAWDOWN` / `POST_BREACH` |

### DEM comparison statistics

`dh = H_egm2008 (ICESat-2) − DEM`, over valid points (ATL13: on-water segments only).
`median_m` is the bias and `nmad_m` (1.4826 × median absolute deviation) is the
robust spread. Trust these over `mean_m` / `rmse_m`, which outliers inflate.
Reference values measured on this stack:

| site | product | COP30 median / NMAD | FABDEM median / NMAD |
|---|---|---|---|
| farmland S of Nova Kakhovka | ATL08 terrain | −0.44 / 0.84 m | −0.29 / 0.58 m |
| same, ground photons | ATL03 | — | 0.00 / 1.05 m |
| Lake Victoria, 2023 | ATL13 water | +2.52 / 0.11 m | +2.52 / 0.11 m |

Over water, the DEMs hold one flattened lake level from their 2011–2015 acquisition
epoch, so a non-zero ATL13 bias there can be a **real water-level change**, not an
error.

### ATL13 pass levels

One row per `(date, rgt, beam)`: `median_wse_m` (the level), `nmad_m`, `n_points`,
`track_length_km`, `along_track_slope_m_per_km`, `qc_pass`, `qc_flags`
(`|`-separated reasons), `vertical_datum`. For a water-level time series, use
`qc_pass=true` and the median per date across beams. The GeoJSON geometry is the
pass's track line through its water segments.

### Rasters

`GET /rasters?job_id=…` → `raster_id`, `variable`, `resolution_m`, `crs` (UTM zone
of the area), `vertical_datum` (`null` for `chm`, which is a height above terrain),
`stats`, `footprint` (GeoJSON). `GET /rasters/{raster_id}/download` streams the
COG: **band 1 = value** (median of points in the cell, NaN = no data),
**band 2 = number of ICESat-2 points** in the cell.

## 6. Errors

| code | meaning | what to do |
|---|---|---|
| 401 | missing or wrong `X-API-Key` | fix the header; don't retry otherwise |
| 404 | unknown region / job / raster | `POST /regions` first, or check the id |
| 409 | slug is a configured region | use `region_slug` instead of `region` |
| 422 | invalid request (body explains: missing `coord` for ATL13, bad `bbox`, unknown raster variable, `atl03` options on another product, …) | fix the body |
| job `failed` | `error` names the exception and stage | `acquire`: SlideRule/network, retry later; `process` + "EGG2015": the area is outside Europe, use `vertical: "egm2008"`; anything else: report it |

A job with `to_fetch: 0` is **not an error**: no new granules in that window
(already loaded, or none exist). Widen the dates or check `GET /granules`.

## 7. Licences and attribution

- ICESat-2 (NASA NSIDC DAAC), accessed through SlideRule (University of Washington / NASA).
- Copernicus GLO-30 DEM © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH
  2014–2018, provided under COPERNICUS by the European Union and ESA.
- FABDEM V1-2, University of Bristol / Fathom: **CC BY-NC-SA 4.0, non-commercial
  use only.** Do not use `fabdem` results commercially.
- EGG2015 (IAG / International Service for the Geoid): the 1′ grid used here has an
  open provenance question (see README); fine for analysis, cite with care.

## 8. Complete example (curl)

```bash
K="X-API-Key: $API_KEY"; B=http://localhost:58000
# 1) water levels of a lake you have never used before
curl -s -X POST $B/jobs -H "$K" -H 'Content-Type: application/json' -d '{
  "product": "ATL13",
  "region": {"slug": "lake_victoria_sw", "coord": {"lon": 33.0, "lat": -1.0},
             "bbox": [32.5, -1.5, 33.5, -0.5], "kind": "lake"},
  "start": "2023-01-01", "end": "2023-02-28"}'
# -> {"job_id": "8e4c...", "status": "queued", ...}
curl -s $B/jobs/8e4c... -H "$K"            # repeat until status == "done"
curl -s "$B/regions/lake_victoria_sw/pass-levels?format=csv&qc_pass=true" -H "$K"

# 2) terrain + canopy rasters and DEM validation on land
curl -s -X POST $B/jobs -H "$K" -H 'Content-Type: application/json' -d '{
  "product": "ATL08",
  "region": {"slug": "nova_kakhovka_land", "bbox": [33.30, 46.70, 33.45, 46.80]},
  "start": "2021-05-01", "end": "2021-07-31",
  "compare": ["cop30", "fabdem"], "dem": {"resolution_m": 100}}'
curl -s "$B/rasters?region=nova_kakhovka_land" -H "$K"
curl -s -o dtm.tif "$B/rasters/<raster_id>/download" -H "$K"
```
