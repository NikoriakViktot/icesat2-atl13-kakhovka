# icesat2-atl13-kakhovka

Reproducible pipeline: **ICESat-2 ATL13 → EGG2015 → per-pass water-surface
elevation (EVRS)** for the Kakhovka reservoir.

**V1 (this repo) is ICESat-only.** It pulls ATL13 over the reservoir, reduces every
segment to EVRS via the EGG2015 quasigeoid, QCs and aggregates to one level per
beam-pass, and reports what ICESat-2 actually shows. Gauges are **Phase 2** (see
below) and are not a V1 dependency.

## The vertical branch (V1)

| quantity | column | source |
|---|---|---|
| ellipsoidal WSE | `h_wgs84_m` | ATL13 `ht_water_surf`, verbatim |
| EGG2015 quasigeoid | `zeta_egg2015_m` | sampled from the EGG2015 grid |
| **EVRS WSE** | `H_evrs_egg2015_m = h_wgs84_m − zeta_egg2015_m` | computed |
| EGM2008 WSE | `H_egm2008_m` | ATL13 `ht_ortho` — **independent control only** |
| chain sanity | `egm2008_minus_evrs_m` | must be small (dm) & spatially smooth |

`ht_ortho` (EGM2008) is stored only for the `egm2008_minus_evrs_m` check; it is
**never** fed back into the EGG2015 branch. Config: `config/vertical_datums.yaml`
(EGG2015 grid = `data/1_data/egg_2015.tif`; native `.isg` also supported).

### Reference frames — what each input is actually in

| input | frame | tide system |
|---|---|---|
| ATL13 v7 `ht_water_surf` | ellipsoidal, **ITRF2020** (v7 reprocessing; ≈7 mm height change at mid-latitudes) | — |
| EGG2015 ζ | GRS80 / ETRF2000, **EVRF2007-consistent** | zero-tide |
| EPSG:9902 grid | BS-77 → **EVRF2019** normal heights | zero-tide |

Both ends of the EVRS branch are zero-tide, so **no tide-system mixing occurs** —
worth stating explicitly rather than leaving implicit.

**Naming discipline:** `h − ζ_EGG2015` yields an **EVRF2007-consistent** normal
height, *not* an EVRF2019 one. EVRF2019 is reached only by adding the empirical
corrector `c(x, y)`. The column is named `H_evrs_egg2015_m` for exactly this reason.

**Open provenance blocker.** Our EGG2015 raster is **1′×1′** (7200×3600). The
release distributed publicly by the International Service for the Geoid is 10′×15′;
the full 1′ grid is not published through that channel, so the donor repo's upstream
source is unidentified and **cannot yet be cited**. This is a citation problem, not
a numerical one — the values behave correctly (`egm2008_minus_evrs_m` is
−0.145 ± 0.027 m and smooth). It must be closed before publication.

UCS-2000 (УСК-2000) is not used here, but a future route through Ukraine's national
quasigeoid model **УКГ2025** would need it: that branch runs
ITRF2020 → UCS-2000 → УКГ2025 → EVRF2019, and would make the geodetic part of our
corrector directly computable as `c_geodetic = ζ_EGG2015 − ζ_УКГ2025` (the
ellipsoidal height cancels). The residual `r_i = c_station − c_geodetic` would then
isolate the ATL13 bias + hydrology + matchup error for the first time. The grid is
not in hand — this is the prepared next step, not a current capability.

## Periods (split on the 2023-06-06 dam breach)

| period | span | meaning |
|---|---|---|
| `PRE_BREACH` | … 2023-06-05 | reservoir water level |
| `BREACH_DRAWDOWN` | 2023-06-06 … `post_breach_start` (2024-01-01) | transient draining |
| `POST_BREACH` | after `post_breach_start` | residual ponds / Dnipro channel |

Reservoir-level statistics never mix `PRE_BREACH` with the post-breach periods.

