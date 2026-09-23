# LightGBM feature ablation (B2)

Owner: @dimashisenov. Run date: 2026-09-23.

## Decision

Keep the baseline as the general default and the original full-feature Tweedie as the main boosting challenger. Removing SKU identity hurts every retrospective group/horizon relative to full features. Development-selected ablations beat the baseline in 3/8 development comparisons and 4/8 retrospective comparisons, but worsen the full-feature model in 6/8 retrospective comparisons (one improvement, one tie). Feature removal is not a general upgrade.

The useful narrow lead is **IEK packs, 7 days, without weekly lags**: WAPE is 51.634 vs baseline 51.879 on development and 66.990 vs 81.969 retrospectively. Its 28-day counterpart loses to the baseline (46.584 vs 42.567), so do not apply the change to every horizon. At 7 days, aggregate bias improves from +13.626% to -2.199%, but underforecast quantity slightly worsens (34.172% to 34.595%). Sparse WAPE remains high at 148.714%. Keep this as a segment-specific candidate for further validation, not an inventory-policy change.

Run ID: `20260923T095929639835Z-lightgbm-ablation-v1`. The registry independently reconciled 80 full-cohort metric groups and matched the existing data/target signature `7cb7a0efc3014f3d2bdf6e77831cd1fc0b2298130b721552fb527c7e96287816`. The tables below are generated; this decision section is editorial interpretation.

## Protocol

Predeclared in [issue #4](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/4#issuecomment-5792732946). Hypothesis: removing feature groups may generalize better on short histories. Keep the v1 Tweedie objective (power 1.5), 150 rounds, 15 leaves, learning rate 0.05, seed, examples and targets unchanged. Compare full (29 features), no SKU (28), no calendar (25), and no individual weekly lags (21). All remaining recency and rolling features stay. Selection among four variants uses total 2025 development WAPE separately per supplier/unit/horizon. The baseline remains a separate decision comparator. 2026 is already-viewed retrospective data. This follow-up was motivated by prior results, and is not independent confirmation or a new holdout.

## WAPE results (%)

Lower is better. Selected means the 2025-selected ablation, not the best retrospective score.

### development_2025

| Supplier / unit / days | Baseline | Full | No SKU | No calendar | No week lags | Selected |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| IEK / м / 7 | 79.690 | 82.687 | 81.962 | 85.525 | 85.270 | tweedie_no_sku |
| IEK / м / 28 | 50.471 | 53.751 | 56.942 | 53.704 | 54.643 | tweedie_no_calendar |
| IEK / упак / 7 | 51.879 | 52.854 | 56.396 | 55.596 | 51.634 | tweedie_no_week_lags |
| IEK / упак / 28 | 41.098 | 41.338 | 51.512 | 41.306 | 40.387 | tweedie_no_week_lags |
| IEK / шт / 7 | 59.210 | 61.458 | 64.139 | 60.638 | 61.245 | tweedie_no_calendar |
| IEK / шт / 28 | 36.057 | 36.060 | 40.458 | 35.834 | 36.247 | tweedie_no_calendar |
| Systeme electric / шт / 7 | 84.782 | 91.044 | 92.527 | 97.172 | 87.563 | tweedie_no_week_lags |
| Systeme electric / шт / 28 | 66.951 | 67.012 | 73.245 | 67.500 | 68.299 | tweedie_full |

### retrospective_2026

| Supplier / unit / days | Baseline | Full | No SKU | No calendar | No week lags | Selected |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| IEK / м / 7 | 92.697 | 85.829 | 89.014 | 92.588 | 84.409 | tweedie_no_sku |
| IEK / м / 28 | 64.977 | 58.803 | 63.210 | 60.265 | 59.455 | tweedie_no_calendar |
| IEK / упак / 7 | 81.969 | 68.716 | 72.048 | 70.031 | 66.990 | tweedie_no_week_lags |
| IEK / упак / 28 | 42.567 | 46.293 | 53.361 | 46.736 | 46.584 | tweedie_no_week_lags |
| IEK / шт / 7 | 71.928 | 71.399 | 73.758 | 72.254 | 71.348 | tweedie_no_calendar |
| IEK / шт / 28 | 40.245 | 40.152 | 43.858 | 41.226 | 40.335 | tweedie_no_calendar |
| Systeme electric / шт / 7 | 73.715 | 73.505 | 75.862 | 81.135 | 73.844 | tweedie_no_week_lags |
| Systeme electric / шт / 28 | 42.760 | 42.430 | 50.259 | 43.388 | 40.104 | tweedie_full |

## Retrospective bias and sparse errors

Negative bias means aggregate underprediction; it can hide offsetting errors. Underforecast is not a stockout rate.

| Supplier / unit / days | Baseline bias | Selected bias | Baseline underforecast | Selected underforecast | Baseline sparse WAPE | Selected sparse WAPE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / м / 7 | -15.918 | -19.290 | 54.308 | 54.152 | 122.671 | 125.200 |
| IEK / м / 28 | -22.722 | -13.941 | 43.849 | 37.103 | 112.888 | 109.994 |
| IEK / упак / 7 | 13.626 | -2.199 | 34.172 | 34.595 | 201.776 | 148.714 |
| IEK / упак / 28 | -12.258 | 1.467 | 27.413 | 22.558 | 122.556 | 96.683 |
| IEK / шт / 7 | 5.755 | 10.401 | 33.087 | 30.927 | 148.358 | 158.047 |
| IEK / шт / 28 | -10.436 | -5.576 | 25.341 | 23.401 | 119.418 | 118.494 |
| Systeme electric / шт / 7 | -14.736 | -9.079 | 44.226 | 41.461 | 146.917 | 120.975 |
| Systeme electric / шт / 28 | -25.285 | -2.192 | 34.023 | 22.311 | 101.275 | 107.255 |

## Verification and reproduction

Full-feature control exactly reproduces all 65,754 v1 Tweedie predictions and actuals. All 448 training label cutoffs passed; every selected variant matches the development-only rule. Runtime: 223.61 seconds total, 174.87 seconds fitting/predicting. Environment is pinned in experiments/requirements.txt; detailed environment and hashes are in the run summary.

```sh
experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py --ablation
python scripts/summarize_lightgbm_ablation.py
```

Run the baseline and v1 LightGBM first if their local artifacts are absent; see [workflow](../experiments/README.md). Raw predictions, monthly metrics, feature importance and training cutoffs are in artifacts/lightgbm-ablation. Register this directory to freeze the run. Published summaries are linked from [the comparison table](../experiments/INDEX.md); large CSV archives remain local. No production model or purchasing policy is changed.
