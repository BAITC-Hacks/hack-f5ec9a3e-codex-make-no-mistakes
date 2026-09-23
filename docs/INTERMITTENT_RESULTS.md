# Track C results: Croston-SBA and TSB / Результаты Track C

Run date: 2026-09-23. Owner: @dimashisenov, local Codex run. [Protocol and reproduction](INTERMITTENT_EXPERIMENT.md).

## Decision / Решение

**Keep the existing baseline as the default. Keep TSB as a candidate for a less negatively biased 28-day IEK forecast; do not adopt Croston-SBA globally.** This experiment does not establish a universally better model or an optimal purchasing policy.

TSB improves 28-day WAPE only for IEK meters versus the development-selected baseline, by 0.228 percentage points. It loses on the other three supplier/unit groups and on all four 7-day comparisons. Its main useful signal is a different underforecast/overforecast balance. Croston-SBA preserves stale demand after sales stop, causing severe overprediction for some products.

These findings apply to the specified daily initialization, small fixed parameter grid and recorded-sales target. They do not reject every possible Croston/TSB implementation or configuration. The 2026 period is a retrospective comparison: its baseline results were already known. No parameters were changed after seeing these results.

## Main comparison: 28 days, January–August 2026

WAPE percentages; lower is better. WAPE is not an accuracy percentage. The baseline here is capped EWMA, selected using 2025 only for all four groups. Each candidate family's parameters were also selected using 2025 only.

| Supplier / unit | Baseline | Croston-SBA | TSB | TSB beats baseline, monthly origins |
| --- | ---: | ---: | ---: | ---: |
| IEK / pieces (шт) | 40.245 | 74.565 | 41.260 | 2 / 8 |
| IEK / meters (м) | 64.977 | 69.748 | 64.749 | 5 / 8 |
| IEK / packs (упак) | 42.567 | 49.783 | 50.648 | 1 / 8 |
| Systeme / pieces (шт) | 42.760 | 43.426 | 45.176 | 3 / 8 |

## Bias and underforecast trade-off, 28 days

Bias is signed forecast error divided by actual sales; negative means aggregate underprediction. Underforecast ratio sums positive actual-minus-forecast gaps across SKU targets and divides by actual sales. It is **not** a stockout rate. Near-zero bias can still hide large offsetting errors.

| Supplier / unit | Baseline bias % | TSB bias % | Baseline underforecast % | TSB underforecast % | Baseline overforecast % | TSB overforecast % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / pieces | -10.436 | +2.021 | 25.341 | 19.620 | 14.905 | 21.640 |
| IEK / meters | -22.722 | +0.122 | 43.849 | 32.314 | 21.128 | 32.436 |
| IEK / packs | -12.258 | +6.649 | 27.413 | 21.999 | 15.154 | 28.648 |
| Systeme / pieces | -25.285 | +1.837 | 34.023 | 21.670 | 8.737 | 23.506 |

TSB reduces underforecast quantity but increases overforecast quantity in every group. Without agreed shortage/holding costs and historical availability, this cannot be called a business improvement. The baseline's spike cap also needs manager-visible handling; low WAPE alone does not justify it.

## Sparse items and a concrete failure

Sparse means positive sales in fewer than four of the previous eight weeks, determined separately at each origin. Parameters were selected on the full development cohort, not optimized for this subset.

| Supplier / unit | Sparse baseline WAPE % | Sparse SBA WAPE % | Sparse TSB WAPE % |
| --- | ---: | ---: | ---: |
| IEK / pieces | 119.418 | 867.086 | 120.008 |
| IEK / meters | 112.888 | 139.552 | 109.769 |
| IEK / packs | 122.556 | 143.504 | 104.771 |
| Systeme / pieces | 101.275 | 145.544 | 113.919 |

IEK SKU `130200305_` has zero recorded actual sales across the eight evaluated 28-day target windows, but the selected SBA forecasts sum to **286,650 pieces**. This one SKU dominates the SBA overforecast problem. Standard SBA does not decay its rate through trailing zero observations. Do not silently remove this failure from scoring or infer from it that the SKU was discontinued: availability is unknown. A future experiment can test an explicitly defined lifecycle/bulk-event rule using development data.

Every sparse WAPE in this table is above 100%. An always-zero forecast would score 100% on these nonzero-total targets; that is a metric diagnostic, not a recommendation to stop replenishing sparse products.

## Seven-day comparison