## Run V1

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/download_atl13.py        # SlideRule atl13x pull (batched)
python scripts/build_evrs.py            # + EGG2015 → EVRS, water mask, period
python scripts/build_pass_levels.py     # aggregate to one level per beam-pass
python scripts/build_findings.py        # outputs/reports/atl13_v1_findings.md
pytest -q
```

### V1 outputs

| path | grain |
|---|---|
| `data/raw/atl13/kakhovka_atl13x_raw.parquet` | verbatim SlideRule return |
| `data/processed/kakhovka_atl13_segments.parquet` | normalised segments |
| `data/processed/kakhovka_atl13_evrs.parquet` | segments + EVRS columns + `period` |
| `data/processed/kakhovka_atl13_pass_levels.parquet` | one row per `(date, rgt, beam)` |
| `outputs/tables/atl13_pass_levels.csv` | same, as CSV |
| `outputs/reports/atl13_v1_findings.md` | what ICESat-2 shows, with numbers |

`pass_levels` columns: `datetime, year, rgt, beam, transect, period, n_points,
median_wse_evrs_m, mean_wse_evrs_m, std_m, mad_m, nmad_m, p05_m, p95_m, range_m,
track_length_km, along_track_slope_m_per_km, mean_stdev_water_surf_m, lat_mean,
lon_mean, qc_pass, qc_flags`.

### First-run result (323 seed granules, 2018-10 → 2025-12)

~514k segments over 17 RGTs → 1680 beam-passes, 1138 pass QC. `egm2008_minus_evrs_m`
= −0.145 ± 0.027 m (smooth). PRE_BREACH 2018–2022 stable-pool WSE ≈ **15.96 m
EVRS** (p05–p95 15.7–16.4), within-pass NMAD ≈ 2 cm, cross-beam spread ≈ 7 cm.
ICESat-2 also captured the ~3 m pre-breach drawdown/refill in spring 2023, and
the drop to ~9 m (drawdown) then ~5 m (post-breach). See the findings report.

## Phase 2a — local vertical alignment at every Kakhovka gauge

```bash
python scripts/local_alignment.py --maps   # all posts + figures
python scripts/local_alignment.py --station 80959
jupyter lab notebooks/06_local_alignment.ipynb   # code, maps and the full write-up
```

Works from the **point-level** `kakhovka_atl13_evrs.parquet` (not the
reservoir-wide pass levels): each ATL13 segment gets a distance to the post, local
pass levels are rebuilt per `(date, rgt, beam)` inside a radius, and those are
matched to that post's stage series. `PRE_BREACH` only — after 2023-06-06 the local
surface is no longer the reservoir and must never enter the tie.

| post | km from dam | radius | n | `alignment_constant_m` | NMAD |
|---|---:|---:|---:|---:|---:|
| 80977 Nova Kakhovka | 0 | 2 km | 12 | 12.343 | 0.053 |
| 80971 Velyka Lepetykha | 61 | 3 km | 5 | 12.369 | 0.060 |
| 80964 Nikopol | 115 | 2 km | 8 | 12.379 | 0.034 |
| 80963 Blahovishchenka | 134 | 2 km | 11 | 12.333 | 0.049 |
| 80961 Plavni | 171 | 3 km | 8 | 12.406 | 0.060 |
| 80959 Rozumivka | 173 | 2 km | 9 | 12.350 | 0.038 |

Median **12.359 m**, spread **7.3 cm** over ~175 km with six independent RGT sets;
`corr(C, distance from dam) = +0.34` — **no longitudinal trend**. Since every post
carries the same *nominal* 12.00 m BS-77 zero and the pool is quasi-horizontal
(donor slope ≈ 10⁻⁵, < 0.2 m over 178 km), that spread is essentially the
**relative error between the posts' true gauge zeros**, not a hydraulic gradient.
Among the 14 RGTs with n ≥ 5, per-RGT bias spans only −0.023 … +0.040 m.

A post whose 2 km radius is too thin is reported at the smallest radius that
reaches the confidence threshold, flagged in the `note` column.

Local QC is separate from the reservoir-wide one (track-length and slope checks are
meaningless inside a few-km circle) and adds an **ICESat-only plausibility gate**:
the local level must be within 3 m of the reservoir-wide ICESat level on the same
date. This catches internally-flat bank/land returns — one such pass at 22.99 m
(≈7 m above the water) was removed by it. CIs are around the **median**
(`1.96 · 1.2533 · NMAD / √n`), so one outlier cannot inflate them.

Figures (`outputs/figures/`): `map_overview`, `map_stations`, `map_alignment`,
`alignment_longitudinal`, `alignment_radius_stability`, `scatter_<post>`.

## Phase 2b — the official Baltic-1977 → EVRF2019 correction

```bash
python scripts/datum_comparison.py --download --maps
jupyter lab notebooks/07_datum_comparison.ipynb
```

**EPSG:9902** ("Baltic 1977 height to EVRF2019 height") is a **grid**, not a
constant — and it is **not a quasigeoid**: it maps one system of normal heights
onto another and never touches the ellipsoid.

PROJ *defines* the operation but **ships no grid** for it: `ua_2019z.asc` is
`open_license=False`, `direct_download=False`, with an empty URL, and the PROJ CDN
carries no Ukrainian grids, so PROJ reports it `available: False`. What PROJ can
still offer between these CRSs then degrades to a **ballpark `proj=noop`** that
silently returns 0. The grid is therefore read directly from the CRS-EU publication
of the same product (*UA_KRON/NH to EVRF2019zero*).

Once the grid *is* in hand, PROJ can run the shift itself — `export_datum_geotiff.py`
writes a PROJ-conformant vertical-offset GeoTIFF, and `tests/test_official_datum.py`
feeds it back as `+proj=vgridshift` to cross-check our own reader. **They agree to
better than a micrometre at all six posts and across the grid interior**, which is
an independent implementation check the statistics comparison cannot provide.

Before use the grid also gets a **numerical sanity check** against the published
EPSG metadata — its 3776 valid nodes match the count published by Stopkhai et al.
(2026), and mean/min/SD agree to a few millimetres. That is a *consistency* check,
not proof of file identity (the published statistics come from a 154-point defining
set, ours from 3776 interpolated nodes); identity is the SHA-256 in
`outputs/reports/provenance.json`. Its real job is catching a wrong or all-zero
grid, which the ballpark fallback would otherwise hide.

EPSG:9903 is the mean-tide sibling and is deliberately unused: EGG2015 and
EVRF2019 (EPSG:9389) are both zero-tide, so this branch never mixes tide systems.

| | value |
|---|---|
| Official BS-77 → EVRF2019 **at the Kakhovka posts** | **0.172 … 0.216 m** (median **0.186**) |
| National range (EPSG:9902) | 0.079 … 0.285 m, mean 0.151 |
| Empirical `C − nominal zero` | **+0.359 m** |
| `delta_unexplained_m` | **+0.170 m** (0.128 … 0.217) |

So roughly **half** the empirical constant is the real, officially sanctioned datum
correction. The remainder is **not** a datum residual — it holds the gauge-zero
error (12.00 m is a rounded reservoir-wide nominal, not six surveyed zeros),
EGG2015's ~0.1 m model error over Ukraine, and any ATL13 bias. These enter `c`
additively and gauges plus ICESat alone **cannot separate them**.

A common **adopted** gauge datum zero of 12.000 m in Baltic 1977 is used for all six
posts. It is a fixed constant of the model, not an estimated parameter — so the
`implied_gauge_zero_baltic_m` column is a *diagnostic, not a result*: it says what
the true zeros would have to be **if** the EGG2015 and ATL13 systematics were exactly
zero (12.13 … 12.22 m rather than 12.00). Arithmetically it is
`nominal_zero + delta_unexplained`, i.e. a restatement of the residual carrying no
independent information. Worth checking against a technical passport if one surfaces;
never to be reported as a measured zero.

Consistency check: `delta_unexplained_m` is **flat across the radius ladder**
(per-station spread 1.4–2.4 cm over rows with n ≥ 5), as a datum/zero term must be.
The frame terms `evrf2019_minus_evrf2007_m` (EGG2015 is EVRF2007-consistent) and
`tide_system_correction_m` default to `0.0` meaning **"not assumed"**, and stay
visible in the budget rather than being absorbed into the residual.

Figures: `datum_official_correction_map`, `datum_budget`,
`datum_unexplained_by_radius`.

### GeoTIFF for all of Ukraine

```bash
python scripts/export_datum_geotiff.py --preview            # full box, native 0.15°
python scripts/export_datum_geotiff.py --extent ukraine     # Ukraine bbox
python scripts/export_datum_geotiff.py --extent data        # shrink-wrapped
python scripts/export_datum_geotiff.py --cell-deg 0.05      # bilinear resample
python scripts/export_datum_geotiff.py --dst-crs EPSG:6381  # + projected copy
```

→ `outputs/rasters/ua_bs77_to_evrf2019z.tif` — EPSG:4258, 0.15°, nodata −9999,
float32, DEFLATE+predictor, tiled.

| `--extent` | shape | bounds | valid cells |
|---|---|---|---|
| `source` (default) | 99 × 167 | lon 20.13–45.18, lat 40.81–55.66 | 3776 |
| `ukraine` | 55 × 123 | lon 21.83–40.43, lat 44.19–52.51 | 3776 |
| `data` | 55 × 123 | lon 21.93–40.38, lat 44.26–52.51 | 3776 |

**All three carry identical values** — only the NODATA margin differs; the script
prints how many valid cells any extent choice would drop (none, for these). The
NODATA holes inside the footprint are the **domain of the transformation itself**,
not a cropping artefact: the model covers 3776 nodes over Ukraine, Crimea included.

**Sign convention, recorded in the GeoTIFF tags:** the value is **added** to a
Baltic 1977 height to obtain the EVRF2019 (zero-tide) height. Tags also carry
`EPSG_OPERATION`, source/target vertical CRS, tide system, units, source URL,
value statistics, and — when `--cell-deg` is used — a `RESAMPLED` tag stating the
interpolation adds no information beyond the source IDW product.

The script refuses to write unless the source grid passes the same numerical
sanity check as Phase 2b, and after writing it re-reads the raster and compares it against
the source grid at every gauge (agreement ≤ 8 mm at 0.15°, ≤ 3 mm at 0.05° — the
residual is nearest-neighbour read-back of a bilinear source, not an error).

The raster is git-ignored: it is regenerable in one command and redistributes a
third-party grid.

## Phase 2 — empirical vertical alignment (general case, not run in V1)

`scripts/match_gauges.py` matches gauge **stage** series
(`data/1_data/data/parquet/post_id=<id>/year=*.parquet`, config `config/gauges.yaml`)
to ICESat-2 pass levels and computes, per station,

    alignment_constant_m = median( H_EVRS_ICESat(pass) − gauge_stage(t) )

→ `outputs/tables/gauge_vertical_alignment.csv`. This is the **empirical vertical
alignment constant** between gauge stage and ICESat-2/EGG2015 WSE. It incorporates
the gauge zero elevation, the Baltic-1977 → EVRS datum difference, and any
systematic ICESat-2 / vertical-model bias, and therefore **must not** be
interpreted as a pure Baltic-to-EVRS transformation. `datum.solve_geodetic_datum_offset`
is a stub: decomposing the constant needs a surveyed BS-77 gauge zero, a GNSS
benchmark height, or an official transform.

## Phase 2c — empirical EGG2015 → EVRF2019 corrector

```bash
python scripts/egg2015_to_evrf2019.py            # 6 gauges, radius ladder, per-RGT, bootstrap
```

Per gauge, `c_station = median( H_gauge_EVRF2019 − H_ICESat_EGG2015 )` with
`H_gauge_EVRF2019 = 12.00 + stage + Δ_EPSG9902`. Six values **−0.128 … −0.217 m**,
regional median **−0.170 m**, station-to-station NMAD 4.6 cm. **Not** a datum
transformation or a quasigeoid — it absorbs the EGG2015/EVRF2019 mismatch, the
unsurveyed gauge-zero error and any ATL13 bias, inseparably. Full write-up:
`outputs/reports/egg2015_to_evrf2019_gauge_experiment.md`.

## Phase 3 — reproducible science notebooks

```bash
python scripts/build_science_notebooks.py        # (re)generate the 3 notebooks
python scripts/spatial_model_comparison.py        # constant/plane/IDW/linear + LOSO-CV
python scripts/download_atl13_downstream.py        # ATL13 for the downstream/coastal water bodies (Kherson, Dnipro-Buh liman; network)
jupyter execute --inplace notebooks/00_data_audit.ipynb \
                          notebooks/08_methods_results.ipynb \
                          notebooks/09_spatial_validation.ipynb
