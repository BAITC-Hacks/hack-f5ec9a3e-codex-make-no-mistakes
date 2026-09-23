# Combined forecast results / Результаты прогноза с совместными признаками

[Fixed protocol](COMBINED_FORECAST_EXPERIMENT.md) · [All registered experiments](../experiments/INDEX.md).

## Answer

Adding cleaned history and bulk-order signals to the raw model improves WAPE versus raw-only Tweedie in **3/8 development groups** and **2/8 retrospective groups**. Each group is a supplier/unit/horizon combination; these are not independent statistical trials.

The combined model is chosen in **0/8 groups** when compared with the existing baseline and raw Tweedie using 2025 only. That frozen policy improves on the baseline in **0/8** 2026 groups. All regressions are shown; no 2026 result changes the choices.

Lower forecast error is not evidence of reduced stockouts or inventory savings. Inspect bias and underforecasting before using a candidate for ordering. Keep any improvement scoped to its supplier, unit and horizon; do not replace every forecast with a single winner.

## What changed and what was checked

The combined model has 59 features: all 29 raw features, 17 cleaned-history features and 13 bulk-order frequency/size/recency signals. The 150-round Tweedie settings, cleaning policy, sources, training labels and evaluation targets are unchanged. Raw sales remain the target.

The raw control exactly reproduces all 65,754 earlier predictions, actual quantities, baseline predictions and segment labels. All 224 fits use labels observed by their forecast date. Feature checks preserve the raw block, verify hand-calculated bulk signals and reject future orders. Cached versus prefix-only cleaning and bulk signals match at training/test boundaries.

Total runtime: 416.8s; model fit/predict: 119.0s. 2025 development: July–December; 2026 retrospective: January–August. All targets are gross positive outgoing sales in Алматы, with at least 90 days since the first observed sale. Units are scored separately. The 2026 period was already seen in earlier experiments and is not an untouched test.

## 7-day WAPE (%), development_2025

Lower is better.

| Supplier / unit | Baseline | Raw Tweedie | Clean-only | Combined | Combined−raw (pp) |
| --- | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 79.690 | 82.687 | 84.719 | 82.026 | -0.661 |
| IEK / упак | 51.879 | 52.854 | 50.322 | 53.909 | +1.055 |
| IEK / шт | 59.210 | 61.458 | 60.945 | 60.782 | -0.676 |
| Systeme electric / шт | 84.782 | 91.044 | 95.056 | 94.097 | +3.053 |

## 28-day WAPE (%), development_2025

Lower is better.

| Supplier / unit | Baseline | Raw Tweedie | Clean-only | Combined | Combined−raw (pp) |
| --- | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 50.471 | 53.751 | 54.091 | 53.348 | -0.403 |
| IEK / упак | 41.098 | 41.338 | 40.981 | 43.248 | +1.910 |
| IEK / шт | 36.057 | 36.060 | 36.044 | 36.422 | +0.362 |
| Systeme electric / шт | 66.951 | 67.012 | 72.135 | 73.181 | +6.169 |

## 7-day WAPE (%), retrospective_2026

Lower is better.

| Supplier / unit | Baseline | Raw Tweedie | Clean-only | Combined | Combined−raw (pp) |
| --- | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 92.697 | 85.829 | 87.119 | 87.939 | +2.110 |
| IEK / упак | 81.969 | 68.716 | 69.683 | 71.905 | +3.189 |
| IEK / шт | 71.928 | 71.399 | 70.473 | 70.790 | -0.609 |
| Systeme electric / шт | 73.715 | 73.505 | 77.906 | 74.053 | +0.548 |

## 28-day WAPE (%), retrospective_2026

Lower is better.

| Supplier / unit | Baseline | Raw Tweedie | Clean-only | Combined | Combined−raw (pp) |
| --- | ---: | ---: | ---: | ---: | ---: |
| IEK / м | 64.977 | 58.803 | 59.028 | 61.766 | +2.963 |
| IEK / упак | 42.567 | 46.293 | 44.515 | 47.871 | +1.578 |
| IEK / шт | 40.245 | 40.152 | 40.207 | 40.054 | -0.098 |
| Systeme electric / шт | 42.760 | 42.430 | 42.825 | 43.067 | +0.637 |

