# Data model

All heights are in **metres**; coordinates are **EPSG:4326** lon/lat; timestamps are
**UTC** (`timestamptz`). Geometry columns are PostGIS `geometry(…, 4326)`.
Schema: `migrations/versions/0001_icesat2_schema.py` + `0002_multi_product.py`.

## Height columns: read this first

| name pattern | frame |
|---|---|
| `h_wgs84_m`, `h_te_median_m`, `height_m` | WGS84 **ellipsoid** (the product's native height) |
| `n_m` | geoid (EGM2008) or quasigeoid (EGG2015) height that was subtracted |
| `wse_m`, `h_m`, `median_wse_m`, `mean_wse_m` | **the row's `vertical_datum`** |
| `h_egm2008_m` | EGM2008, always present; the frame of DEM comparisons |
| `h_evrs_egg2015_m`, `zeta_egg2015_m`, `egm2008_minus_evrs_m` | EGG2015 chain of the research pipeline (ATL13, `egg2015` regions only) |
| `cop30_m`, `fabdem_m` | reference DEM at the point, EGM2008 |

`vertical_datum` ∈ {`EGM2008`, `EVRS_EGG2015`}. `EVRS_EGG2015` is an
EVRF2007-consistent normal height (h − ζ_EGG2015), *not* EVRF2019.

`period` ∈ {`ALL`} for every region except the configured Kakhovka family, which
uses `PRE_BREACH` (≤ 2023-06-05), `BREACH_DRAWDOWN` (2023-06-06 … 2023-12-31) and
`POST_BREACH` (≥ 2024-01-01).

## PostGIS: schema `icesat2`

### `jobs`: one row per ingest request
| column | type | |
|---|---|---|
| `job_id` | uuid PK | |
| `region` | text | region slug |
| `product` | text | `ATL13` \| `ATL08` \| `ATL03` |
| `params` | jsonb | the validated request body (`region_slug` always filled in) |
| `status` | text | `queued` → `running` → `done` \| `failed` |
| `stage` | text | `discover` \| `acquire` \| `process` \| `load` |
| `stats` | jsonb | counts, `dem_comparison`, `rasters` (see agents-api.md §5) |
| `error` | text | exception + short traceback when failed |
| `created_at`, `started_at`, `finished_at` | timestamptz | |
| `client` | text | name of the API key that created it (`API_KEYS` `name:key`) |
| `requested_by` | text | end user a BFF acted for (`X-Requested-By`) |

### `regions`: regions registered through the API
`slug` PK, `definition` jsonb (the `RegionIn` body + `regimes=false`), `footprint`
geometry (the clip), `client`, `requested_by` (owner; only the owner may update the
slug), `created_at`, `updated_at`. Configured regions (`kakhovka`,
`kherson`, `dnipro_estuary`) come from `config/kakhovka.yaml` and are not stored here.

### `granules`: per-granule bookkeeping
PK `(region, product, granule)`. `rgt`, `cycle`, `acq_time`, `version`
(`<release>_<version>`), `status` (`pending` → `fetched` → `loaded`, or `empty`,
meaning SlideRule returned nothing inside the area), `n_rows`, `s3_raw_uri`, `job_id`,
`updated_at`. `loaded` and `empty` granules are skipped by later jobs.

### `atl13_segments`: ATL13 inland-water segments
PK `(region, beam, time)`; partitioned by year (`atl13_segments_2018` … `_2035`,
`_default`).

| column | |
|---|---|
| `granule`, `rgt`, `cycle`, `beam`, `segment_id` | ICESat-2 identifiers (`beam` = `gt1l` … `gt3r`) |
| `lat`, `lon`, `geom` | position (Point) |
| `h_wgs84_m` | ATL13 `ht_water_surf` |
| `h_egm2008_m` | ATL13 `ht_ortho` |
| `stdev_water_surf_m`, `water_depth_m` | ATL13 fields (FLT_MAX → NULL) |
| `n_m`, `wse_m`, `vertical_datum` | water-surface elevation in the region's datum |
| `zeta_egg2015_m`, `h_evrs_egg2015_m`, `egm2008_minus_evrs_m` | EGG2015 regions only |
| `cop30_m`, `fabdem_m` | when the job asked for `compare` |
| `water_mask_pass` | segment inside the region clip |
| `period`, `job_id` | |

### `atl13_pass_levels`: one water level per `(date, rgt, beam)`
PK `(region, date, rgt, beam)`. `datetime` (first segment), `year`, `transect`
(`<rgt>_<beam>`), `period`, `n_points`, `median_wse_m` (**the level**),
`mean_wse_m`, `std_m`, `mad_m`, `nmad_m`, `p05_m`, `p95_m`, `range_m`,
`along_track_slope_m_per_km`, `track_length_km`, `mean_stdev_water_surf_m`,
`lat_mean`, `lon_mean`, `qc_pass`, `qc_flags` (`|`-joined reasons), `vertical_datum`,
`job_id`, `geom` (LineString through the pass's water segments).
QC (`kind` lake/reservoir only, thresholds in `config/kakhovka.yaml::qc`): ≥ 20
points, MAD ≤ 0.25 m, p95 − p05 ≤ 1 m, track ≥ 2 km, mean stdev ≤ 0.5 m,
|slope| ≤ 0.05 m/km. River regions get statistics without QC (`qc_pass` NULL).

### `atl08_segments`: ATL08 100 m land/vegetation segments
PK `(region, beam, time)`; partitioned by year.

| column | |
|---|---|
| `h_te_median_m` | terrain height, ellipsoidal (ATL08 `h_te_median`) |
| `h_te_uncertainty_m`, `terrain_slope` | |
| `h_canopy_m`, `h_mean_canopy_m`, `h_max_canopy_m`, `h_canopy_uncertainty_m` | canopy height **above terrain** |
| `canopy_openness`, `n_te_photons`, `n_ca_photons` | |
| `segment_landcover`, `segment_snowcover`, `solar_elevation` | ATL08 flags |
| `n_m`, `h_m`, `h_egm2008_m`, `vertical_datum` | terrain in the region's datum and in EGM2008 |
| `cop30_m`, `fabdem_m` | when requested |
| `granule`, `rgt`, `cycle`, `beam`, `segment_id`, `lat`, `lon`, `geom`, `period`, `job_id` | |

### `rasters`: ICESat-2 gridded products
`raster_id` uuid PK, `job_id`, `region`, `product`, `variable` (`dtm` \| `chm` \|
`wse`), `description`, `resolution_m`, `crs` (UTM zone, e.g. `EPSG:32636`),
`vertical_datum` (NULL for `chm`), `s3_uri`, `stats` jsonb (`rows`, `cols`,
`valid_cells`, `points`, `min`, `max`, `median`), `footprint` (Polygon), `created_at`.
Re-running a job replaces its raster rows for the same variable and resolution.

### `dem_comparisons`: ICESat-2 minus reference DEM
PK `(job_id, dem)`. `region`, `product`, `dem` (`cop30` \| `fabdem`), `height`
(the ICESat-2 column, `H_egm2008_m`), `n`, `median_m`, `nmad_m`, `mean_m`, `std_m`,
`rmse_m`, `p05_m`, `p95_m`, `created_at`. `dh = H_egm2008 − DEM`.

## S3 layout

Root `s3://$S3_BUCKET/$S3_PREFIX` (default `s3://icesat2/icesat2`).

```
reference/egg_2015.tif                                   EGG2015 grid (EGG2015_URI)
reference/cop30/<Copernicus_DSM_COG_10_..._DEM>.tif      COP30 tile cache
reference/fabdem/<N46E033_FABDEM_V1-2>.tif               FABDEM tile cache
<product>/v007/<region>/manifest/run=<job>.csv           granules this job fetched
<product>/v007/<region>/raw/run=<job>/batch_NNN.parquet  verbatim SlideRule return
<product>/v007/<region>/processed/points/run=<job>.parquet
<product>/v007/<region>/processed/pass_levels/run=<job>.parquet   (ATL13)
<product>/v007/<region>/dem/run=<job>/<variable>_<res>m.tif       (COG)
```

`<product>` is lower case. Raw parquet keeps SlideRule's own column names (e.g.
`ht_water_surf`, `h_te_median`, `height`) plus `time` and `geometry_wkt`. Processed
`points` parquet has the normalised columns of the tables above (frame names:
`H_m`, `N_m`, `H_egm2008_m`, …), and for ATL03 additionally `atl03_cnf`,
`atl08_class`, `quality_ph`, `ph_index`, `x_atc`, `y_atc`, `background_rate`.

### Raster files
Two-band Cloud-Optimised GeoTIFF, float32, DEFLATE, 256-px tiles, projected UTM:
- band 1 `value`: median of the points in the cell; NaN where no point fell;
- band 2 `n_points`: number of ICESat-2 points in the cell.