```

| notebook | role |
|---|---|
| `00_data_audit.ipynb` | input hashes, ATL13 provenance/DOI, CRS + tide-system table, coverage, `provenance.json` |
| `08_methods_results.ipynb` | the human-readable study — definitions, grid sanity check, per-station/radius/RGT tables, precision-vs-accuracy budget, publication-safe wording |
| `09_spatial_validation.ipynb` | constant/plane/IDW/linear vs the adopted nearest-station surface, **leave-one-station-out CV**, and the downstream/coastal section (Kherson + Dnipro-Buh liman) |

Every number is read from `outputs/tables/egg2015_to_evrf2019_*.csv`, so a
pipeline re-run cannot leave stale prose. Notebook prose is Ukrainian; code is
English. `scripts/spatial_model_comparison.py` writes
`egg2015_to_evrf2019_spatial_cv{,_summary}.csv` — with six controls the LS plane
is the worst model (LOSO-RMSE ~7.5 cm) and no smooth model beats the regional
constant / nearest-station meaningfully; the real upgrade is external validation
(UKG2025 / GNSS-levelling), not a fancier interpolator.

## Downstream / coastal

Two ATL13 reference water bodies **below the dam**, each pulled in its own
SlideRule request, disjoint by `refid` (a segment belongs to exactly one).
Config: `config/kakhovka.yaml::downstream_bodies` (name/slug/`refid`/coord/seed
granule list/bbox-or-polygon clip) + the `downstream:` gauge-post block in
`config/gauges.yaml`; loaders in `kakhovka_altimetry.downstream`.

* **Kherson** (post **80805**, slug `kherson`, refid `5952005933`) — a Dnipro
  **river** post *below* the dam. Its donor yearbook stores
  `water_level_m_abs = h0 + level` with `h0 ≈ −5.00 m`, i.e. a genuine
  **absolute BS-77 height** (unlike the reservoir posts, which are anomalies on
  a nominal 12.00 m zero). Bbox clip.
* **Dnipro-Buh liman** (slug `dnipro_estuary`, refid `6033000138`) — the whole
  liman including the Pivdenno-Buzkyi (Southern Bug) arm up to Mykolaiv.
  Polygon clip = a buffered convex hull of 17 operator landmark points
  (`config/dnipro_estuary_points.csv` → `scripts/build_estuary_aoi.py` →
  `data/aoi/dnipro_estuary.geojson`), excluding the open Black Sea. Its coastal
  gauge is **Mykolaiv** (post **98027**), same `h0 = −5.00 m` graph zero,
  wind-setup/setdown ("згонно-нагонні") dominated, ±0.3–0.5 m events; the gauge
  position is surveyed (`46°59'03.5"N 31°58'15.3"E`), not a city-centre
  approximation.