## Frozen 2025-only choice

Candidates: existing baseline selection, raw Tweedie, combined Tweedie. Other historical experiments are shown in the registry, not silently added to this selection.

| Supplier / unit | Days | Choice | 2026 WAPE | Δ vs baseline (pp) | Bias % | Underforecast % |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| IEK / м | 7 | baseline_selected | 92.697 | +0.000 | -15.918 | 54.308 |
| IEK / м | 28 | baseline_selected | 64.977 | +0.000 | -22.722 | 43.849 |
| IEK / упак | 7 | baseline_selected | 81.969 | +0.000 | 13.626 | 34.172 |
| IEK / упак | 28 | baseline_selected | 42.567 | +0.000 | -12.258 | 27.413 |
| IEK / шт | 7 | baseline_selected | 71.928 | +0.000 | 5.755 | 33.087 |
| IEK / шт | 28 | baseline_selected | 40.245 | +0.000 | -10.436 | 25.341 |
| Systeme electric / шт | 7 | baseline_selected | 73.715 | +0.000 | -14.736 | 44.226 |
| Systeme electric / шт | 28 | baseline_selected | 42.760 | +0.000 | -25.285 | 34.023 |

## Combined-model failure cases and stability

All changes below compare combined features with raw-only Tweedie in 2026. Positive WAPE/underforecast deltas are worse. Negative bias indicates underforecasting.

| Supplier / unit | Days | Regular WAPE Δ | Intermittent WAPE Δ | Bias raw→combined | Underforecast Δ (pp) | Better months / 8 |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| IEK / м | 7 | +2.287 | +0.911 | -22.728 → -26.181 | +2.782 | 4 / 8 |
| IEK / м | 28 | +3.278 | -0.988 | -10.908 → -14.278 | +3.166 | 1 / 8 |
| IEK / упак | 7 | +3.344 | -1.756 | -2.155 → -1.802 | +1.417 | 1 / 8 |
| IEK / упак | 28 | +1.559 | +1.986 | -0.157 → 1.160 | +0.131 | 3 / 8 |
| IEK / шт | 7 | -0.652 | +0.156 | 0.902 → 1.335 | -0.521 | 5 / 8 |
| IEK / шт | 28 | -0.104 | +0.015 | -2.107 → -2.335 | +0.065 | 5 / 8 |
| Systeme electric / шт | 7 | +0.672 | -2.330 | -8.841 → -6.120 | -1.087 | 4 / 8 |
| Systeme electric / шт | 28 | +0.576 | +2.320 | -2.192 → -2.773 | +0.609 | 3 / 8 |

## Evidence and reproduction

Run `experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py --combined`, register the run, then regenerate this readout with `experiments/.venv/Scripts/python.exe scripts/summarize_combined_forecast.py`.

Registered run: [20260923T104442154821Z-lightgbm-combined-v1](../experiments/runs/20260923T104442154821Z-lightgbm-combined-v1/manifest.json). The registry independently verified 80 full-cohort metric groups from predictions. Source/code hashes, settings and compact metrics are in the snapshot; large prediction archives remain local and Git-ignored.

Working outputs: `artifacts/lightgbm-combined/` contains predictions, monthly/segment metrics, training cutoffs, feature importance, selected models and runtime provenance. The clean-only comparison requires the preceding `artifacts/lightgbm-cleaning` run.

## Русский

Проверили совместные признаки: исходные продажи, очищенная история и частота/размер крупных заказов. Будущие продажи не очищались; исходный контроль воспроизведён точно. Выбор модели отдельно для поставщика, единицы и горизонта — только по 2025. Таблицы показывают все улучшения и ухудшения 2026, смещение, недопрогноз и помесячную устойчивость. Это ретроспективная проверка прогноза, не доказательство экономии запасов.
