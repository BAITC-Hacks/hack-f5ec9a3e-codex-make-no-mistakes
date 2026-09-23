# Track B: LightGBM experiment and results / Эксперимент LightGBM

Run date: 2026-09-23. Owner: @dimashisenov, local Codex run. Run ID: `20260923T093912139814Z-lightgbm-v1`.

**Decision: keep Tweedie LightGBM as a promising challenger, not an automatic replacement.** It beats the baseline in 7 of 8 supplier/unit/horizon comparisons in retrospective 2026, but does not beat the baseline in any of the corresponding 2025 development groups. There was no tuning after inspecting 2026. The retrospective gains motivate further validation, not a claim of proven purchasing savings.

## Reproduce

Use the pinned isolated environment in [experiments/README.md](../experiments/README.md), then:

```sh
experiments/.venv/Scripts/python.exe scripts/backtest_demand.py
experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py
```

The first command is needed only if shared baseline outputs are absent. Results go to `artifacts/lightgbm-experiment/`. An archived copy is in [the run manifest](../experiments/runs/20260923T093912139814Z-lightgbm-v1/manifest.json). Registration, comparisons and sharing rules are documented in the experiment workflow.

## Fixed method

Reuse the same sources, recorded-positive-sales target, 90-day eligibility, units, 14 forecast origins and separate 7/28-day horizons as [the shared benchmark](DEMAND_EXPERIMENT.md). Both supplier workbook hashes and warehouse identity are verified; all 65,754 evaluation keys, actual quantities and segment labels match the existing benchmark.

Fit a separate model per supplier/unit/horizon at each origin. Pool SKU histories within that group. The target is total recorded sales over the next horizon, so inference does not require recursive future-sales features.

Training examples start at day 90 of the fixed history, sampled every seven days plus the common month-start origins. Include only examples with a complete target ending before or at the current forecast origin (exclusive target end). Overlapping training targets are allowed; they are not independent observations. `training.csv` records the last label end and training row count for every fit. Weekly sampling is a speed/data-volume choice, not a proven optimal scheme.

The 29 features use history strictly before each example's origin: categorical SKU identity, age, days since last sale, month sine/cosine, weekday and month-day, recent means and positive-day fractions for 7/14/28/56/84 days, eight lagged weekly totals, 56-day maximum/standard deviation/mean positive size, and a recent-to-previous-28-day ratio. No future prices, availability, customer IDs or September category/growth/seasonal coefficients are used. Category features are omitted because their historical validity is not established. Neither model explicitly recovers lost demand.

Two prespecified candidates:

- `lgbm_l2`: squared-error regression; negative predictions clipped to zero.
- `lgbm_tweedie`: Tweedie objective, variance power 1.5; same nonnegative output guard.

Common settings: 150 boosting rounds, learning rate 0.05, 15 leaves, minimum 50 training rows per leaf, L2 regularization 1, max-bin 63, two CPU threads, deterministic/column-wise training, seed 20260923. No early stopping, ensemble, new preprocessing or hyperparameter sweep. LightGBM's [official parameter reference](https://lightgbm.readthedocs.io/en/stable/Parameters.html) documents the objectives and controls.

Choose the objective separately by supplier/unit/horizon using total WAPE on the six 2025 origins. **Tweedie wins against L2 in all eight groups.** The `lgbm_selected` output is consequently identical to Tweedie for this run. The baseline was selected from its own four short-history candidates using the same development period.

## Results: 28-day WAPE (%)

Lower is better; WAPE is not an accuracy percentage. Different physical units are never pooled.

| Supplier / unit | 2025 baseline | 2025 L2 | 2025 Tweedie | 2026 baseline | 2026 L2 | 2026 Tweedie |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / pieces | 36.057 | 54.597 | 36.060 | 40.245 | 42.316 | 40.152 |
| IEK / meters | 50.471 | 60.140 | 53.751 | 64.977 | 62.084 | 58.803 |
| IEK / packs | 41.098 | 52.374 | 41.338 | 42.567 | 56.034 | 46.293 |
| Systeme / pieces | 66.951 | 88.222 | 67.012 | 42.760 | 43.621 | 42.430 |

Tweedie improves retrospective WAPE by 6.174 percentage points for IEK meters and wins in 6/8 monthly origins there. Improvements for IEK pieces (0.093 pp, 5/8 origins) and Systeme (0.330 pp, 5/8) are small. It loses for IEK packs by 3.726 pp and wins in only 3/8 origins. There is no significance claim.

