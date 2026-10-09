# ATL13 → EGG2015 → EVRS water levels for the Kakhovka reservoir — V1 findings
_Generated from `kakhovka_atl13_pass_levels.parquet` (1680 passes) and `kakhovka_atl13_evrs.parquet` (513873 point segments)._
## 1. Passes obtained
- Total beam-passes over water: **1680**
- Passing QC: **1138** (542 rejected)
- Distinct RGT/beam transects: **102**
- Date span: 2018-10-16 → 2025-12-31

Rejection reasons: slope_too_steep (250), too_few_points (244), range_too_large (189), track_too_short (86), mad_too_large (74), stdev_too_large (26)

## 2. Passes per year
|   year |   passes_total |   passes_qc_ok |
|-------:|---------------:|---------------:|
|   2018 |             40 |             37 |
|   2019 |            246 |            227 |
|   2020 |            258 |            229 |
|   2021 |            219 |            181 |
|   2022 |            222 |            184 |
|   2023 |            243 |            133 |
|   2024 |            220 |             78 |
|   2025 |            232 |             69 |

## 3. Points per pass
- All passes: median 118.00, p10 12.00, p90 722.00, min 1.00, max 7409.00
- QC-ok passes: median 185.00, p10 42.70, p90 912.90, min 20.00, max 7409.00
- Along-track length (km): median 13.94, p10 5.00, p90 33.19, min 2.18, max 51.73

## 4. Within-pass water-surface spread (QC-ok)
- `nmad_m`: median 0.02, p10 0.02, p90 0.07, min 0.01, max 0.37
- `range_m` (p95−p05): median 0.08, p10 0.05, p90 0.39, min 0.03, max 0.98
- `mad_m`: median 0.02, p10 0.01, p90 0.04, min 0.01, max 0.25
- along-track slope (m/km): median 0.00, p10 0.00, p90 0.02, min 0.00, max 0.05

## 5. Beam / transect agreement (same date + RGT, QC-ok)
- 229 multi-beam overpasses.
- Cross-beam WSE spread (m): median 0.07, p10 0.03, p90 0.17, min 0.00, max 6.95

## 6. Suspect passes
_Deviation from the seasonal mean is deliberately NOT a criterion — the reservoir level genuinely moves metres (see §7). Flags: within-pass `nmad_m` > 0.30 m or `range_m` > 2.0 m, or QC-ok beams of one date+RGT disagreeing by > 0.30 m._

- 209 flagged — within-pass spread: 152; cross-beam disagreement: 57.
- Almost all are BREACH_DRAWDOWN / POST_BREACH (braided channel, not a flat pool). Sample:

| datetime                            | transect   | period          |   n_points |   median_wse_evrs_m |    nmad_m |   range_m | qc_pass   | reason                  |
|:------------------------------------|:-----------|:----------------|-----------:|--------------------:|----------:|----------:|:----------|:------------------------|
| 2023-06-27 03:09:08.522660352+00:00 | 105_gt3l   | BREACH_DRAWDOWN |        158 |             9.36212 | 0.171019  |  0.502244 | True      | cross-beam disagreement |
| 2023-06-27 03:09:08.773860096+00:00 | 105_gt1r   | BREACH_DRAWDOWN |         78 |             8.74895 | 0.145765  |  0.777318 | True      | cross-beam disagreement |
| 2023-06-27 03:09:08.869260288+00:00 | 105_gt3r   | BREACH_DRAWDOWN |         39 |             9.3892  | 0.0953804 |  0.472082 | True      | cross-beam disagreement |
| 2023-07-01 03:00:39.970021376+00:00 | 165_gt3l   | BREACH_DRAWDOWN |        249 |             3.27477 | 0.0947934 |  2.78987  | False     | within-pass spread      |
| 2023-07-03 15:05:58.930890240+00:00 | 205_gt1l   | BREACH_DRAWDOWN |       1899 |            10.6542  | 0.14055   |  2.13515  | False     | within-pass spread      |
| 2023-07-03 15:05:59.272990208+00:00 | 205_gt1r   | BREACH_DRAWDOWN |        525 |            10.6887  | 0.196312  |  2.51169  | False     | within-pass spread      |
| 2023-07-07 14:57:41.688653056+00:00 | 265_gt2l   | BREACH_DRAWDOWN |        295 |             5.73744 | 0.38232   |  9.18337  | False     | within-pass spread      |
| 2023-07-07 14:57:42.071853056+00:00 | 265_gt2r   | BREACH_DRAWDOWN |         93 |             6.07429 | 0.578594  |  9.03924  | False     | within-pass spread      |
| 2023-07-07 14:57:43.979953152+00:00 | 265_gt3r   | BREACH_DRAWDOWN |         39 |             5.96922 | 0.374017  |  1.2901   | False     | within-pass spread      |
| 2023-07-07 14:57:45.749404928+00:00 | 265_gt3l   | BREACH_DRAWDOWN |          2 |            13.1546  | 2.89537   |  3.51522  | False     | within-pass spread      |
| 2023-07-26 01:44:58.186613248+00:00 | 545_gt3l   | BREACH_DRAWDOWN |        199 |             9.42757 | 0.320933  |  0.746823 | True      | within-pass spread      |
| 2023-07-26 01:44:58.515413248+00:00 | 545_gt3r   | BREACH_DRAWDOWN |         53 |             9.52457 | 0.338781  |  0.792712 | True      | within-pass spread      |
| 2023-07-30 01:36:35.306378496+00:00 | 609_gt3l   | BREACH_DRAWDOWN |        410 |             5.60832 | 0.424427  |  1.18747  | False     | within-pass spread      |
| 2023-07-30 01:36:35.325578752+00:00 | 609_gt2l   | BREACH_DRAWDOWN |        445 |             4.75422 | 1.10326   |  2.40086  | False     | within-pass spread      |
| 2023-07-30 01:36:35.641778688+00:00 | 609_gt3r   | BREACH_DRAWDOWN |        118 |             5.33996 | 0.506372  |  1.90363  | False     | within-pass spread      |

