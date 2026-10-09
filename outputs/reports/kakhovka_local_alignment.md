# Local vertical alignment at the Kakhovka reservoir gauges

_ATL13 point-level EVRS within a radius of each post, `PRE_BREACH` only, matched to that post's stage series._

> `alignment_constant_m` is the **empirical vertical alignment constant** between gauge stage and ICESat-2/EGG2015 water-surface elevations. It incorporates the gauge zero elevation, the Baltic-1977 → EVRS datum difference, and any systematic ICESat-2 / vertical-model bias, and therefore **must not** be interpreted as a pure Baltic-to-EVRS transformation.

## Result per station

|   station_id | name_en          |   distance_from_dam_km |   reported_radius_km |   n_reported |   alignment_constant_m |   nmad_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | note                                         |
|-------------:|:-----------------|-----------------------:|---------------------:|-------------:|-----------------------:|---------:|-------------:|--------------:|--------------------:|:---------------------------------------------|
|        80977 | Nova Kakhovka    |                  0     |                    2 |           12 |                 12.343 |    0.053 |       12.306 |        12.381 |               0.343 |                                              |
|        80971 | Velyka Lepetykha |                 61.317 |                    3 |            5 |                 12.369 |    0.06  |       12.303 |        12.435 |               0.369 | main radius too thin (n=2); reported at 3 km |
|        80964 | Nikopol          |                115.009 |                    2 |            8 |                 12.379 |    0.034 |       12.35  |        12.409 |               0.379 |                                              |
|        80963 | Blahovishchenka  |                133.556 |                    2 |           11 |                 12.333 |    0.049 |       12.296 |        12.37  |               0.333 |                                              |
|        80961 | Plavni           |                171.775 |                    3 |            8 |                 12.406 |    0.06  |       12.354 |        12.459 |               0.406 | main radius too thin (n=2); reported at 3 km |
|        80959 | Rozumivka        |                173.713 |                    2 |            9 |                 12.35  |    0.038 |       12.319 |        12.381 |               0.35  |                                              |

Across the 6 posts with a usable tie the constant spans **7 cm** (median 12.359 m). Every post carries the same *nominal* 12.00 m BS-77 zero, and the pool is quasi-horizontal, so this spread is essentially the **relative error between the posts' true gauge zeros** — not a water-surface gradient.

## Sensitivity to radius, per station

### с. Розумівка / Rozumivka (80959)

Gauge 2020-01-01 → 2025-12-31 (4346 readings). **alignment_constant_m = 12.350 m** at 2 km (n = 9, NMAD 0.038 m).

|   radius_km |   n_matchups |   n_dates |   n_rgts |           rgts |   alignment_constant_m |   nmad_m |    std_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | indicative   |
|------------:|-------------:|----------:|---------:|---------------:|-----------------------:|---------:|---------:|-------------:|--------------:|--------------------:|:-------------|
|         0.5 |            1 |         1 |        1 |            989 |                12.3356 |   0      | nan      |     nan      |      nan      |              0.3356 | True         |
|         1   |            7 |         4 |        2 |        205,989 |                12.3467 |   0.0318 |   0.0802 |      12.3172 |       12.3762 |              0.3467 | False        |
|         2   |            9 |         6 |        2 |        205,989 |                12.3498 |   0.0376 |   0.0771 |      12.319  |       12.3807 |              0.3498 | False        |
|         3   |           15 |         7 |        2 |        205,989 |                12.3498 |   0.0673 |   0.0677 |      12.3072 |       12.3925 |              0.3498 | False        |
|         5   |           29 |        10 |        3 |     45,205,989 |                12.3585 |   0.0511 |   0.0832 |      12.3352 |       12.3818 |              0.3585 | False        |
|        10   |           54 |        15 |        4 | 45,205,645,989 |                12.3424 |   0.067  |   0.126  |      12.32   |       12.3648 |              0.3424 | False        |

Per-RGT bias:

