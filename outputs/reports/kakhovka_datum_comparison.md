# Baltic-1977 → EVRF2019 at the Kakhovka gauges — official vs empirical

_Official transformation: **EPSG:9902** → EVRF2019 (zero-tide). CRS-EU 'UA_KRON/NH to EVRF2019zero' == EPSG:9902 (ua_2019z.asc)_

## Headline

- Official BS-77 → EVRF2019 correction **at the Kakhovka posts**: **0.172 … 0.216 m** (median 0.186 m) — inside the national range 0.079 … 0.285 m, and above the national mean of 0.151 m.
- Empirical `C − nominal zero`: median **+0.359 m**.
- Left over: `delta_unexplained_m` median **+0.170 m** (+0.128 … +0.217).
- A common **adopted** BS-77 gauge zero of 12.00 m was used for all posts; it is a fixed constant of the model, not an estimated parameter.

> `delta_unexplained_m` is **not** a residual of the datum transformation. It still contains the gauge-zero error, EGG2015's model error over Ukraine (~0.1 m) and any systematic ATL13 bias. Separating those needs a surveyed BS-77 gauge zero or a GNSS height on a benchmark.

## Grid numerical sanity check

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

This is a **consistency check, not a proof of file identity**. The published EPSG statistics are quoted over the transformation's **154-point defining set**, while ours are over 3776 interpolated grid nodes — IDW smooths the extremes, which is why `max` sits 3.4 cm lower and is not treated as decisive. Agreement of three summary statistics says the file is *consistent with* the product, not that it *is* the product; identity is established by the SHA-256 recorded in `outputs/reports/provenance.json`. What the check does earn its keep for is catching a wrong, empty or all-zero grid — the real failure mode here, since PROJ's ballpark fallback silently returns 0. The valid-node count matches the figure published by Stopkhai et al. (2026) exactly.

## Per station

|   station_id | name_en          |   alignment_constant_m |   nominal_zero_m |   delta_empirical_m |   delta_official_m |   delta_unexplained_m |   implied_gauge_zero_baltic_m | official_within_national_range   |
|-------------:|:-----------------|-----------------------:|-----------------:|--------------------:|-------------------:|----------------------:|------------------------------:|:---------------------------------|
|        80977 | Nova Kakhovka    |                 12.343 |               12 |               0.343 |              0.216 |                 0.128 |                        12.128 | True                             |
|        80971 | Velyka Lepetykha |                 12.369 |               12 |               0.369 |              0.179 |                 0.189 |                        12.189 | True                             |
|        80964 | Nikopol          |                 12.379 |               12 |               0.379 |              0.172 |                 0.208 |                        12.208 | True                             |
|        80963 | Blahovishchenka  |                 12.333 |               12 |               0.333 |              0.183 |                 0.15  |                        12.15  | True                             |
|        80961 | Plavni           |                 12.406 |               12 |               0.406 |              0.189 |                 0.217 |                        12.217 | True                             |
|        80959 | Rozumivka        |                 12.35  |               12 |               0.35  |              0.204 |                 0.146 |                        12.146 | True                             |

## Error budget

| term | value | note |
|---|---:|---|
| `delta_official_m` | +0.186 m | EPSG:9902 grid at the post; accuracy ±0.068 m |
| `evrf2019_minus_evrf2007_m` | +0.000 m | EGG2015 is EVRF2007-consistent; **0.0 = not assumed**, cm level |
| `tide_system_correction_m` | +0.000 m | zero- vs mean-tide; **0.0 = not assumed**, ~2–3 cm at 47.7° N |
| EGG2015 model error | ±0.100 m | quoted accuracy over Ukraine; sits inside `delta_unexplained_m` |
| ATL13 bias | +0.000 m | not assumed |
| **`delta_unexplained_m`** | **+0.170 m** | gauge-zero error + EGG2015 error + ATL13 bias |

## Stability across the radius ladder

`delta_unexplained_m` must be flat in radius — it is a datum/zero term, so radius dependence would mean a bug upstream. Over rows with n ≥ 5, the per-station spread is **1.4–2.4 cm**.

Rows with n < 5 scatter much more (up to 17 cm if they are included) and are excluded from that statistic — they are small-sample noise, not a radius effect.

| name_en          |   radius_km |   n_matchups |   alignment_constant_m |   delta_unexplained_m |
|:-----------------|------------:|-------------:|-----------------------:|----------------------:|
| Nova Kakhovka    |         1   |            2 |                 12.185 |                -0.031 |
| Nova Kakhovka    |         2   |           12 |                 12.343 |                 0.128 |
| Nova Kakhovka    |         3   |           19 |                 12.354 |                 0.138 |
| Nova Kakhovka    |         5   |           22 |                 12.346 |                 0.13  |
| Nova Kakhovka    |        10   |           34 |                 12.34  |                 0.124 |
| Velyka Lepetykha |         2   |            2 |                 12.37  |                 0.191 |
| Velyka Lepetykha |         3   |            5 |                 12.369 |                 0.189 |
| Velyka Lepetykha |         5   |           10 |                 12.376 |                 0.197 |
| Velyka Lepetykha |        10   |           29 |                 12.352 |                 0.173 |
| Nikopol          |         0.5 |            1 |                 12.366 |                 0.194 |
| Nikopol          |         1   |            3 |                 12.368 |                 0.197 |
| Nikopol          |         2   |            8 |                 12.379 |                 0.208 |
| Nikopol          |         3   |           16 |                 12.366 |                 0.194 |
| Nikopol          |         5   |           24 |                 12.365 |                 0.194 |
| Nikopol          |        10   |           59 |                 12.357 |                 0.186 |
| Blahovishchenka  |         0.5 |            3 |                 12.309 |                 0.125 |
| Blahovishchenka  |         1   |            6 |                 12.356 |                 0.173 |
| Blahovishchenka  |         2   |           11 |                 12.333 |                 0.15  |
| Blahovishchenka  |         3   |           16 |                 12.351 |                 0.167 |
| Blahovishchenka  |         5   |           27 |                 12.341 |                 0.158 |
| Blahovishchenka  |        10   |           54 |                 12.339 |                 0.156 |
| Plavni           |         0.5 |            2 |                 12.495 |                 0.306 |
| Plavni           |         1   |            2 |                 12.487 |                 0.298 |
| Plavni           |         2   |            2 |                 12.458 |                 0.269 |
| Plavni           |         3   |            8 |                 12.406 |                 0.217 |
| Plavni           |         5   |           11 |                 12.421 |                 0.232 |
| Plavni           |        10   |           26 |                 12.418 |                 0.229 |
| Rozumivka        |         0.5 |            1 |                 12.336 |                 0.132 |
| Rozumivka        |         1   |            7 |                 12.347 |                 0.143 |
| Rozumivka        |         2   |            9 |                 12.35  |                 0.146 |
| Rozumivka        |         3   |           15 |                 12.35  |                 0.146 |
| Rozumivka        |         5   |           29 |                 12.358 |                 0.155 |
| Rozumivka        |        10   |           54 |                 12.342 |                 0.139 |

