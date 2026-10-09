# Agent playbooks

Step-by-step recipes for an AI agent using this API, with the checks it should run
before it reports anything. Field reference: [agents-api.md](agents-api.md). Tool
definitions: [agent-tools.json](agent-tools.json).

General rules for every playbook:

1. **Bound the request.** Always send `start` and `end`. Use `limit` (5–10) for the
   first job in a new area, look at the result, then widen.
2. **One job at a time per region and product.** Poll `get_job` until `done` /
   `failed` before submitting the next one for the same region and product.
3. **Check, then report.** Run the sanity checks listed in each playbook. If one
   fails, say so; don't smooth it over.
4. **Always state the datum and the period** with every height you report
   (`vertical_datum`, plus `period` for the Kakhovka regions).
5. **Cite the data** (ICESat-2 / SlideRule, plus Copernicus and FABDEM when used;
   see agents-api.md §7).

---

## P1 — Water-level time series of a lake, reservoir or river

**Use when** the user asks how a water body's level changed.

1. Pick a point clearly **on the water** (not the shore) as `coord`, and a bbox
   that covers the water body with a small margin. Set `kind`: `lake` / `reservoir`
   for still water, `river` for flowing water. Use `vertical: "egm2008"` unless the
   user wants European EVRS heights and the area is in Europe.
2. `create_job` with `product: "ATL13"`, the inline `region`, a 1–3 month window and
   `limit: 10`.
3. Poll. On `done`, check `stats`:
   - `water_segments > 0`. If 0, `coord` may not be on an ATL13 reference water
     body; move it toward the centre of the water body and retry.
   - `pass_levels_qc / pass_levels` ≥ 0.5 for still water. Lower than that suggests
     a wrong clip, shore contamination or a river registered as a lake.
4. Widen the window step by step (re-submit the same request with a later `end`;
   already loaded granules are skipped).
5. `get_pass_levels(slug, qc_pass=true, format="csv")` → per date, take the
   **median of `median_wse_m` across beams**.

**Sanity checks before reporting**
- Within one date, beams should agree to a few dm on a lake. A spread of metres
  means contamination (or a river with slope).
- A jump of metres between consecutive passes is either real (dam breach,
  drawdown, flood) or a QC failure; check `n_points` and `nmad_m` of those passes.
- The level should be plausible for the area (compare with any known elevation;
  `compare: ["cop30"]` gives the DEM's flattened lake level from 2011–2015).

**Report**: date range, number of dates, level range and trend, datum, and the
number of QC-passed passes.

---

## P2 — Validate a DEM (Copernicus / FABDEM) with ICESat-2

**Use when** the user asks how accurate a DEM is in an area, or which DEM to trust.

1. Register a land region (`bbox` ≲ 0.5° × 0.5°; no `coord` needed).
2. `create_job`: `product: "ATL08"`, `compare: ["cop30", "fabdem"]`, a 6–12 month
   window, `limit: 10`.
3. On `done`, read `stats.dem_comparison` (or `get_dem_comparisons(job_id)`).

**Interpretation**
- `median_m` is the vertical bias of the DEM relative to ICESat-2 (positive means
  ICESat-2 is above the DEM). `nmad_m` is the robust random error. Report these
  two; mention `rmse_m` only together with them, because outliers inflate it.
- FABDEM is bare earth and COP30 is a surface model. Over forest or built-up
  areas, ICESat-2 terrain sits below COP30 (negative `median_m` for COP30), while
  FABDEM should be closer to zero. That gap is the vegetation and building effect,
  not an error.
- Reference values on farmland (this stack): COP30 −0.44 / 0.84 m, FABDEM
  −0.29 / 0.58 m. Biases of **tens of metres** are not real; they mean a datum
  mix-up, so stop and report it.
- `n` < 100 is thin; widen the window.

---

## P3 — Terrain model (DTM) or canopy height map from ICESat-2

1. Land region; `product: "ATL08"`, `dem: {"resolution_m": 100}` (variables
   default to `dtm` + `chm`). For a denser ground model over a small area use
   `product: "ATL03"`, `atl03: {"cnf": 4, "atl08_class": ["atl08_ground"]}`,
   `dem: {"resolution_m": 30}`, `limit` ≤ 5.
2. On `done`, `list_rasters(job_id=…)`; give the user `raster_id`, `crs`,
   `resolution_m`, `stats.valid_cells` and the download path
   `/rasters/{raster_id}/download`.

**Explain the gaps.** ICESat-2 samples lines ~3 km apart, so the raster has values
only along tracks (band 2 = points per cell). Never present it as a wall-to-wall
DEM. For fuller coverage use a longer window or coarser cells.

**Sanity checks**: `stats.median` of `dtm` close to the area's known elevation; a
30 m ATL03 DTM and a 100 m ATL08 DTM of the same area should agree within about 1 m
(near Nova Kakhovka: 16.97 m vs 16.85 m).

---

## P4 — Reproduce or extend the Kakhovka reservoir record

Configured regions already exist: `kakhovka` (reservoir, EVRS/EGG2015, curated
granule list), `kherson`, `dnipro_estuary` (rivers). Use `region_slug`, not an
inline region.

- Never mix `PRE_BREACH` with `BREACH_DRAWDOWN` / `POST_BREACH` in one statistic:
  the reservoir stopped existing on 2023-06-06.
- Heights here are `EVRS_EGG2015` (EVRF2007-consistent normal heights), *not*
  EVRF2019 and not EGM2008; say so.
- Reference: pre-breach stable pool ≈ 15.96 m EVRS; drawdown to ≈ 9 m, then ≈ 5 m
  post-breach.

---

## Failure handling

| what you see | do |
|---|---|
| 422 on `create_job` | read `detail`, fix the body, resubmit (don't loop more than twice) |
| `failed` at `acquire` | wait a few minutes and resubmit the same request once; then report |
| `failed` at `process`, message mentions EGG2015 | re-register the region with `vertical: "egm2008"` |
| `done` with `to_fetch: 0` | nothing new in the window; widen dates or check `list_granules` |
| `done`, `points: 0` / `water_segments: 0` | wrong area/coord, or no ICESat-2 tracks in that window |
| a number you cannot explain | report it as unexplained, with the job_id; don't invent a cause |

## System-prompt template for an agent built on this API

```
You can ingest and analyse NASA ICESat-2 satellite altimetry through the tools
create_job, get_job, register_region, get_pass_levels, get_points,
get_dem_comparisons, list_rasters, list_products, list_regions, list_granules.
- Jobs are asynchronous: after create_job, poll get_job (5-10 s, then 30 s) until
  status is done or failed. Never claim results before status is done.
- Always bound requests with start/end; begin new areas with limit 5-10.
- ATL13 = water levels (needs a coord on the water), ATL08 = terrain and canopy,
  ATL03 = photons (small areas only). compare = ["cop30","fabdem"] validates DEMs.
- Every height has a datum (vertical_datum: EGM2008 or EVRS_EGG2015); always state it.
- DEM comparison: report median_m (bias) and nmad_m (spread); biases of tens of
  metres signal an error, not a result.
- ICESat-2 rasters are sparse along tracks; never present them as complete maps.
- If a check fails or a value is unexplained, say so and give the job_id.
```
