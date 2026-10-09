# Operations

`C` below is the compose command. Dev: `docker compose`. Server:
`docker compose -f docker-compose.yml -f docker-compose.prod.yml`.

## Everyday

```bash
$C ps                                   # all five services Up; db (healthy)
$C logs -f worker                       # job progress: "job <id> batch N: G granules -> R rows"
curl -s localhost:58000/health
curl -s localhost:58000/jobs?limit=10 -H "X-API-Key: $KEY" | jq '.[] | {job_id,product,region,status,stage}'
```

Run a job without the API (same code path, synchronous):

```bash
$C exec worker python -m kakhovka_altimetry.service.worker \
   --region kakhovka --product ATL13 --start 2019-04-01 --end 2019-05-31 --limit 5
$C exec worker python -m kakhovka_altimetry.service.worker \
   --region nova_kakhovka_land --product ATL08 --compare cop30 fabdem --dem-res 100
```

Scale workers (jobs run in parallel, one per worker):

```bash
$C up -d --scale worker=4
```

## SQL you will want

```sql
-- what is running / failed
SELECT job_id, product, region, status, stage, started_at, left(error, 120)
FROM icesat2.jobs ORDER BY created_at DESC LIMIT 20;

-- coverage per region and product
SELECT region, product, status, count(*) FROM icesat2.granules GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

-- a water-level time series (QC'd, median across beams per day)
SELECT date, percentile_cont(0.5) WITHIN GROUP (ORDER BY median_wse_m) AS wse_m,
       count(*) AS beams, min(vertical_datum) AS datum
FROM icesat2.atl13_pass_levels WHERE region = 'kakhovka' AND qc_pass
GROUP BY date ORDER BY date;

-- DEM validation summary
SELECT region, product, dem, n, round(median_m::numeric, 2) bias, round(nmad_m::numeric, 2) nmad
FROM icesat2.dem_comparisons ORDER BY created_at DESC;
```

QGIS: connect to PostGIS (`localhost:55433`, db/user `icesat2`; on a server through
an SSH tunnel). Layers: `atl13_pass_levels` (lines), `atl13_segments` /
`atl08_segments` (points), `rasters` (footprints). Rasters: download through the API
or read `s3_uri` with GDAL's `/vsis3/`.

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| every call 401 | `API_KEYS` empty or the key is not in it | set `API_KEYS` in `.env`, `$C up -d api` |
| job `failed` at `acquire` | SlideRule / network error after `FETCH_RETRIES` | check outbound HTTPS; resubmit later |
| job `failed` at `process`: "outside the EGG2015 grid" | `vertical=egg2015` outside Europe | re-register the region with `vertical: egm2008` |
| job `failed` at `process`: "Parquet magic bytes not found" | S3 objects stored with aws-chunked framing | keep `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` and `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required`; delete the bad `raw/run=<job>/`, resubmit |
| `ImportError: libexpat.so.1` | old image | rebuild: `$C --profile tools build` |
| `relation "icesat2.atl13_segments" does not exist` | migrations not applied, or `migrate` image stale | `$C --profile tools build && $C --profile tools run --rm migrate` |
| ATL08/ATL03 `H_m` NaN | PROJ could not fetch the EGM2008 grid | outbound access to `cdn.proj.org`; `PROJ_NETWORK=ON` |
| `to_fetch: 0` | window already loaded, or no granules | widen dates; `GET /granules?region=…` |
| a job stuck `running` after a restart | the worker was killed mid-job | resubmit (idempotent) |
| port already in use on `up` | another service on 58000 / 55433 / 58333 / 56379 | change the host port in compose |

## Backups

| what | how | needed? |
|---|---|---|
| Postgres | `$C exec -T db pg_dump -U icesat2 -Fc icesat2 > icesat2_$(date +%F).dump` | yes: jobs, regions, results |
| S3 raw layer | copy `s3://…/<product>/…/raw/` (or the `s3data` volume) | yes if you want reprocessing without NASA |
| S3 processed / dem / reference | rebuildable from raw + public sources | optional |
| `.env`, `docker/seaweedfs-s3.local.json` | copy securely | yes |

Restore: `$C exec -T db pg_restore -U icesat2 -d icesat2 --clean < icesat2_<date>.dump`.

## Data lifecycle

Each job writes its own `raw/run=<job_id>/`; nothing is deleted automatically. To
drop a region:

```sql
DELETE FROM icesat2.atl13_pass_levels WHERE region = 'x';
DELETE FROM icesat2.atl13_segments    WHERE region = 'x';
DELETE FROM icesat2.atl08_segments    WHERE region = 'x';
DELETE FROM icesat2.dem_comparisons   WHERE region = 'x';
DELETE FROM icesat2.rasters           WHERE region = 'x';
DELETE FROM icesat2.granules          WHERE region = 'x';
DELETE FROM icesat2.regions           WHERE slug   = 'x';
```

then remove `s3://…/*/v007/x/`. Jobs rows are kept as an audit trail.
