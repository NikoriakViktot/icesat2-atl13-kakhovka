# Empirical EGG2015 → EVRF2019 corrector from the Kakhovka gauges

_ATL13 point-level `H_evrs_egg2015_m` (= `ht_water_surf − ζ_EGG2015`) within a radius of each gauge, `PRE_BREACH` only, matched to that gauge's stage series and referenced to EVRF2019 with the official EPSG:9902 grid._

> `c_station` is **not** an official datum transformation. It absorbs, inseparably from ICESat + gauges alone, the EGG2015 vs EVRF2019 model mismatch, the (unsurveyed) gauge-zero error, any systematic ICESat-2/ATL13 bias, and the spatial/temporal matchup mismatch. It equals `-delta_unexplained_m` from the Phase-2b decomposition.

## Definitions

```
c_station        = median( H_gauge_EVRF2019 − H_ICESat_EGG2015 )
H_gauge_EVRF2019 = gauge_zero_BS77 + stage_m + delta_EPSG9902(lat,lon)
H_ICESat_EGG2015 = local median H_evrs_egg2015_m  (one value per beam-pass)
use:  H_ICESat_EVRF2019_approx = H_ICESat_EGG2015 + c_station
```

Independent statistical unit = one `(date, RGT, beam)` beam-pass. Multiple ATL13 segments from one beam-pass are aggregated to a single median first and never counted as independent. Bootstrap CIs (10,000 resamples) resample beam-passes, not segments. Fewer than 5 independent beam-passes → `LOW_SAMPLE`.

## Official grid numerical sanity check

```
numerical sanity check vs the published EPSG:9902 metadata (consistency, not file identity; published stats over 154 determination points)
grid nodes (valid): 3776  [matches the published node count]
stat          grid   published     delta   decisive
mean_m       0.145       0.151    -0.006   yes
min_m        0.081       0.079    +0.002   yes
max_m        0.251       0.285    -0.034   no
sd_m         0.031       0.034    -0.003   yes
sanity check: PASS (tolerance 0.020 m on the decisive statistics; identity is established by the SHA-256 in provenance.json, not here)
```

Consistency with the published EPSG:9902 metadata, **not** proof of file identity — that is the SHA-256 in `provenance.json`. Its real job is to catch a wrong or all-zero grid, since PROJ's ballpark fallback between these CRSs silently returns 0.

## Result per gauge (at the reported radius)

| name_en          |   reported_radius_km |   n_matchups |   n_dates |   n_rgts |   delta_epsg9902_m |   c_station_m |   empirical_nmad_m |   bootstrap_ci95_low_m |   bootstrap_ci95_high_m |   c_station_B_nearest_m |   c_station_C_dailymean_m |   temporal_spread_m | flag   |
|:-----------------|---------------------:|-------------:|----------:|---------:|-------------------:|--------------:|-------------------:|-----------------------:|------------------------:|------------------------:|--------------------------:|--------------------:|:-------|
| Nova Kakhovka    |                    2 |           12 |         8 |        2 |              0.216 |        -0.128 |              0.053 |                 -0.165 |                  -0.094 |                  -0.13  |                    -0.119 |               0.011 | OK     |
| Velyka Lepetykha |                    3 |            5 |         3 |        2 |              0.179 |        -0.189 |              0.06  |                 -0.23  |                  -0.131 |                  -0.182 |                    -0.188 |               0.007 | OK     |
| Nikopol          |                    2 |            8 |         4 |        2 |              0.172 |        -0.208 |              0.034 |                 -0.24  |                  -0.183 |                  -0.208 |                    -0.207 |               0.001 | OK     |
| Blahovishchenka  |                    2 |           11 |         6 |        2 |              0.183 |        -0.15  |              0.049 |                 -0.189 |                  -0.119 |                  -0.153 |                    -0.145 |               0.008 | OK     |
| Rozumivka        |                    2 |            9 |         6 |        2 |              0.204 |        -0.146 |              0.038 |                 -0.288 |                  -0.101 |                  -0.143 |                    -0.14  |               0.006 | OK     |
| Plavni           |                    3 |            8 |         3 |        2 |              0.189 |        -0.217 |              0.06  |                 -0.266 |                  -0.181 |                  -0.217 |                    -0.222 |               0.005 | OK     |

## 1–2. Radius ladder, per gauge