## 7. PRE_BREACH reservoir WSE (up to 2023-06-06, QC-ok)
- n passes: **957** (2018–2022 stable pool: 858)
- **2018–2022 stable pool: typical WSE 15.96 m EVRS** (mean 15.99, std 0.23, p05–p95 15.66–16.41)
- Full PRE_BREACH incl. 2023: 15.96 m median, range 14.05 … 17.49 m

**2023 pre-breach was anomalous**: the reservoir was drawn down to ~14.2 m EVRS by Feb–Mar 2023, then refilled to ~17.4 m by May 2023 — a ~3 m swing captured by ICESat-2 *before* the 6 June breach. This is why the 2023 row has a large std.

Per year:
|   year |   n |   median |   std |    min |    max |
|-------:|----:|---------:|------:|-------:|-------:|
|   2018 |  37 |   15.849 | 0.065 | 15.728 | 16.005 |
|   2019 | 227 |   15.817 | 0.172 | 15.551 | 16.278 |
|   2020 | 229 |   15.946 | 0.107 | 15.641 | 16.141 |
|   2021 | 181 |   16.117 | 0.181 | 15.744 | 16.475 |
|   2022 | 184 |   16.196 | 0.292 | 15.306 | 16.579 |
|   2023 |  99 |   15.042 | 1.418 | 14.047 | 17.492 |

Monthly, Nov 2022 → Jun 2023 (the pre-breach drawdown/refill):
| month   |   n |   median |
|:--------|----:|---------:|
| 2022-11 |  12 |    15.35 |
| 2022-12 |   6 |    15.81 |
| 2023-01 |   6 |    15.04 |
| 2023-02 |  22 |    14.19 |
| 2023-03 |  24 |    14.52 |
| 2023-04 |   6 |    16.8  |
| 2023-05 |  29 |    17.39 |
| 2023-06 |  12 |    17.24 |

## 8. After the dam breach — reported separately
- **BREACH_DRAWDOWN**: n=34, WSE median 9.38 m EVRS, range 1.14 … 12.70 m (2023-06-08 → 2023-10-24)
- **POST_BREACH**: n=147, WSE median 5.20 m EVRS, range 0.18 … 15.04 m (2024-01-01 → 2025-12-31)

_Not mixed into the PRE_BREACH reservoir statistics above._

## 9. Vertical-chain sanity: EGM2008 − EGG2015/EVRS
- `egm2008_minus_evrs_m`: mean **-0.145 m**, std 0.027 m, range [-0.201, -0.102]
- Expected: small (decimetre) and spatially smooth → the ellipsoidal / EGM2008 / EGG2015 chain is not mixed up.