`scripts/download_atl13_downstream.py --body <slug>` pulls ATL13 for either body
→ `data/processed/<slug>_atl13_{evrs,pass_levels}.parquet`. Each seed granule
list is a CMR polygon search (`sliderule.earthdata.cmr`, ATL13 v007) against the
body's own clip region, so it is complete for that analysis area by
construction. Notebook 09 then shows, per body, the coastal level series with
the June-2023 breach wave, the stable ICESat water surface (essentially
unchanged PRE→POST), and a **provisional** corrector built the same way as the
reservoir correctors: `c_Kherson ≈ −0.07 ± 0.08 m` (n=115 over 38 dates) and
`c_Mykolaiv ≈ −0.13 ± 0.03 m` (n=14 over 6 dates, 30 km radius). Both are weaker
than the reservoir estimate (river/liman level variability, no surveyed vertical
zero) and are read as location-independent sanity checks, not validated
downstream correctors.

> **`c_Mykolaiv` must not be quoted as a corrector.** The audit shows it moves
> −0.142 → −0.129 → −0.018 m as the pass-selection radius goes 20 → 30 → 50 km —
> a 12 cm swing, larger than the quantity itself. The reason is that the post sits
> at the head of the Southern Bug arm, which carries only **3** of the 456
> PRE_BREACH in-clip passes (lat 46.9–47.1), so the estimate is really the
> Mykolaiv gauge against the *main liman body* ~0.2 m lower — a different water
> mass. The quoted ±0.03 m is also not an uncertainty: 6 of the 14 matchups come
> from one day (2021-04-23) and share one gauge value, and 3 more fall in 2022,
> which is **entirely missing** from the Mykolaiv series and is bridged by a
> 72–111-day linear interpolation. Treat the liman as ICESat-surface context
> only until the Buh arm is properly sampled.