`n` = independent beam-passes = `n_matchups`. Open question marks in the figures are `n<5`.

### Blahovishchenka

| name_en         |   radius_km |   n_matchups |   n_dates |   n_rgts |   median_h_icesat_egg2015_m |   c_station_m |   empirical_nmad_m |   bootstrap_ci95_low_m |   bootstrap_ci95_high_m | flag       |
|:----------------|------------:|-------------:|----------:|---------:|----------------------------:|--------------:|-------------------:|-----------------------:|------------------------:|:-----------|
| Blahovishchenka |         0.5 |            3 |         2 |        1 |                      15.928 |        -0.125 |              0.041 |                 -0.153 |                  -0.097 | LOW_SAMPLE |
| Blahovishchenka |         1   |            6 |         4 |        2 |                      15.94  |        -0.173 |              0.061 |                 -0.214 |                  -0.107 | OK         |
| Blahovishchenka |         2   |           11 |         6 |        2 |                      15.937 |        -0.15  |              0.049 |                 -0.189 |                  -0.119 | OK         |
| Blahovishchenka |         3   |           16 |         7 |        2 |                      15.934 |        -0.167 |              0.039 |                 -0.19  |                  -0.138 | OK         |
| Blahovishchenka |         5   |           27 |         8 |        2 |                      15.934 |        -0.158 |              0.062 |                 -0.189 |                  -0.128 | OK         |
| Blahovishchenka |        10   |           54 |        13 |        5 |                      15.929 |        -0.156 |              0.046 |                 -0.181 |                  -0.142 | OK         |

### Nikopol

| name_en   |   radius_km |   n_matchups |   n_dates |   n_rgts |   median_h_icesat_egg2015_m |   c_station_m |   empirical_nmad_m |   bootstrap_ci95_low_m |   bootstrap_ci95_high_m | flag       |
|:----------|------------:|-------------:|----------:|---------:|----------------------------:|--------------:|-------------------:|-----------------------:|------------------------:|:-----------|
| Nikopol   |         0.5 |            1 |         1 |        1 |                      15.906 |        -0.194 |              0     |                nan     |                 nan     | LOW_SAMPLE |
| Nikopol   |         1   |            3 |         2 |        1 |                      15.941 |        -0.197 |              0.015 |                 -0.229 |                  -0.186 | LOW_SAMPLE |
| Nikopol   |         2   |            8 |         4 |        2 |                      16.006 |        -0.208 |              0.034 |                 -0.24  |                  -0.183 | OK         |
| Nikopol   |         3   |           16 |         5 |        2 |                      16.005 |        -0.194 |              0.031 |                 -0.221 |                  -0.18  | OK         |
| Nikopol   |         5   |           24 |         7 |        4 |                      15.959 |        -0.194 |              0.036 |                 -0.221 |                  -0.184 | OK         |
| Nikopol   |        10   |           59 |        13 |        4 |                      16.036 |        -0.186 |              0.03  |                 -0.192 |                  -0.178 | OK         |

### Nova Kakhovka

| name_en       |   radius_km |   n_matchups |   n_dates |   n_rgts |   median_h_icesat_egg2015_m |   c_station_m |   empirical_nmad_m |   bootstrap_ci95_low_m |   bootstrap_ci95_high_m | flag       |
|:--------------|------------:|-------------:|----------:|---------:|----------------------------:|--------------:|-------------------:|-----------------------:|------------------------:|:-----------|
| Nova Kakhovka |           1 |            2 |         1 |        1 |                      15.679 |         0.031 |              0.03  |                  0.01  |                   0.051 | LOW_SAMPLE |
| Nova Kakhovka |           2 |           12 |         8 |        2 |                      15.914 |        -0.128 |              0.053 |                 -0.165 |                  -0.094 | OK         |
| Nova Kakhovka |           3 |           19 |         8 |        2 |                      15.933 |        -0.138 |              0.051 |                 -0.159 |                  -0.104 | OK         |
| Nova Kakhovka |           5 |           22 |         8 |        2 |                      15.936 |        -0.13  |              0.047 |                 -0.156 |                  -0.107 | OK         |
| Nova Kakhovka |          10 |           34 |        10 |        4 |                      15.926 |        -0.124 |              0.055 |                 -0.152 |                  -0.104 | OK         |

### Plavni

