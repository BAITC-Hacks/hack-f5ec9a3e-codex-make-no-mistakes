# Demand cleaning results / Результаты очистки спроса

Reproduce this readout: `experiments/.venv/Scripts/python.exe scripts/summarize_cleaning_experiment.py`.
Policy and reproduction: [DEMAND_CLEANING.md](DEMAND_CLEANING.md).

## Decision

Keep the explainable cleaning policy and review artifacts, but do not enable automatic bulk exclusion as the default forecast input. On the 28-day benchmark the cleaned baseline loses in every supplier/unit group in both development and retrospective evaluation. Removing plausible bulk orders can remove recurring demand and increase underforecasting. LightGBM results below isolate feature cleaning with unchanged raw training labels; any gains are specific to those groups.

There IS a consistent short-horizon WAPE improvement: holding the original baseline models fixed, cleaning improves all four groups at 7 days in both 2025 and 2026. In 2026 the reductions range from 0.486 to 5.671 percentage points. However, underforecast ratios rise in every group; for IEK packs they rise from 34.172% to 45.230%. Keep this as an optional 7-day experiment, not evidence of better stock availability or a reason to enable cleaning for all horizons.

The useful 28-day LightGBM gain is IEK packs: WAPE improves from 46.293% to 44.515% in 2026, but the existing baseline remains better at 42.567%. IEK pieces are nearly flat, while IEK meters and Systeme are slightly worse. The packs improvement is not an overall new best forecast, and the tiny development gain for IEK pieces does not carry into 2026.

Synthetic acceptance checks retain a steady 10-unit/day series after adding one 1,000-unit order and preserve sustained 2x and 10x growth once three elevated days are visible. This establishes mechanics, not real customer intent. Recent flags can be revised as growth evidence arrives.

## Data and validation

Two original transaction workbooks; Алматы; January 2025–August 2026; exact SKU/unit separation. All 65,754 forecast keys and raw actuals are unchanged. July–December 2025 chooses models; January–August 2026 is already-known retrospective evidence, not a fresh test. No customer IDs or exact availability intervals were supplied.

The paired raw LightGBM control exactly reproduces all 65,754 earlier Tweedie predictions, actuals and baseline forecasts. All 224 model fits have training labels ending no later than their forecast origin. The experiment register independently checks exported predictions and full-cohort WAPE, bias, underforecasting and MAE. Source hashes and target signatures match.

Baseline/cleaning runtime: 189.9s; paired LightGBM runtime: 377.0s (includes preprocessing).

## Cleaning evidence

Full-source classification includes 248,915 movement rows plus two report-total footer rows quarantined for missing identity/date. The 417 negative rows remain unresolved; 31 missing quantities remain missing. These counts cover the full source, including dates outside the experiment. The experiment uses 238,402 positive source lines.

Final-cutoff document decisions (2026-09-01):

| Reason | Orders |
| --- | ---: |
| insufficient_history | 43,223 |
| regular | 173,185 |
| bulk_candidate_median_replacement | 8,829 |
| sustained_elevation_retained | 13,165 |

| Supplier / unit | Orders | Flagged | Flagged % | Raw quantity | Excluded quantity | Excluded % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 12,091 | 648 | 5.36 | 880,702.0 | 214,800.5 | 24.39 |
| IEK / упак | 8,902 | 333 | 3.74 | 70,789.0 | 15,170.0 | 21.43 |
| IEK / шт | 143,456 | 5,048 | 3.52 | 2,741,332.0 | 314,405.5 | 11.47 |
| Systeme electric / шт | 73,953 | 2,800 | 3.79 | 6,496,330.0 | 663,594.5 | 10.21 |

Bulk flags are candidates, not confirmed errors. Missing days represent zero recorded sales, not known zero underlying demand. The final-cutoff cleaned CSV is not valid input to earlier backtests; each historical origin recomputes its own cleaning.

## 28-day WAPE (%), development_2025