## Out of scope

- ATL03 photon reconstruction (`notebooks/_donor/` keeps the reference notebooks).
- Sentinel-2 / Dynamic World water masks — the AOI bbox is the V1 water filter
  (`data/Kakhovka_SA_2.geojson` stays disabled pending epoch confirmation).

## Ingest service (API → S3 → PostGIS)

The same pipeline as a service: a request names a region and a date window, a
worker pulls ATL13 through SlideRule, keeps the raw and processed parquet in S3
and upserts segments + pass levels into PostGIS.

```bash
cp .env.example .env                       # set API_KEYS, S3 + Earthdata credentials
docker compose up -d --build               # db, s3 (SeaweedFS), redis, api, worker
docker compose run --rm migrate            # alembic upgrade head
# EGG2015 into S3 once (path = EGG2015_URI in .env)
python -c "import s3fs; s3fs.S3FileSystem().put('egg_2015.tif', 'icesat2/icesat2/reference/egg_2015.tif')"

curl -X POST localhost:58000/jobs -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
     -d '{"region_slug": "kakhovka", "start": "2019-04-01", "end": "2019-05-31", "limit": 5}'
curl localhost:58000/jobs/<job_id> -H "X-API-Key: $KEY"
curl "localhost:58000/regions/kakhovka/pass-levels?format=csv&qc_pass=true" -H "X-API-Key: $KEY"
```