| name_en   |   radius_km |   n_matchups |   n_dates |   n_rgts |   median_h_icesat_egg2015_m |   c_station_m |   empirical_nmad_m |   bootstrap_ci95_low_m |   bootstrap_ci95_high_m | flag       |
|:----------|------------:|-------------:|----------:|---------:|----------------------------:|--------------:|-------------------:|-----------------------:|------------------------:|:-----------|
| Plavni    |         0.5 |            2 |         1 |        1 |                      16.143 |        -0.306 |              0.035 |                 -0.329 |                  -0.282 | LOW_SAMPLE |
| Plavni    |         1   |            2 |         1 |        1 |                      16.135 |        -0.298 |              0.03  |                 -0.318 |                  -0.278 | LOW_SAMPLE |
| Plavni    |         2   |            2 |         1 |        1 |                      16.106 |        -0.269 |              0.001 |                 -0.27  |                  -0.268 | LOW_SAMPLE |
| Plavni    |         3   |            8 |         3 |        2 |                      16.064 |        -0.217 |              0.06  |                 -0.266 |                  -0.181 | OK         |
| Plavni    |         5   |           11 |         4 |        2 |                      16.095 |        -0.232 |              0.039 |                 -0.258 |                  -0.188 | OK         |
| Plavni    |        10   |           26 |        10 |        3 |                      16.036 |        -0.229 |              0.044 |                 -0.245 |                  -0.205 | OK         |

### Rozumivka

| name_en   |   radius_km |   n_matchups |   n_dates |   n_rgts |   median_h_icesat_egg2015_m |   c_station_m |   empirical_nmad_m |   bootstrap_ci95_low_m |   bootstrap_ci95_high_m | flag       |
|:----------|------------:|-------------:|----------:|---------:|----------------------------:|--------------:|-------------------:|-----------------------:|------------------------:|:-----------|
| Rozumivka |         0.5 |            1 |         1 |        1 |                      15.966 |        -0.132 |              0     |                nan     |                 nan     | LOW_SAMPLE |
| Rozumivka |         1   |            7 |         4 |        2 |                      16.165 |        -0.143 |              0.032 |                 -0.288 |                  -0.122 | OK         |
| Rozumivka |         2   |            9 |         6 |        2 |                      16.167 |        -0.146 |              0.038 |                 -0.288 |                  -0.101 | OK         |
| Rozumivka |         3   |           15 |         7 |        2 |                      16.159 |        -0.146 |              0.067 |                 -0.203 |                  -0.125 | OK         |
| Rozumivka |         5   |           29 |        10 |        3 |                      16.156 |        -0.155 |              0.051 |                 -0.184 |                  -0.13  | OK         |
| Rozumivka |        10   |           54 |        15 |        4 |                      16.13  |        -0.139 |              0.067 |                 -0.171 |                  -0.124 | OK         |

### Velyka Lepetykha

| name_en          |   radius_km |   n_matchups |   n_dates |   n_rgts |   median_h_icesat_egg2015_m |   c_station_m |   empirical_nmad_m |   bootstrap_ci95_low_m |   bootstrap_ci95_high_m | flag       |
|:-----------------|------------:|-------------:|----------:|---------:|----------------------------:|--------------:|-------------------:|-----------------------:|------------------------:|:-----------|
| Velyka Lepetykha |           2 |            2 |         2 |        2 |                      15.983 |        -0.191 |              0.069 |                 -0.237 |                  -0.144 | LOW_SAMPLE |
| Velyka Lepetykha |           3 |            5 |         3 |        2 |                      15.913 |        -0.189 |              0.06  |                 -0.23  |                  -0.131 | OK         |
| Velyka Lepetykha |           5 |           10 |         4 |        2 |                      15.914 |        -0.197 |              0.05  |                 -0.23  |                  -0.162 | OK         |
| Velyka Lepetykha |          10 |           29 |         8 |        3 |                      15.954 |        -0.173 |              0.044 |                 -0.212 |                  -0.16  | OK         |

## 3. Per-RGT corrector and RGT bias