| rgt   |   radius_km |   n_matchups |   icesat_median_wse_m |   gauge_median_stage_m |   alignment_constant_m |   nmad_m |   bias_relative_to_pooled_m |
|:------|------------:|-------------:|----------------------:|-----------------------:|-----------------------:|---------:|----------------------------:|
| 205   |           2 |            4 |               16.335  |                 3.8413 |                12.4258 |   0.1007 |                      0.0759 |
| 989   |           2 |            5 |               16.1166 |                 3.8116 |                12.3318 |   0.0268 |                     -0.0181 |
| ALL   |           2 |            9 |               16.1666 |                 3.8116 |                12.3498 |   0.0376 |                      0      |
| 45    |          10 |            4 |               16.1148 |                 3.8835 |                12.2469 |   0.0992 |                     -0.0956 |
| 205   |          10 |           26 |               16.2429 |                 3.7749 |                12.382  |   0.073  |                      0.0396 |
| 645   |          10 |            1 |               15.2657 |                 3.2382 |                12.0275 |   0      |                     -0.3149 |
| 989   |          10 |           23 |               16.1015 |                 3.8117 |                12.3311 |   0.0479 |                     -0.0113 |
| ALL   |          10 |           54 |               16.1296 |                 3.8117 |                12.3424 |   0.067  |                      0      |

### з.ст Плавні / Plavni (80961)

Gauge 2020-01-01 → 2021-12-31 (1462 readings). **alignment_constant_m = 12.406 m** at 3 km (n = 8, NMAD 0.060 m).

|   radius_km |   n_matchups |   n_dates |   n_rgts |       rgts |   alignment_constant_m |   nmad_m |   std_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | indicative   |
|------------:|-------------:|----------:|---------:|-----------:|-----------------------:|---------:|--------:|-------------:|--------------:|--------------------:|:-------------|
|         0.5 |            2 |         1 |        1 |         45 |                12.4951 |   0.0348 |  0.0332 |      12.4347 |       12.5556 |              0.4951 | True         |
|         1   |            2 |         1 |        1 |         45 |                12.487  |   0.0295 |  0.0282 |      12.4357 |       12.5383 |              0.487  | True         |
|         2   |            2 |         1 |        1 |         45 |                12.458  |   0.0014 |  0.0013 |      12.4556 |       12.4605 |              0.458  | True         |
|         3   |            8 |         3 |        2 |     45,645 |                12.4065 |   0.0602 |  0.0426 |      12.3542 |       12.4587 |              0.4065 | False        |
|         5   |           11 |         4 |        2 |     45,645 |                12.4209 |   0.0392 |  0.0377 |      12.3918 |       12.45   |              0.4209 | False        |
|        10   |           26 |        10 |        3 | 45,645,989 |                12.4185 |   0.0444 |  0.0457 |      12.3971 |       12.4399 |              0.4185 | False        |

Per-RGT bias:

| rgt   |   radius_km |   n_matchups |   icesat_median_wse_m |   gauge_median_stage_m |   alignment_constant_m |   nmad_m |   bias_relative_to_pooled_m |
|:------|------------:|-------------:|----------------------:|-----------------------:|-----------------------:|---------:|----------------------------:|
| 45    |           2 |            2 |               16.1061 |                 3.6481 |                12.458  |   0.0014 |                      0      |
| ALL   |           2 |            2 |               16.1061 |                 3.6481 |                12.458  |   0.0014 |                      0      |
| 45    |          10 |           12 |               16.0838 |                 3.6481 |                12.4235 |   0.0293 |                      0.005  |
| 645   |          10 |           10 |               15.9973 |                 3.6188 |                12.395  |   0.0438 |                     -0.0234 |
| 989   |          10 |            4 |               16.1008 |                 3.6681 |                12.4332 |   0.0853 |                      0.0147 |
| ALL   |          10 |           26 |               16.0361 |                 3.6188 |                12.4185 |   0.0444 |                      0      |

### с. Благовіщенка / Blahovishchenka (80963)

Gauge 2020-01-01 → 2021-12-31 (1462 readings). **alignment_constant_m = 12.333 m** at 2 km (n = 11, NMAD 0.049 m).

