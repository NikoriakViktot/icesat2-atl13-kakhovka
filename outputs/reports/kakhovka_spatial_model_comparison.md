# Порівняння просторових моделей корректора EGG2015→EVRF2019

_Шість точкових оцінок `c_station` (Фаза 2c) → чотири гладкі кандидати (constant / plane / IDW p=1,2 / linear) проти прийнятої nearest-station поверхні. Валідація — виключення цілої станції (LOSO-CV): із 6 контролями випадковий спліт беззмістовний._

## LOSO-CV, зведення (відсортовано за RMSE)

| model    |   n_folds |   n_predicted |   loso_bias_cm |   loso_cmae_cm |   loso_rmse_cm |   loso_cmedian_abs_error_cm |   max_abs_error_cm |
|:---------|----------:|--------------:|---------------:|---------------:|---------------:|----------------------------:|-------------------:|
| idw_p1   |         6 |             6 |           -0.3 |            4.3 |            4.5 |                         4.3 |                5.8 |
| linear   |         6 |             2 |           -1.7 |            4.2 |            4.5 |                         4.2 |                5.9 |
| idw_p2   |         6 |             6 |           -0.4 |            4.7 |            4.9 |                         4.8 |                6.4 |
| constant |         6 |             6 |            0.3 |            5.2 |            5.3 |                         5.1 |                6.8 |
| plane    |         6 |             6 |            0.5 |            6.9 |            7.5 |                         7.2 |               11.7 |

## LOSO-CV, покроково (модель × виключена станція)

| model    | held_out_station   | held_out_slug    |   observed_c_m |   predicted_c_m |   error_m |   abs_error_m |   training_station_count |
|:---------|:-------------------|:-----------------|---------------:|----------------:|----------:|--------------:|-------------------------:|
| constant | Nova Kakhovka      | nova_kakhovka    |         -0.128 |          -0.189 |    -0.062 |         0.062 |                        5 |
| constant | Velyka Lepetykha   | velyka_lepetykha |         -0.189 |          -0.15  |     0.04  |         0.04  |                        5 |
| constant | Nikopol            | nikopol          |         -0.208 |          -0.15  |     0.058 |         0.058 |                        5 |
| constant | Blahovishchenka    | blahovishchenka  |         -0.15  |          -0.189 |    -0.04  |         0.04  |                        5 |
| constant | Rozumivka          | rozumivka        |         -0.146 |          -0.189 |    -0.043 |         0.043 |                        5 |
| constant | Plavni             | plavni           |         -0.217 |          -0.15  |     0.068 |         0.068 |                        5 |
| plane    | Nova Kakhovka      | nova_kakhovka    |         -0.128 |          -0.21  |    -0.083 |         0.083 |                        5 |
| plane    | Velyka Lepetykha   | velyka_lepetykha |         -0.189 |          -0.154 |     0.035 |         0.035 |                        5 |
| plane    | Nikopol            | nikopol          |         -0.208 |          -0.137 |     0.071 |         0.071 |                        5 |
| plane    | Blahovishchenka    | blahovishchenka  |         -0.15  |          -0.185 |    -0.035 |         0.035 |                        5 |
| plane    | Rozumivka          | rozumivka        |         -0.146 |          -0.22  |    -0.074 |         0.074 |                        5 |
| plane    | Plavni             | plavni           |         -0.217 |          -0.1   |     0.117 |         0.117 |                        5 |
| idw_p1   | Nova Kakhovka      | nova_kakhovka    |         -0.128 |          -0.184 |    -0.057 |         0.057 |                        5 |
| idw_p1   | Velyka Lepetykha   | velyka_lepetykha |         -0.189 |          -0.169 |     0.02  |         0.02  |                        5 |
| idw_p1   | Nikopol            | nikopol          |         -0.208 |          -0.166 |     0.041 |         0.041 |                        5 |
| idw_p1   | Blahovishchenka    | blahovishchenka  |         -0.15  |          -0.187 |    -0.037 |         0.037 |                        5 |
| idw_p1   | Rozumivka          | rozumivka        |         -0.146 |          -0.19  |    -0.044 |         0.044 |                        5 |
| idw_p1   | Plavni             | plavni           |         -0.217 |          -0.16  |     0.058 |         0.058 |                        5 |
| idw_p2   | Nova Kakhovka      | nova_kakhovka    |         -0.128 |          -0.187 |    -0.059 |         0.059 |                        5 |
| idw_p2   | Velyka Lepetykha   | velyka_lepetykha |         -0.189 |          -0.17  |     0.019 |         0.019 |                        5 |
| idw_p2   | Nikopol            | nikopol          |         -0.208 |          -0.164 |     0.044 |         0.044 |                        5 |
| idw_p2   | Blahovishchenka    | blahovishchenka  |         -0.15  |          -0.192 |    -0.042 |         0.042 |                        5 |
| idw_p2   | Rozumivka          | rozumivka        |         -0.146 |          -0.198 |    -0.052 |         0.052 |                        5 |
| idw_p2   | Plavni             | plavni           |         -0.217 |          -0.153 |     0.064 |         0.064 |                        5 |
| linear   | Nova Kakhovka      | nova_kakhovka    |         -0.128 |         nan     |   nan     |       nan     |                        5 |
| linear   | Velyka Lepetykha   | velyka_lepetykha |         -0.189 |          -0.165 |     0.025 |         0.025 |                        5 |
| linear   | Nikopol            | nikopol          |         -0.208 |         nan     |   nan     |       nan     |                        5 |
| linear   | Blahovishchenka    | blahovishchenka  |         -0.15  |          -0.209 |    -0.059 |         0.059 |                        5 |
| linear   | Rozumivka          | rozumivka        |         -0.146 |         nan     |   nan     |       nan     |                        5 |
| linear   | Plavni             | plavni           |         -0.217 |         nan     |   nan     |       nan     |                        5 |

## Висновок

- Найкраща за RMSE модель: **IDW p=1** (4.5 см).
- Регіональна константа: **5.3 см** RMSE — різниця з найкращою гладкою моделлю в межах ~1 см і в межах станційного NMAD (4.6 см).
- `linear` не може передбачити станції поза опуклою оболонкою решти п'яти (пости майже колінеарні вздовж водосховища) — стовпець `predicted_c_m` = NaN для них.
- Жодна гладка модель не б'є константу/nearest-station суттєво. **Рекомендація: найпростіша модель, що проходить LOSO-CV — регіональна константа −0.17 м або її кускова nearest-station форма.** Не публікувати гладкий растр як «істину» на 6 контролях; справжній апгрейд — зовнішня валідація (UKG2025 / GNSS-нівелювання).

## Фігури

- `outputs/figures/spatial_model_loso_cv.png`
- `outputs/figures/spatial_corrector_models.png`