| name_en          |   radius_km |   rgt |   n_matchups |   n_dates |   correction_m |   nmad_m |   ci95_low_m |   ci95_high_m |   c_station_all_m |   rgt_bias_m | flag       |
|:-----------------|------------:|------:|-------------:|----------:|---------------:|---------:|-------------:|--------------:|------------------:|-------------:|:-----------|
| Rozumivka        |           2 |   205 |            4 |         3 |         -0.222 |    0.101 |       -0.292 |        -0.073 |            -0.146 |       -0.076 | LOW_SAMPLE |
| Rozumivka        |           2 |   989 |            5 |         3 |         -0.128 |    0.027 |       -0.151 |        -0.101 |            -0.146 |        0.018 | OK         |
| Plavni           |           3 |    45 |            4 |         2 |         -0.264 |    0.003 |       -0.266 |        -0.214 |            -0.217 |       -0.047 | LOW_SAMPLE |
| Plavni           |           3 |   645 |            4 |         1 |         -0.182 |    0.017 |       -0.22  |        -0.159 |            -0.217 |        0.036 | LOW_SAMPLE |
| Blahovishchenka  |           2 |   545 |            4 |         2 |         -0.177 |    0.041 |       -0.228 |        -0.149 |            -0.15  |       -0.027 | LOW_SAMPLE |
| Blahovishchenka  |           2 |  1149 |            7 |         4 |         -0.136 |    0.055 |       -0.183 |        -0.099 |            -0.15  |        0.014 | OK         |
| Nikopol          |           2 |   265 |            2 |         1 |         -0.234 |    0.008 |       -0.24  |        -0.229 |            -0.208 |       -0.026 | LOW_SAMPLE |
| Nikopol          |           2 |  1049 |            6 |         3 |         -0.193 |    0.019 |       -0.232 |        -0.18  |            -0.208 |        0.015 | OK         |
| Velyka Lepetykha |           3 |   165 |            3 |         2 |         -0.144 |    0.019 |       -0.189 |        -0.131 |            -0.189 |        0.045 | LOW_SAMPLE |
| Velyka Lepetykha |           3 |  1209 |            2 |         1 |         -0.22  |    0.014 |       -0.23  |        -0.211 |            -0.189 |       -0.031 | LOW_SAMPLE |
| Nova Kakhovka    |           2 |   325 |            6 |         4 |         -0.12  |    0.105 |       -0.191 |         0.025 |            -0.128 |        0.008 | OK         |
| Nova Kakhovka    |           2 |   669 |            6 |         4 |         -0.128 |    0.024 |       -0.162 |        -0.11  |            -0.128 |        0     | OK         |

Largest |RGT bias| among n≥5 rows: **1.8 cm**.

## 4. How much variation comes from what

| source | spread | how measured |
|---|---:|---|
| **station** | 9 cm (NMAD 4.6 cm) | range of `c_station` across the 6 usable gauges |
| **radius** | 1.4–2.4 cm | per-station max−min of `c_station` over n≥5 radii |
| **RGT** | 0.0–0.8 cm | per-station max−min RGT bias (n≥5) |
| **time matching (A/B/C)** | 0.1–1.1 cm | max−min of `c_station` over interpolated / nearest / daily-mean stage |
| **within-station repeatability** | NMAD 3.4–6.0 cm | beam-pass scatter at the reported radius (OK stations) |

## 5. Precision vs absolute accuracy

**PRECISION (repeatability, measured here).** The beam-pass NMAD and the bootstrap CI of the median. This is the only uncertainty these data constrain.

**ABSOLUTE ACCURACY (not fully resolved here).** Limited by, kept as separate lines and *not* combined in quadrature:

- `epsg9902_op_accuracy` = 0.068 m — EPSG:9902's published **operation accuracy** field. It is *not* a standard deviation and *not* a 95% CI: the same EPSG record separately reports SD 0.034 m over 154 determination points. Quote it as an operation accuracy or not at all.
- gauge-zero uncertainty — **not independently constrained** (no surveyed BS-77 zero; the nominal 12.00 m is a reservoir-wide figure).
- EGG2015 model error over Ukraine (~0.1 m quoted) — **unresolved**; not inferred from these gauge comparisons.
- ATL13 systematic bias — **unresolved**; the per-RGT spread bounds the track-dependent part but does not separate a common offset.
- temporal mismatch — bounded empirically by the A/B/C spread above.

See `outputs/tables/egg2015_to_evrf2019_uncertainty.csv` for the per-station split.

## 6. Final result (compact)