|   radius_km |   n_matchups |   n_dates |   n_rgts | rgts                 |   alignment_constant_m |   nmad_m |   std_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | indicative   |
|------------:|-------------:|----------:|---------:|:---------------------|-----------------------:|---------:|--------:|-------------:|--------------:|--------------------:|:-------------|
|         0.5 |            3 |         2 |        1 | 1149                 |                12.3089 |   0.0412 |  0.028  |      12.2504 |       12.3673 |              0.3089 | True         |
|         1   |            6 |         4 |        2 | 545,1149             |                12.356  |   0.0612 |  0.0503 |      12.2946 |       12.4173 |              0.356  | False        |
|         2   |           11 |         6 |        2 | 545,1149             |                12.3331 |   0.0495 |  0.0444 |      12.2964 |       12.3698 |              0.3331 | False        |
|         3   |           16 |         7 |        2 | 545,1149             |                12.3508 |   0.0389 |  0.0405 |      12.3269 |       12.3746 |              0.3508 | False        |
|         5   |           27 |         8 |        2 | 545,1149             |                12.3411 |   0.0616 |  0.0479 |      12.312  |       12.3703 |              0.3411 | False        |
|        10   |           54 |        13 |        5 | 105,205,545,989,1149 |                12.3394 |   0.0456 |  0.0437 |      12.3241 |       12.3546 |              0.3394 | False        |

Per-RGT bias:

| rgt   |   radius_km |   n_matchups |   icesat_median_wse_m |   gauge_median_stage_m |   alignment_constant_m |   nmad_m |   bias_relative_to_pooled_m |
|:------|------------:|-------------:|----------------------:|-----------------------:|-----------------------:|---------:|----------------------------:|
| 545   |           2 |            4 |               15.937  |                 3.5734 |                12.3603 |   0.0408 |                      0.0272 |
| 1149  |           2 |            7 |               15.9299 |                 3.6471 |                12.3196 |   0.0545 |                     -0.0135 |
| ALL   |           2 |           11 |               15.9367 |                 3.6043 |                12.3331 |   0.0495 |                      0      |
| 105   |          10 |            2 |               15.8806 |                 3.5162 |                12.3643 |   0.0374 |                      0.025  |
| 205   |          10 |            4 |               15.8543 |                 3.5541 |                12.2986 |   0.0241 |                     -0.0407 |
| 545   |          10 |           18 |               15.9337 |                 3.5426 |                12.3681 |   0.0484 |                      0.0287 |
| 989   |          10 |            2 |               16.282  |                 3.9373 |                12.3447 |   0.0155 |                      0.0054 |
| 1149  |          10 |           28 |               15.8988 |                 3.5911 |                12.3251 |   0.0366 |                     -0.0143 |
| ALL   |          10 |           54 |               15.9295 |                 3.5426 |                12.3394 |   0.0456 |                      0      |

### м. Нікополь / Nikopol (80964)

Gauge 2020-01-01 → 2021-12-31 (1462 readings). **alignment_constant_m = 12.379 m** at 2 km (n = 8, NMAD 0.034 m).

|   radius_km |   n_matchups |   n_dates |   n_rgts | rgts             |   alignment_constant_m |   nmad_m |    std_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | indicative   |
|------------:|-------------:|----------:|---------:|:-----------------|-----------------------:|---------:|---------:|-------------:|--------------:|--------------------:|:-------------|
|         0.5 |            1 |         1 |        1 | 1049             |                12.366  |   0      | nan      |     nan      |      nan      |              0.366  | True         |
|         1   |            3 |         2 |        1 | 1049             |                12.3681 |   0.0151 |   0.0224 |      12.3467 |       12.3895 |              0.3681 | True         |
|         2   |            8 |         4 |        2 | 265,1049         |                12.3793 |   0.0341 |   0.026  |      12.3497 |       12.4089 |              0.3793 | False        |
|         3   |           16 |         5 |        2 | 265,1049         |                12.3656 |   0.0308 |   0.0374 |      12.3467 |       12.3846 |              0.3656 | False        |
|         5   |           24 |         7 |        4 | 105,265,705,1049 |                12.3651 |   0.0355 |   0.0328 |      12.3473 |       12.3829 |              0.3651 | False        |
|        10   |           59 |        13 |        4 | 105,265,705,1049 |                12.3572 |   0.0301 |   0.034  |      12.3475 |       12.3668 |              0.3572 | False        |

Per-RGT bias:

| rgt   |   radius_km |   n_matchups |   icesat_median_wse_m |   gauge_median_stage_m |   alignment_constant_m |   nmad_m |   bias_relative_to_pooled_m |
|:------|------------:|-------------:|----------------------:|-----------------------:|-----------------------:|---------:|----------------------------:|
| 265   |           2 |            2 |               16.2349 |                 3.8292 |                12.4057 |   0.008  |                      0.0264 |
| 1049  |           2 |            6 |               15.9632 |                 3.58   |                12.3646 |   0.0191 |                     -0.0148 |
| ALL   |           2 |            8 |               16.0055 |                 3.6343 |                12.3793 |   0.0341 |                      0      |
| 105   |          10 |           12 |               16.0779 |                 3.7233 |                12.3549 |   0.0615 |                     -0.0023 |
| 265   |          10 |           14 |               16.2015 |                 3.8292 |                12.3628 |   0.0271 |                      0.0056 |
| 705   |          10 |            7 |               16.0325 |                 3.6095 |                12.3489 |   0.013  |                     -0.0083 |
| 1049  |          10 |           26 |               15.9433 |                 3.5949 |                12.3572 |   0.0196 |                     -0      |
| ALL   |          10 |           59 |               16.0363 |                 3.6346 |                12.3572 |   0.0301 |                      0      |

### смт Велика Лепетиха / Velyka Lepetykha (80971)

Gauge 2020-01-01 → 2021-12-31 (1462 readings). **alignment_constant_m = 12.369 m** at 3 km (n = 5, NMAD 0.060 m).

|   radius_km |   n_matchups |   n_dates |   n_rgts | rgts         |   alignment_constant_m |   nmad_m |    std_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | indicative   |
|------------:|-------------:|----------:|---------:|:-------------|-----------------------:|---------:|---------:|-------------:|--------------:|--------------------:|:-------------|
|         0.5 |            0 |         0 |        0 |              |               nan      | nan      | nan      |     nan      |      nan      |            nan      | True         |
|         1   |            0 |         0 |        0 |              |               nan      | nan      | nan      |     nan      |      nan      |            nan      | True         |
|         2   |            2 |         2 |        2 | 165,1209     |                12.3698 |   0.0687 |   0.0655 |      12.2505 |       12.4891 |              0.3698 | True         |
|         3   |            5 |         3 |        2 | 165,1209     |                12.3685 |   0.0601 |   0.0425 |      12.3025 |       12.4345 |              0.3685 | False        |
|         5   |           10 |         4 |        2 | 165,1209     |                12.3757 |   0.0497 |   0.0355 |      12.3371 |       12.4144 |              0.3757 | False        |
|        10   |           29 |         8 |        3 | 165,769,1209 |                12.3519 |   0.0442 |   0.0522 |      12.3318 |       12.3721 |              0.3519 | False        |

Per-RGT bias:

| rgt   |   radius_km |   n_matchups |   icesat_median_wse_m |   gauge_median_stage_m |   alignment_constant_m |   nmad_m |   bias_relative_to_pooled_m |
|:------|------------:|-------------:|----------------------:|-----------------------:|-----------------------:|---------:|----------------------------:|
| 165   |           2 |            1 |               16.0466 |                 3.7232 |                12.3235 |   0      |                     -0.0463 |
| 1209  |           2 |            1 |               15.92   |                 3.5039 |                12.4161 |   0      |                      0.0463 |
| ALL   |           2 |            2 |               15.9833 |                 3.6135 |                12.3698 |   0.0687 |                      0      |
| 165   |          10 |           16 |               15.9625 |                 3.6008 |                12.3396 |   0.0225 |                     -0.0123 |
| 769   |          10 |            2 |               15.9108 |                 3.45   |                12.4608 |   0.0642 |                      0.1089 |
| 1209  |          10 |           11 |               15.9288 |                 3.5039 |                12.3857 |   0.0488 |                      0.0338 |
| ALL   |          10 |           29 |               15.9539 |                 3.5128 |                12.3519 |   0.0442 |                      0      |

### м. Нова Каховка / Nova Kakhovka (80977)

Gauge 2020-01-01 → 2021-12-31 (1462 readings). **alignment_constant_m = 12.343 m** at 2 km (n = 12, NMAD 0.053 m).

