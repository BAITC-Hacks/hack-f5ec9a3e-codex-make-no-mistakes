# Track C: Croston-SBA and TSB / Эксперимент с редким спросом

Claimed for @dimashisenov in [issue #4](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/4#issuecomment-5792260151).

## Reproduce / Повторить

From the repository root, using Python with NumPy and openpyxl:

```sh
python scripts/backtest_demand.py
python scripts/backtest_intermittent.py
```

The first command generates the shared baseline artifacts if they are not already present. The second reads the original supplier workbooks again, imports the shared loader/scoring helpers, reconstructs the targets and four short-history baselines, and checks them against every saved baseline key/value before writing separate outputs to `artifacts/intermittent-experiment/`. It does not change the source workbooks or baseline files.

## Frozen protocol

This is the [shared historical-sales protocol](DEMAND_EXPERIMENT.md): positive outgoing sales, January 2025–August 2026, Алматы; distinct supplier/SKU/unit series; 90-day age eligibility; forecast origins on the first of July–December 2025 and January–August 2026; separate 7/28-day targets. The loader verifies the workbook hashes against the baseline run and asserts warehouse identity.

All periods without a recorded positive sale are zeros in the recorded-sales target. They do not prove zero latent demand or product availability. Long zero runs can therefore reflect stockouts as well as inactivity. This is particularly consequential for TSB's probability decay.

Development uses the six 2025 origins. Select one parameter setting per family, supplier/unit and horizon by total development WAPE. The sparse/regular classification is used for reporting, **not** separate parameter tuning. Freeze these choices for 2026; refitting states using observations available before each new origin is allowed. Since the 2026 baseline results were already inspected before this experiment, call it a retrospective comparison, not an untouched final test. No 2026-guided parameter adjustments are part of v1.

## Models and initialization

The local NumPy implementation uses daily state updates, with no new dependency. It follows the standard smoothing recurrences; method references are the [StatsForecast model source](https://github.com/Nixtla/statsforecast/blob/main/python/statsforecast/models.py) and [intermittent-data tutorial](https://nixtlaverse.nixtla.io/statsforecast/docs/tutorials/intermittentdata.html). It is a local implementation, not a run of the StatsForecast package.

- **Croston-SBA:** smooth positive sale size and inter-sale interval using the same alpha. First size equals first positive quantity; first interval is its 1-based day since the fixed history start. At later positive observations update both states. Trailing zero observations leave the forecast unchanged. Daily rate is `(1 - alpha/2) * smoothed_size / smoothed_interval`. Grid: alpha 0.05, 0.1, 0.2. The familiar 0.95 correction is the alpha=0.1 case.
- **TSB:** smooth positive sale size with alpha-size and daily sale-occurrence indicator with alpha-probability. Size initializes at first positive sale; probability initializes from the first history day's 0/1 indicator and updates every subsequent day. Grid: alpha-size 0.05, 0.1, 0.2 crossed with alpha-probability 0.01, 0.05, 0.1, 0.2. Daily rate is smoothed size times smoothed probability.
- Both forecast a constant expected daily rate across the future horizon, summed over 7 or 28 days. Do not feed assumed future zeros into the states. All-zero histories forecast zero. Leading zeros are retained; this initialization is an explicit modeling choice rather than evidence of historical assortment availability.

Neither model explicitly learns seasonality, growth drivers, customer identity, or lost demand. They are candidate components, not a complete fulfillment of the hackathon brief. No rounding or inventory arithmetic is applied to forecast evaluation.

## Artifacts and checks

- `results.json`: source hashes, script hashes, model grid, frozen selections, runtime/environment and metrics.
- `predictions.csv`: common long format for the development-selected baseline, SBA and TSB models.
- `candidate_predictions.csv`: all 15 candidate settings plus baselines and selected forecasts, with segment labels.
- `grid_development.csv`: 2025 scores for every candidate.
- `metrics.csv`: WAPE, bias, under/overforecast ratios and MAE by period, supplier/unit, horizon and segment.
- `monthly_metrics.csv`: scores at individual origins.

Embedded checks cover hand-calculated irregular sequences, all-zero and constant histories, decay through trailing zeros, batch independence and isolation from future values. Runtime includes all 15 settings and every origin; per-supplier model timing is separated from workbook reading. The output records the actual Python environment rather than assuming the planned application runtime.

## Русский

Берём Track C: Croston-SBA и TSB. Повторяем исходную подготовку данных и проверяем совпадение всех ключей, фактов и базовых прогнозов с существующим экспериментом. Результаты сохраняются отдельно; XLSX и базовые результаты не меняются.

Параметры выбираются только на июле–декабре 2025 по WAPE для каждой группы поставщик/единица/горизонт. Период январь–август 2026 — ретроспективное сравнение: его базовые результаты уже известны. Прогнозы строятся исключительно по истории до даты расчёта. Обе модели проверяются на всех допустимых SKU, отдельно показываем редкий и регулярный спрос.

Croston-SBA сохраняет оценку при длинном отсутствии продаж; TSB постепенно уменьшает вероятность продажи. Но отсутствие записей может означать дефицит, а не исчезновение спроса. Поэтому уменьшение прогноза не доказывает пользу для запасов. Выбираем направление по ошибке, смещению и недопрогнозу; экономия и уровень сервиса здесь не измеряются.