**Nova Kakhovka**
```
c_station              = -0.128 m   (radius 2 km, n = 12 beam-passes, 8 dates, 2 RGTs)
empirical precision    = ±0.053 m (NMAD)   std ±0.074 m
bootstrap 95% CI       = [-0.165, -0.094] m
temporal A/B/C spread  = 1.1 cm  (A -0.128 / B -0.130 / C -0.119)
EPSG:9902 op. accuracy = 0.068 m (not a sigma)
unresolved systematic  = gauge zero + EGG2015 model + ATL13 bias
```

**Velyka Lepetykha**
```
c_station              = -0.189 m   (radius 3 km, n = 5 beam-passes, 3 dates, 2 RGTs)
empirical precision    = ±0.060 m (NMAD)   std ±0.042 m
bootstrap 95% CI       = [-0.230, -0.131] m
temporal A/B/C spread  = 0.7 cm  (A -0.189 / B -0.182 / C -0.188)
EPSG:9902 op. accuracy = 0.068 m (not a sigma)
unresolved systematic  = gauge zero + EGG2015 model + ATL13 bias
```

**Nikopol**
```
c_station              = -0.208 m   (radius 2 km, n = 8 beam-passes, 4 dates, 2 RGTs)
empirical precision    = ±0.034 m (NMAD)   std ±0.026 m
bootstrap 95% CI       = [-0.240, -0.183] m
temporal A/B/C spread  = 0.1 cm  (A -0.208 / B -0.208 / C -0.207)
EPSG:9902 op. accuracy = 0.068 m (not a sigma)
unresolved systematic  = gauge zero + EGG2015 model + ATL13 bias
```

**Blahovishchenka**
```
c_station              = -0.150 m   (radius 2 km, n = 11 beam-passes, 6 dates, 2 RGTs)
empirical precision    = ±0.049 m (NMAD)   std ±0.044 m
bootstrap 95% CI       = [-0.189, -0.119] m
temporal A/B/C spread  = 0.8 cm  (A -0.150 / B -0.153 / C -0.145)
EPSG:9902 op. accuracy = 0.068 m (not a sigma)
unresolved systematic  = gauge zero + EGG2015 model + ATL13 bias
```

**Rozumivka**  _(CI much wider than NMAD — bimodal by RGT; see Recommendation)_
```
c_station              = -0.146 m   (radius 2 km, n = 9 beam-passes, 6 dates, 2 RGTs)
empirical precision    = ±0.038 m (NMAD)   std ±0.077 m
bootstrap 95% CI       = [-0.288, -0.101] m
temporal A/B/C spread  = 0.6 cm  (A -0.146 / B -0.143 / C -0.140)
EPSG:9902 op. accuracy = 0.068 m (not a sigma)
unresolved systematic  = gauge zero + EGG2015 model + ATL13 bias
```

**Plavni**
```
c_station              = -0.217 m   (radius 3 km, n = 8 beam-passes, 3 dates, 2 RGTs)
empirical precision    = ±0.060 m (NMAD)   std ±0.043 m
bootstrap 95% CI       = [-0.266, -0.181] m
temporal A/B/C spread  = 0.5 cm  (A -0.217 / B -0.217 / C -0.222)
EPSG:9902 op. accuracy = 0.068 m (not a sigma)
unresolved systematic  = gauge zero + EGG2015 model + ATL13 bias
```

## Is one Kakhovka-wide corrector justified?

- median across the 6 usable gauges: **-0.170 m**
- station-to-station NMAD: **4.6 cm**, range 9 cm (-0.217 … -0.128 m)
- median bootstrap CI half-width per station: ±3.9 cm
- trend vs longitude: slope -0.017 m per unit, R²=0.13 (n=6)
- trend vs latitude: slope -0.041 m per unit, R²=0.16 (n=6)
- trend vs ICESat level: slope -0.050 m per unit, R²=0.02 (n=6)
- trend vs `delta_EPSG9902`: slope +1.657 m per unit, R²=0.55 (n=6) — **ALGEBRAICALLY COUPLED, descriptive only.** `c = zero + stage + delta_EPSG9902 − H_ICESat`, so this regresses `c` on one of its own additive constituents; the R² carries no causal information and must not be read as evidence of a spatial relationship. An independent version needs an external quasigeoid (УКГ2025): `c_geodetic = ζ_EGG2015 − ζ_УКГ2025`.