|   radius_km |   n_matchups |   n_dates |   n_rgts | rgts             |   alignment_constant_m |   nmad_m |    std_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | indicative   |
|------------:|-------------:|----------:|---------:|:-----------------|-----------------------:|---------:|---------:|-------------:|--------------:|--------------------:|:-------------|
|         0.5 |            0 |         0 |        0 |                  |               nan      | nan      | nan      |     nan      |      nan      |            nan      | True         |
|         1   |            2 |         1 |        1 | 325              |                12.1851 |   0.0298 |   0.0284 |      12.1333 |       12.2369 |              0.1851 | True         |
|         2   |           12 |         8 |        2 | 325,669          |                12.3434 |   0.053  |   0.0743 |      12.3057 |       12.381  |              0.3434 | False        |
|         3   |           19 |         8 |        2 | 325,669          |                12.3538 |   0.0508 |   0.0673 |      12.3252 |       12.3824 |              0.3538 | False        |
|         5   |           22 |         8 |        2 | 325,669          |                12.3456 |   0.0475 |   0.068  |      12.3207 |       12.3704 |              0.3456 | False        |
|        10   |           34 |        10 |        4 | 325,669,769,1109 |                12.34   |   0.0552 |   0.0719 |      12.3168 |       12.3633 |              0.34   | False        |

Per-RGT bias:

| rgt   |   radius_km |   n_matchups |   icesat_median_wse_m |   gauge_median_stage_m |   alignment_constant_m |   nmad_m |   bias_relative_to_pooled_m |
|:------|------------:|-------------:|----------------------:|-----------------------:|-----------------------:|---------:|----------------------------:|
| 325   |           2 |            6 |               15.8784 |                 3.4979 |                12.3354 |   0.1054 |                     -0.0079 |
| 669   |           2 |            6 |               15.9378 |                 3.6115 |                12.3434 |   0.0238 |                      0      |
| ALL   |           2 |           12 |               15.9138 |                 3.5717 |                12.3434 |   0.053  |                      0      |
| 325   |          10 |           14 |               15.8807 |                 3.4979 |                12.3414 |   0.1038 |                      0.0014 |
| 669   |          10 |           17 |               15.9426 |                 3.6115 |                12.3413 |   0.0391 |                      0.0013 |
| 769   |          10 |            2 |               15.9291 |                 3.5975 |                12.3317 |   0.0634 |                     -0.0083 |
| 1109  |          10 |            1 |               16.3238 |                 3.9884 |                12.3354 |   0      |                     -0.0046 |
| ALL   |          10 |           34 |               15.9257 |                 3.6045 |                12.34   |   0.0552 |                      0      |

## Figures

- `outputs/figures/map_overview.png`
- `outputs/figures/map_stations.png`
- `outputs/figures/map_alignment.png`
- `outputs/figures/alignment_longitudinal.png`
- `outputs/figures/alignment_radius_stability.png`
- `outputs/figures/scatter_rozumivka.png`
- `outputs/figures/scatter_plavni.png`
- `outputs/figures/scatter_blahovishchenka.png`
- `outputs/figures/scatter_nikopol.png`
- `outputs/figures/scatter_velyka_lepetykha.png`
- `outputs/figures/scatter_nova_kakhovka.png`

## Method

- Source: `kakhovka_atl13_evrs.parquet` (point-level), **not** the reservoir-wide pass levels.
- Local pass = one `(date, rgt, beam)` inside the radius; level = median `H_evrs_egg2015_m`.
- Local QC: `n_points >= 10`, `nmad_m <= 0.25`, and an ICESat-only plausibility gate `|level − reservoir level that date| <= 3.0 m` (the reference is the median of QC-ok reservoir-wide pass levels on the same date — never the gauge). The reservoir-wide QC thresholds (track length, along-track slope) are reservoir-scale and are not reused.
- Gauge stage interpolated (linear) to the overpass time, max gap 12.0 h.
- CI is around the **median**: `1.96 · 1.2533 · NMAD / √n`.
- A station whose main radius has fewer than 5 matchups is reported at the smallest radius that reaches that count, flagged in `note`.
- `evrs_minus_bs77_m = alignment_constant_m − gauge_zero_baltic_m` by construction — a shift of the same quantity, not independent evidence.