Lower is better. `clean_fixed_baseline` holds the original model choice fixed; `clean_selected` reselects among the same four baseline methods using 2025 only.

| Supplier / unit | Baseline | Clean fixed | Clean selected | Tweedie raw | Tweedie clean | Clean−raw Tweedie (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 50.471 | 56.813 | 54.288 | 53.751 | 54.091 | +0.340 |
| IEK / упак | 41.098 | 43.510 | 41.181 | 41.338 | 40.981 | -0.357 |
| IEK / шт | 36.057 | 38.329 | 37.332 | 36.060 | 36.044 | -0.016 |
| Systeme electric / шт | 66.951 | 67.788 | 67.788 | 67.012 | 72.135 | +5.123 |

## 28-day WAPE (%), retrospective_2026

Lower is better. `clean_fixed_baseline` holds the original model choice fixed; `clean_selected` reselects among the same four baseline methods using 2025 only.

| Supplier / unit | Baseline | Clean fixed | Clean selected | Tweedie raw | Tweedie clean | Clean−raw Tweedie (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 64.977 | 68.396 | 70.179 | 58.803 | 59.028 | +0.225 |
| IEK / упак | 42.567 | 44.218 | 47.117 | 46.293 | 44.515 | -1.778 |
| IEK / шт | 40.245 | 42.192 | 41.312 | 40.152 | 40.207 | +0.055 |
| Systeme electric / шт | 42.760 | 44.585 | 44.585 | 42.430 | 42.825 | +0.395 |

## 7-day WAPE (%), development_2025

Lower is better. `clean_fixed_baseline` holds the original model choice fixed; `clean_selected` reselects among the same four baseline methods using 2025 only.

| Supplier / unit | Baseline | Clean fixed | Clean selected | Tweedie raw | Tweedie clean | Clean−raw Tweedie (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 79.690 | 79.030 | 79.030 | 82.687 | 84.719 | +2.032 |
| IEK / упак | 51.879 | 50.713 | 50.713 | 52.854 | 50.322 | -2.532 |
| IEK / шт | 59.210 | 57.965 | 57.936 | 61.458 | 60.945 | -0.513 |
| Systeme electric / шт | 84.782 | 82.300 | 82.300 | 91.044 | 95.056 | +4.012 |

## 7-day WAPE (%), retrospective_2026

Lower is better. `clean_fixed_baseline` holds the original model choice fixed; `clean_selected` reselects among the same four baseline methods using 2025 only.

| Supplier / unit | Baseline | Clean fixed | Clean selected | Tweedie raw | Tweedie clean | Clean−raw Tweedie (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 92.697 | 89.681 | 89.681 | 85.829 | 87.119 | +1.290 |
| IEK / упак | 81.969 | 76.298 | 76.298 | 68.716 | 69.683 | +0.967 |
| IEK / шт | 71.928 | 69.096 | 70.900 | 71.399 | 70.473 | -0.926 |
| Systeme electric / шт | 73.715 | 73.229 | 73.229 | 73.505 | 77.906 | +4.401 |

## Bias and failure cases (28-day, retrospective 2026)

Negative bias means underforecasting. Underforecast ratio is missed forecast quantity divided by raw sales; it is not an inventory stockout rate.

| Supplier / unit | Model | Bias % | Underforecast % | Regular WAPE % | Intermittent WAPE % |
| --- | --- | ---: | ---: | ---: | ---: |
| IEK / м | baseline_selected | -22.722 | 43.849 | 61.155 | 112.888 |
| IEK / м | clean_fixed_baseline | -43.851 | 56.124 | 64.708 | 114.633 |
| IEK / м | clean_selected | -29.223 | 49.701 | 66.253 | 119.403 |
| IEK / м | tweedie_raw | -10.908 | 34.856 | 54.578 | 111.773 |
| IEK / м | tweedie_clean | -10.046 | 34.537 | 54.919 | 110.548 |
| IEK / упак | baseline_selected | -12.258 | 27.413 | 38.624 | 122.556 |
| IEK / упак | clean_fixed_baseline | -27.922 | 36.070 | 40.355 | 122.617 |
| IEK / упак | clean_selected | -21.680 | 34.399 | 43.459 | 121.353 |
| IEK / упак | tweedie_raw | -0.157 | 23.225 | 43.769 | 97.488 |
| IEK / упак | tweedie_clean | -0.369 | 22.442 | 41.734 | 100.948 |
| IEK / шт | baseline_selected | -10.436 | 25.341 | 36.446 | 119.418 |
| IEK / шт | clean_fixed_baseline | -20.779 | 31.486 | 38.494 | 119.255 |
| IEK / шт | clean_selected | -14.102 | 27.707 | 37.537 | 119.978 |
| IEK / шт | tweedie_raw | -2.107 | 21.129 | 36.237 | 121.744 |
| IEK / шт | tweedie_clean | -2.679 | 21.443 | 36.294 | 121.751 |
| Systeme electric / шт | baseline_selected | -25.285 | 34.023 | 40.643 | 101.275 |
| Systeme electric / шт | clean_fixed_baseline | -30.865 | 37.725 | 42.530 | 101.384 |
| Systeme electric / шт | clean_selected | -30.865 | 37.725 | 42.530 | 101.384 |
| Systeme electric / шт | tweedie_raw | -2.192 | 22.311 | 40.084 | 107.255 |
| Systeme electric / шт | tweedie_clean | -2.584 | 22.704 | 40.436 | 108.834 |

## Monthly stability (paired Tweedie, 28-day)

| Supplier / unit | Better months in 2025 / 6 | Better months in 2026 / 8 |
| --- | ---: | ---: |
| IEK / м | 3 / 6 | 3 / 8 |
| IEK / упак | 3 / 6 | 5 / 8 |
| IEK / шт | 2 / 6 | 4 / 8 |
| Systeme electric / шт | 2 / 6 | 4 / 8 |

## Model choice using 2025 only

These choices compare the two fixed Tweedie variants only; they do not override a stronger baseline or establish statistical significance. Cleaning thresholds were not retuned.

| Supplier / unit | Horizon | Selected variant |
| --- | ---: | --- |
| IEK / м | 7 | tweedie_raw |
| IEK / м | 28 | tweedie_raw |
| IEK / упак | 7 | tweedie_clean |
| IEK / упак | 28 | tweedie_clean |
| IEK / шт | 7 | tweedie_clean |
| IEK / шт | 28 | tweedie_clean |
| Systeme electric / шт | 7 | tweedie_raw |
| Systeme electric / шт | 28 | tweedie_raw |

## Registered runs and inspectable evidence

- [demand-cleaning-v1](../experiments/runs/20260923T101945737047Z-demand-cleaning-v1/manifest.json): 65,754 targets; 48 independently verified metric groups.
- [lightgbm-cleaning-v1](../experiments/runs/20260923T102653146360Z-lightgbm-cleaning-v1/manifest.json): 65,754 targets; 48 independently verified metric groups.

Detailed predictions, monthly scores and exclusion ledgers are in the two local artifact directories documented in the policy. Compact JSON summaries and source/code hashes are in the registered runs. Large CSV archives remain local and Git-ignored.

## Русский

Очистка воспроизводима, исходники и причины исключений сохранены. Синтетические проверки разового заказа и устойчивого роста проходят. На 7 днях WAPE базовых моделей улучшился во всех группах, но доля недопрогноза выросла. На 28 днях очищенные базовые прогнозы ухудшили WAPE на горизонте 28 дней во всех четырёх группах и увеличили недопрогноз. Автоматическое исключение не включаем по умолчанию; флаги полезны для проверки документов. Таблицы LightGBM показывают отдельный эффект очистки признаков при неизменных исходных целях. 2026 — ретроспектива, а семантика возвратов и клиентская концентрация требуют дополнительных данных.
