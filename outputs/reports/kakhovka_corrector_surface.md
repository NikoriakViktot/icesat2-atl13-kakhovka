# Kakhovka EGG2015 -> EVRF2019 corrector surface (Phase 2d)

> **Empirical, ATL13/gauge-constrained corrector surface.** Not an official geodetic transformation, not a new quasigeoid. Each cell's value is exactly one of the six Phase 2c `c_station` numbers, assigned by nearest-station (Voronoi) lookup -- see `outputs/reports/egg2015_to_evrf2019_gauge_experiment.md` for what `c_station` does and does not measure.

## Method

```
H_ATL13,EVRF2019_empirical = H_EGG2015 + c(x,y)
H_EGG2015 = ht_water_surf - zeta_EGG2015
c(x,y) = c_station of the nearest of the 6 control gauges
```

Nearest-station, not IDW or a plane fit: with 6 stations -- one (Rozumivka) bimodal by RGT, another (Velyka Lepetykha) at only 5 independent beam-passes -- a smooth surface would blend an unreliable station's value into its neighbours. `distance_to_control_km` is carried on every row so confidence can be judged per point; there is no hard distance cutoff beyond the reservoir AOI bbox itself.

## Control stations

| name_en          | slug             |     lat |     lon |   c_station_m |   sigma_m |   reported_radius_km |   n_matchups | flag   |
|:-----------------|:-----------------|--------:|--------:|--------------:|----------:|---------------------:|-------------:|:-------|
| Nova Kakhovka    | nova_kakhovka    | 46.7754 | 33.3746 |       -0.1277 |    0.053  |                    2 |           12 | OK     |
| Velyka Lepetykha | velyka_lepetykha | 47.1753 | 33.9311 |       -0.1893 |    0.0601 |                    3 |            5 | OK     |
| Nikopol          | nikopol          | 47.5545 | 34.3754 |       -0.2078 |    0.0341 |                    2 |            8 | OK     |
| Blahovishchenka  | blahovishchenka  | 47.4639 | 34.821  |       -0.1497 |    0.0495 |                    2 |           11 | OK     |
| Rozumivka        | rozumivka        | 47.7712 | 35.1489 |       -0.1463 |    0.0376 |                    2 |            9 | OK     |
| Plavni           | plavni           | 47.5671 | 35.3261 |       -0.2173 |    0.0602 |                    3 |            8 | OK     |

## Outputs

- `data/processed/kakhovka_atl13_evrf2019_empirical.parquet` -- 513,873 ATL13 segments, all periods, columns added: `nearest_control_station`, `distance_to_control_km`, `egg2015_to_evrf2019_corrector_m`, `corrector_uncertainty_m`, `h_evrf2019_empirical_m`.
- `outputs/tables/atl13_pass_levels_evrf2019_empirical.csv` -- 1,680 beam-passes, same columns applied to `median_wse_evrs_m`.
- `outputs/rasters/kakhovka_egg2015_to_evrf2019_corrector.tif` -- corrector c(x,y), metres, ADD to H_EGG2015.
- `outputs/rasters/kakhovka_egg2015_to_evrf2019_corrector_uncertainty.tif` -- corrector empirical precision (NMAD), metres.

## Caveats (inherited from Phase 2c, unchanged by this step)

- The corrector is calibrated on **PRE_BREACH matchups only**; applying it to BREACH_DRAWDOWN/POST_BREACH rows assumes the local EGG2015/ATL13 systematic terms it absorbs do not depend on reservoir stage. Not tested.
- `corrector_uncertainty_m` is beam-pass NMAD (repeatability) at the nearest station only. It does **not** include the EPSG:9902 published operation accuracy (0.068 m — an operation-accuracy field, not a standard deviation), the unresolved gauge-zero error, or the EGG2015 model error -- see `outputs/tables/egg2015_to_evrf2019_uncertainty.csv`.
- The raster is built only over the reservoir AOI bbox `(33.3, 46.7, 35.4, 47.9)` and must not be sampled outside it -- these 6 gauges are not a basin-wide, let alone national, corrector.
- Every station here is thin (5-12 independent beam-passes, 2020-2021 only except Rozumivka). Treat the whole surface as provisional.
- The reservoir spans ~130 km but has only 6 unevenly spaced gauges: some segments are up to **34 km** from their nearest control station (see `distance_to_control_km` per row, or the per-station breakdown printed by this script) -- this is Voronoi *assignment*, not a claim that the corrector is still accurate that far out.