## Per RGT

| name_en          |   radius_km |   rgt |   n_matchups |   alignment_constant_m |   delta_unexplained_m |
|:-----------------|------------:|------:|-------------:|-----------------------:|----------------------:|
| Nova Kakhovka    |           2 |   325 |            6 |                 12.335 |                 0.12  |
| Nova Kakhovka    |           2 |   669 |            6 |                 12.343 |                 0.128 |
| Nova Kakhovka    |          10 |   325 |           14 |                 12.341 |                 0.126 |
| Nova Kakhovka    |          10 |   669 |           17 |                 12.341 |                 0.126 |
| Nova Kakhovka    |          10 |   769 |            2 |                 12.332 |                 0.116 |
| Nova Kakhovka    |          10 |  1109 |            1 |                 12.335 |                 0.12  |
| Velyka Lepetykha |           2 |   165 |            1 |                 12.323 |                 0.144 |
| Velyka Lepetykha |           2 |  1209 |            1 |                 12.416 |                 0.237 |
| Velyka Lepetykha |          10 |   165 |           16 |                 12.34  |                 0.16  |
| Velyka Lepetykha |          10 |   769 |            2 |                 12.461 |                 0.282 |
| Velyka Lepetykha |          10 |  1209 |           11 |                 12.386 |                 0.206 |
| Nikopol          |           2 |   265 |            2 |                 12.406 |                 0.234 |
| Nikopol          |           2 |  1049 |            6 |                 12.365 |                 0.193 |
| Nikopol          |          10 |   105 |           12 |                 12.355 |                 0.183 |
| Nikopol          |          10 |   265 |           14 |                 12.363 |                 0.191 |
| Nikopol          |          10 |   705 |            7 |                 12.349 |                 0.177 |
| Nikopol          |          10 |  1049 |           26 |                 12.357 |                 0.186 |
| Blahovishchenka  |           2 |   545 |            4 |                 12.36  |                 0.177 |
| Blahovishchenka  |           2 |  1149 |            7 |                 12.32  |                 0.136 |
| Blahovishchenka  |          10 |   105 |            2 |                 12.364 |                 0.181 |
| Blahovishchenka  |          10 |   205 |            4 |                 12.299 |                 0.115 |
| Blahovishchenka  |          10 |   545 |           18 |                 12.368 |                 0.185 |
| Blahovishchenka  |          10 |   989 |            2 |                 12.345 |                 0.161 |
| Blahovishchenka  |          10 |  1149 |           28 |                 12.325 |                 0.142 |
| Plavni           |           2 |    45 |            2 |                 12.458 |                 0.269 |
| Plavni           |          10 |    45 |           12 |                 12.424 |                 0.234 |
| Plavni           |          10 |   645 |           10 |                 12.395 |                 0.206 |
| Plavni           |          10 |   989 |            4 |                 12.433 |                 0.244 |
| Rozumivka        |           2 |   205 |            4 |                 12.426 |                 0.222 |
| Rozumivka        |           2 |   989 |            5 |                 12.332 |                 0.128 |
| Rozumivka        |          10 |    45 |            4 |                 12.247 |                 0.043 |
| Rozumivka        |          10 |   205 |           26 |                 12.382 |                 0.178 |
| Rozumivka        |          10 |   645 |            1 |                 12.028 |                -0.176 |
| Rozumivka        |          10 |   989 |           23 |                 12.331 |                 0.128 |

## What is and is not determined

**Determined.** The official BS-77 → EVRF2019 correction at these coordinates, from Ukraine's own transformation grid. This is the answer to "what is the Baltic→EVRF correction here".

**Not determined.** How the remaining +0.170 m splits between the gauge-zero error, EGG2015's model error and ATL13 bias — these enter `c` additively and gauges plus ICESat alone cannot separate them.

**Diagnostic, not a result.** `implied_gauge_zero_baltic_m` is a counterfactual: *if* the EGG2015 and ATL13 systematics were exactly zero, the posts' true BS-77 zeros would have to be 12.128 … 12.217 m (median 12.170) rather than the adopted 12.00 m. Because the zero is *adopted* rather than estimated, this column is arithmetically `nominal_zero + delta_unexplained` — it restates the residual and adds no independent information. It is worth checking against a technical passport if one surfaces, but it is not a measured zero and must not be reported as one.