| endpoint | does |
|---|---|
| `POST /jobs` | `region_slug` (configured) **or** `region` (ad-hoc refid + coord + bbox/polygon), `start`, `end`, `include_cmr`, `limit`, `batch_size` → `202 {job_id}` |
| `GET /jobs/{id}`, `GET /jobs` | status per stage (discover → acquire → process → load) and counts |
| `GET /regions` | configured regions + row counts in PostGIS |
| `GET /regions/{slug}/pass-levels` | GeoJSON (track LineStrings) or `format=csv`; `start`, `end`, `qc_pass` |
| `GET /granules` | per-granule status: `pending`/`fetched`/`empty`/`loaded` |

Granules already `loaded`/`empty` are skipped, so a repeated job only pulls new
passes; every load is an upsert on `(region, beam, time)` / `(region, date, rgt, beam)`.
S3 layout and schema: `src/kakhovka_altimetry/service/storage.py`,
`migrations/versions/0001_icesat2_schema.py`. Without docker:
`python -m kakhovka_altimetry.service.worker --region kakhovka --limit 5`.

Verified against the batch pipeline on real data (10 granules, Apr–May 2019): all
46 passes match `outputs/tables/atl13_pass_levels.csv` (|Δ median WSE| ≤ 2 µm,
identical `n_points` and `qc_pass`).