| Supplier / unit | Baseline WAPE % | SBA WAPE % | TSB WAPE % |
| --- | ---: | ---: | ---: |
| IEK / pieces | 71.928 | 116.267 | 76.928 |
| IEK / meters | 92.697 | 105.159 | 103.253 |
| IEK / packs | 81.969 | 82.629 | 82.138 |
| Systeme / pieces | 73.715 | 85.851 | 84.977 |

The 7-day pack baseline is the 59-day mean; the other 7-day groups selected capped EWMA. These are first-week-of-month targets, not all rolling weeks.

## Development scores and frozen settings

| Supplier / unit | 2025 28d baseline WAPE % | SBA WAPE % | TSB WAPE % | SBA alpha | TSB alpha-size / alpha-probability |
| --- | ---: | ---: | ---: | ---: | --- |
| IEK / pieces | 36.057 | 49.183 | 36.033 | 0.05 | 0.05 / 0.05 |
| IEK / meters | 50.471 | 52.580 | 49.139 | 0.10 | 0.05 / 0.05 |
| IEK / packs | 41.098 | 43.021 | 40.441 | 0.05 | 0.05 / 0.01 |
| Systeme / pieces | 66.951 | 77.047 | 71.015 | 0.05 | 0.05 / 0.20 |

Seven-day settings match these except IEK meters uses SBA alpha 0.05 and TSB 0.05 / 0.01. Full 2025 candidate scores are in `grid_development.csv`. Selection uses total absolute errors divided by total actual sales across development origins, not the mean of monthly WAPEs. No random seed is needed: the calculation is deterministic.

## Evidence and validation

- Read 248,915 movement rows; included 238,402 positive outgoing rows in the agreed history.
- Reconstructed **65,754** SKU/unit/origin/horizon keys, including **20,098** retrospective 28-day targets, exactly matching the baseline cohort and target values.
- Matched all four recomputed short-history baseline predictions to the existing CSV, for every key.
- Exported **197,262** unique, finite, nonnegative predictions in the shared long format (three selected model families per key).
- An independent read of the exported predictions reconciled WAPE, bias, underforecast ratio and MAE for **48** full-cohort metric groups (two phases × four unit groups × two horizons × three families).
- Embedded hand-calculated recurrence and edge-case checks passed. This is a local NumPy implementation; equivalence to an installed StatsForecast package was not tested.
- Total measured runtime before writing final summary: **59.96 seconds**. Reading workbooks took **35.97 seconds**; fitting/updating all 15 candidate settings and capturing all forecast origins took **0.19 seconds** in total. Remaining time includes baselines, reconciliation, metrics and CSV writing. This is one local run, not a performance benchmark across machines.
- Actual runtime: Windows, Python **3.10.4**, NumPy **1.23.5**, openpyxl **3.1.2**, Intel64 Family 6 Model 158 Stepping 10. The application plan's Python 3.12 environment was not used for this experiment.

Machine-readable evidence:

- [Run manifest, hashes, selections, metrics](../artifacts/intermittent-experiment/results.json)
- [Common-format predictions](../artifacts/intermittent-experiment/predictions.csv)
- [All candidate predictions](../artifacts/intermittent-experiment/candidate_predictions.csv)
- [Metrics including MAE and regular/sparse splits](../artifacts/intermittent-experiment/metrics.csv)
- [Development grid](../artifacts/intermittent-experiment/grid_development.csv)
- [Monthly scores](../artifacts/intermittent-experiment/monthly_metrics.csv)

## Русский: вывод

**Базовый метод пока оставляем. TSB сохраняем как кандидат для 28-дневного прогноза IEK с меньшим отрицательным смещением; Croston-SBA не внедряем для всего ассортимента.** TSB немного улучшил WAPE только по метрам IEK, проиграл по остальным трём группам и во всех четырёх сравнениях на 7 дней. При этом недопрогноз уменьшается ценой большего перепрогноза.

Показательная ошибка SBA: по `130200305_` суммарный прогноз в восьми окнах составил 286 650 шт. при нулевых зарегистрированных продажах. Метод сохраняет старую оценку при отсутствии новых продаж. Это не доказывает снятие товара с продажи: наличие неизвестно.

Проверены одинаковые 65 754 ключа и базовые прогнозы; экспортированы 197 262 прогноза трёх выбранных моделей, независимо сверены 48 групп метрик. Выполнение заняло около минуты. Модели и параметры выбраны по 2025; 2026 — ретроспективное сравнение, без дополнительной настройки после просмотра. Экономия, stockout и уровень сервиса не измерялись. Следующий независимый кандидат — LightGBM в Track B; сравнивать его нужно по тому же протоколу.
