# Heights, geoids and digital elevation models

## From ellipsoid to "height above sea level"

ICESat-2 measures heights above the **WGS84 ellipsoid** (`h`). Maps, gauges and DEMs
use heights above a geoid or quasigeoid. The service converts every point:

```
H = h − N
```

| `vertical` | N | coverage | resulting height |
|---|---|---|---|
| `egm2008` (default) | EGM2008 geoid, PROJ `EPSG:4979 → EPSG:9518` (grid `us_nga_egm08_25` from the PROJ CDN) | global | EGM2008 orthometric height |
| `egg2015` | EGG2015 quasigeoid grid (`EGG2015_URI`) | **Europe only** | EVRF2007-consistent normal height (`EVRS_EGG2015`) |

ATL13 already ships an EGM2008 height (`ht_ortho`), which is used directly as
`h_egm2008_m`; the PROJ conversion agrees with it to ~0.1 m (Lake Victoria:
N = −16.83 m from ATL13 vs −16.96 m from PROJ).

`egg2015` is the frame of the Kakhovka research pipeline. It refuses to run when all
points fall outside the grid rather than silently returning NaN. Naming
discipline from that pipeline applies: `h − ζ_EGG2015` is **not** EVRF2019.

Whatever `vertical` a region uses, every point also gets `h_egm2008_m`, because
the reference DEMs are EGM2008.

## Reference DEMs (`compare`)

| key | dataset | heights | source | licence |
|---|---|---|---|---|
| `cop30` | Copernicus GLO-30 DSM (TanDEM-X 2011–2015, surface incl. trees/buildings) | EGM2008 | AWS Open Data `copernicus-dem-30m`, 1×1° COG tiles | Copernicus DEM licence (free, attribution) |
| `fabdem` | FABDEM V1-2: Copernicus with **forests and buildings removed** (bare earth) | EGM2008 | University of Bristol 10×10° zips, 1×1° COG tiles read with HTTP range requests | CC BY-NC-SA 4.0 (non-commercial; this project is non-commercial) |

Tiles are cached locally (`CACHE_DIR/<dem>/`) and in S3
(`reference/<dem>/`), so each tile is downloaded from its origin once.

### Why not SlideRule's raster sampling for Copernicus

SlideRule can attach `esa-copernicus-30meter` samples to each point. On this stack
those values came back **ellipsoidal** near Nova Kakhovka (COP30 − FABDEM = 23.04 m ≈
N, while `(COP30 − N) − FABDEM` = 0.07 m) but **orthometric** on Lake Victoria
(1133.0 m, the DEM's flattened lake level). A frame that changes between regions
cannot be corrected safely, so the service reads the tiles itself. Direct reads gave
16.01 m (Nova Kakhovka, FABDEM 16.27 m) and 1133.0 m (Victoria): consistent EGM2008.

### Comparison method

`dh = H_egm2008 (ICESat-2) − DEM(lat, lon)` at each point (nearest pixel), over
valid pairs; ATL13 uses only on-water segments. Reported: `n`, `median_m` (bias),
`nmad_m` = 1.4826·median(|dh − median|) (robust spread), `mean_m`, `std_m`,
`rmse_m`, `p05_m`, `p95_m`. Prefer median/NMAD: a few cliff, building or
water-edge points inflate mean, std and RMSE.

Which ICESat-2 height to compare:
- **ATL08 `h_te_median`** (terrain): matches FABDEM (bare earth). Against COP30
  (surface model) expect ICESat-2 to sit *below* the DEM where there is vegetation.
- **ATL03 with `atl08_class: ["atl08_ground"]`**: densest bare-earth check.
- **ATL13** (water): DEMs carry one flattened level per lake from 2011–2015, so
  `dh` there measures **water-level change since then**, not DEM error.

Measured on this stack:

| site | ICESat-2 | n | COP30 median / NMAD | FABDEM median / NMAD |
|---|---|---:|---|---|
| farmland S of Nova Kakhovka, 2022 | ATL08 terrain | 1238 | −0.44 / 0.84 m | −0.29 / 0.58 m |
| same area, May–Jul 2021 | ATL03 ground photons | 67 580 | — | 0.00 / 1.05 m |
| Lake Victoria SW, Mar–Apr 2023 | ATL13 water | 11 351 | +2.52 / 0.11 m | +2.52 / 0.11 m |

## ICESat-2 rasters (`dem`)

Points (ATL13: on-water only) are projected to the UTM zone of their median
position and binned on a `resolution_m` grid; each cell holds the **median** of its
points (band 1) and the **point count** (band 2). Cells without points are NaN.
Nothing is interpolated: ICESat-2 beam pairs are ~3.3 km apart and the 91-day
repeat revisits the same tracks, so a raster from a short window is a set of
lines. Use coarser cells or a longer window for fuller coverage, or treat the
raster as a validation layer.

| product | variables | column gridded |
|---|---|---|
| ATL13 | `wse` | `H_m` (water-surface elevation, region datum) |
| ATL08 | `dtm`, `chm` | `H_m` (terrain, region datum); `h_canopy_m` (height above terrain, no datum) |
| ATL03 | `dtm` | `H_m` of the kept photons (use `atl08_class: ["atl08_ground"]`) |

The 30 m ATL03 ground DTM and the 100 m ATL08 DTM near Nova Kakhovka have medians of
16.97 m and 16.85 m.

## Attribution

ICESat-2: NASA / NSIDC DAAC. SlideRule: University of Washington / NASA ICESat-2
Project Science Office. Copernicus GLO-30: © DLR e.V. 2010–2014 and © Airbus
Defence and Space GmbH 2014–2018, provided under COPERNICUS by the European Union
and ESA. FABDEM V1-2: Hawker et al. (2022), *Environ. Res. Lett.* 17 024016,
University of Bristol / Fathom. EGG2015: IAG / International Service for the
Geoid; see the README for the open provenance question of the 1′ grid in use.