**The station-to-station spread exceeds the per-station precision** — a single Kakhovka-wide constant is **not** justified by these data; the corrector is at least partly station-specific. What makes it station-specific is *not* determined here: unsurveyed gauge zeros, EGG2015 model error and ATL13 bias all enter `c` additively and these data cannot separate them.

## Sanity checks

- Calibration is `PRE_BREACH` only; no POST_BREACH row enters any estimate (asserted in code).
- Radius dependence: per-station `c_station` spread over n≥5 radii is 1.4–2.4 cm (within 10 cm) — flat.
- RGT dependence: among n≥5 RGT subsets the bias is ≤1.8 cm — flat. Among n<5 RGT subsets it reaches 7.6 cm: Rozumivka RGT 205 (n=4, bias -7.6 cm); Plavni RGT 45 (n=4, bias -4.7 cm); Velyka Lepetykha RGT 165 (n=3, bias +4.5 cm). These are the ascending upstream tracks that clip the shoreline; they are why Rozumivka's 2 km bootstrap CI is wide and bimodal. Not removed — see the recommendation below.
- Outliers at each station's reported radius (|c − station c| > 0.12 m), **listed, not removed**: 4 of 53.

| name_en       | date       |   rgt | beam   |   mean_distance_km |   h_icesat_egg2015_m |   c_station_A_m |
|:--------------|:-----------|------:|:-------|-------------------:|---------------------:|----------------:|
| Nova Kakhovka | 2020-04-16 |   325 | gt3l   |              1.052 |               15.71  |           0     |
| Nova Kakhovka | 2020-04-16 |   325 | gt3r   |              1.036 |               15.659 |           0.05  |
| Rozumivka     | 2021-04-07 |   205 | gt2l   |              1.267 |               16.337 |          -0.292 |
| Rozumivka     | 2021-04-07 |   205 | gt2r   |              1.269 |               16.333 |          -0.288 |

## Recommendation

- **Every gauge here is thin** (5–12 independent beam-passes at the reported radius; 2020–2021 only, except Rozumivka). Treat all six correctors as provisional.
- **Rozumivka** — the 2 km pooled value (−0.146 m) is split by RGT (989 → −0.128, 205 → −0.222). RGT 205 reads high near the shoreline. The 3 km and 5 km values (−0.146, −0.155 m; NMAD 5–7 cm; CI ≈ ±4 cm) are more stable and are the recommended figure: **c ≈ −0.15 m, empirical precision ±0.05 m**.
- The six correctors cluster at **−0.13 … −0.22 m, median −0.17 m** (station-to-station NMAD 4.6 cm). A single regional constant of **−0.17 ± 0.05 m** is defensible as a first approximation; a per-station value is better where one exists.
- A common **adopted** gauge datum zero of 12.000 m in Baltic 1977 was used for all six posts. It is an adopted constant, not an estimated parameter — the `implied_gauge_zero_baltic_m` diagnostic below simply restates the residual against it and is not an independent result.

## Figures

- `outputs/figures/correction_by_station.png`
- `outputs/figures/correction_by_radius.png`
- `outputs/figures/correction_by_rgt.png`
- `outputs/figures/residual_vs_distance.png`
- `outputs/figures/residual_vs_time.png`
- `outputs/figures/gauge_vs_icesat_timeseries.png`

## Method notes

- Local beam-pass = one `(date, RGT, beam)` inside the radius; level = median `H_evrs_egg2015_m`. Local QC: `n_seg ≥ 10`, `NMAD ≤ 0.25 m`, and `|level − reservoir-wide ICESat level that date| ≤ 3.0 m` (reference never the gauge).
- Temporal strategies: **A** linear-interpolate the 08:00/20:00 term readings to the overpass (primary); **B** nearest term reading; **C** linear-interpolate the daily mean. Tolerance to the nearest real reading 12 h (A/B), 18 h (C). Missing days are not interpolated across (the gap check drops them).
- Gauge term timestamps are Europe/Kyiv (per `config/gauges.yaml`), converted to UTC before matching to the UTC ICESat time.
- `delta_EPSG9902` is sampled once per gauge from `ua_2019z.asc` (EPSG:9902, zero-tide).
- Reported radius = the radius nearest 2 km that reaches 5 independent beam-passes.
- Implied BS-77 gauge zero under zero EGG2015/ATL13 systematic bias = `nominal_zero − c_station` (see the by-station table); this is a prediction to test against a technical passport, **not** a measured zero.