## Seven-day WAPE (%)

| Supplier / unit | 2025 baseline | 2025 Tweedie | 2026 baseline | 2026 Tweedie |
| --- | ---: | ---: | ---: | ---: |
| IEK / pieces | 59.210 | 61.458 | 71.928 | 71.399 |
| IEK / meters | 79.690 | 82.687 | 92.697 | 85.829 |
| IEK / packs | 51.879 | 52.854 | 81.969 | 68.716 |
| Systeme / pieces | 84.782 | 91.044 | 73.715 | 73.505 |

The comparison samples only the first seven days of each month, not every possible operational week. The baseline wins development WAPE throughout, despite these retrospective improvements.

## Bias, sparse items and limits

| Supplier / unit | 28d baseline bias % | Tweedie bias % | Baseline underforecast % | Tweedie underforecast % | Baseline overforecast % | Tweedie overforecast % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IEK / pieces | -10.436 | -2.107 | 25.341 | 21.129 | 14.905 | 19.023 |
| IEK / meters | -22.722 | -10.908 | 43.849 | 34.856 | 21.128 | 23.947 |
| IEK / packs | -12.258 | -0.157 | 27.413 | 23.225 | 15.154 | 23.068 |
| Systeme / pieces | -25.285 | -2.192 | 34.023 | 22.311 | 8.737 | 20.119 |

The lower 28-day underforecast quantity is accompanied by higher overforecast quantity. These ratios are forecast errors, not stockout/excess-stock rates. Near-zero total bias can conceal errors that cancel across products.

On sparse 28-day targets, baseline → Tweedie WAPE is: IEK pieces 119.418 → 121.744; IEK meters 112.888 → 111.773; IEK packs 122.556 → 97.488; Systeme 101.275 → 107.255. So the full-cohort gain does not imply improvement on every demand segment. All other segment/MAE/monthly scores remain in the artifacts.

Recorded sales are constrained by unknown historical availability. Missing customers and stockout intervals still prevent factual recovery of lost demand or customer-concentrated order detection. Small early training sets, overlapping labels, short seasonal history and the limited candidate set constrain interpretation. The larger amount of pre-origin training data in 2026 may contribute to the different relative performance, but that explanation has not been isolated experimentally.

## Execution and verification

- 224 fitted models: four supplier/unit groups × two horizons × fourteen origins × two objectives.
- 65,754 common target rows; 263,016 long-format prediction rows including baseline, both objectives and selected-objective alias.
- Total run: **218.61 seconds**; fit/predict work: **163.92 seconds**, two CPU threads.
- Windows, Python 3.10.4, LightGBM 4.6.0, NumPy 1.23.5, openpyxl 3.1.2. Dependencies are isolated under `experiments/.venv`; the production environment is unchanged by this experiment.
- Embedded feature-value, future-isolation and label-cutoff checks passed. Every recorded training label cutoff is at or before its forecast origin. All predictions are finite and nonnegative.
- Registration independently reconciled **32** full-cohort metric groups for the two distinct objectives from exported predictions; both objectives cover the exact shared target set. Archived script hashes match the run's recorded code hashes.

Artifacts: `results.json`, `metrics.csv`, `monthly_metrics.csv`, `predictions.csv`, `candidate_predictions.csv`, `training.csv`, and final-origin `feature_importance.csv`. Feature gain is a model diagnostic, not a causal explanation of replenishment quantities.

## Русский: вывод

Проверили два варианта LightGBM: squared error и Tweedie. На 2025 Tweedie лучше второго варианта во всех восьми группах, но базовый метод всё ещё лучше обоих. На ретроспективном 2026 Tweedie выигрывает у baseline в 7 из 8 сочетаний группа/горизонт. Наиболее заметное улучшение на 28 дней — метры IEK: WAPE 64,977% → 58,803%; по упаковкам IEK результат хуже.

Tweedie оставляем кандидатом для следующей проверки, а не объявляем новым победителем по уже просмотренному периоду. Недопрогноз уменьшается ценой большего перепрогноза. По редким SKU улучшение неоднородно. Экономия и сервис не измерялись.

Запуск занял 3 минуты 39 секунд; обучено 224 небольших модели. Параметры, исходные хеши, код, метрики и прогнозы сохранены отдельным зарегистрированным запуском. Общая таблица сравнения — [experiments/INDEX.md](../experiments/INDEX.md); обсуждение результатов продолжается в issue #4.
