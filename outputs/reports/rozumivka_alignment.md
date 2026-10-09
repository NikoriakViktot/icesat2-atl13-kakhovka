# Local vertical alignment at с. Розумівка (post 80959)

_ATL13 point-level EVRS within a radius of the gauge, `PRE_BREACH` only, matched to the gauge stage series._

## Result (main radius 2 km)

**alignment_constant_m = 12.350 m** (NMAD 0.038 m, n = 9, 6 dates, RGTs 205,989, 95% CI [12.319, 12.381])

So `H_gauge_aligned(t) = stage(t) + 12.350 m`.

Empirical EVRS−BS77 difference (nominal zero 12.00 m): **+0.350 m**.

> `alignment_constant_m` is the **empirical vertical alignment constant** between gauge stage and ICESat-2/EGG2015 water-surface elevations. It incorporates the gauge zero elevation, the Baltic-1977 → EVRS datum difference, and any systematic ICESat-2 / vertical-model bias, and therefore **must not** be interpreted as a pure Baltic-to-EVRS transformation.

## Sensitivity to radius

|   radius_km |   n_matchups |   n_dates |   n_rgts |           rgts |   alignment_constant_m |   nmad_m |    std_m |   ci95_low_m |   ci95_high_m |   evrs_minus_bs77_m | indicative   |
|------------:|-------------:|----------:|---------:|---------------:|-----------------------:|---------:|---------:|-------------:|--------------:|--------------------:|:-------------|
|         0.5 |            1 |         1 |        1 |            989 |                12.3356 |   0      | nan      |     nan      |      nan      |              0.3356 | True         |
|         1   |            7 |         4 |        2 |        205,989 |                12.3467 |   0.0318 |   0.0802 |      12.3172 |       12.3762 |              0.3467 | False        |
|         2   |            9 |         6 |        2 |        205,989 |                12.3498 |   0.0376 |   0.0771 |      12.319  |       12.3807 |              0.3498 | False        |
|         3   |           15 |         7 |        2 |        205,989 |                12.3498 |   0.0673 |   0.0677 |      12.3072 |       12.3925 |              0.3498 | False        |
|         5   |           29 |        10 |        3 |     45,205,989 |                12.3585 |   0.0511 |   0.0832 |      12.3352 |       12.3818 |              0.3585 | False        |
|        10   |           54 |        15 |        4 | 45,205,645,989 |                12.3424 |   0.067  |   0.126  |      12.32   |       12.3648 |              0.3424 | False        |

Across the well-populated radii (1–10 km) the constant varies by only **1.6 cm** and every 95% CI overlaps — the local tie is stable and not an artefact of the radius choice.

Rows flagged `indicative` have fewer than 5 matchups — consistent with the main radius but carrying no statistical weight:
- **0.5 km**: n = 1, 1 date, RGTs 989

## Per-RGT bias

`bias_relative_to_pooled_m = median(C_RGT) − median(C_ALL)` at the same radius. Only **4 RGTs** cross near this post even at 10 km, so that wider radius is shown alongside the main one purely to give each RGT enough matchups.

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

Among RGTs with n ≥ 5 at 10 km, the bias spans -0.011 … +0.040 m — no RGT is grossly offset.
- RGT **45** has n = 4; its -0.096 m bias is not meaningful.
- RGT **645** has n = 1; its -0.315 m bias is not meaningful.

## Method

- Source: `kakhovka_atl13_evrs.parquet` (point-level), **not** the reservoir-wide pass levels.
- Distance: great-circle from each ATL13 segment to the post.
- Local pass = one `(date, rgt, beam)` inside the radius; level = median `H_evrs_egg2015_m`.
- Local QC: `n_points >= 10`, `nmad_m <= 0.25`, and a plausibility gate `|level − reservoir level that date| <= 3.0 m`. The gate is ICESat-only (the reference is the median of QC-ok reservoir-wide pass levels on the same date, never the gauge); it catches internally-flat bank/land returns that the NMAD test cannot see. The reservoir-wide QC thresholds (track length, along-track slope) are reservoir-scale and are not reused; that verdict is carried as `reservoir_qc_pass`.
- CI is around the **median** (the reported estimate): `1.96 · 1.2533 · NMAD / √n`, so a single gross outlier cannot inflate it.
- Gauge stage interpolated (linear) to the overpass time, max gap 12.0 h.
- `evrs_minus_bs77_m = alignment_constant_m − 12.00` by construction — a shift of the same quantity, not independent evidence.
