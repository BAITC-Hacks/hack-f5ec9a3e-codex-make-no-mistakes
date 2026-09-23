# Historical demand experiment / Историческая проверка спроса

Experiment date / Дата: 2026-09-23.

## English

This experiment tests whether Sultan OS's sales-based replenishment idea transfers to the supplied Elektrokomplekt data. It evaluates **forecasts of recorded positive outgoing sales**, not unconstrained customer demand, stock availability, profit, or actual orders. Results and interpretation are in [DEMAND_RESULTS.md](DEMAND_RESULTS.md).

### Reproduce

From the repository root, with Python and `numpy`, `openpyxl` available:

```sh
python scripts/backtest_demand.py
```

The run starts with deterministic arithmetic checks, reads the two original `Динамика продаж*` workbooks using `openpyxl` in read-only mode, and writes CSV/JSON outputs to `artifacts/demand-experiment/`. No source workbook or Sultan OS file is changed. `results.json` records SHA-256 hashes, source dates, imported/excluded row counts, model selection, metrics, and explicitly synthetic scenarios. `predictions.csv` contains each SKU forecast, actual observed sales and origin. `monthly_metrics.csv` and `coverage.csv` expose time variation and excluded cold-start demand.

### Protocol fixed before evaluating results

- Transactional history: January 1, 2025–August 31, 2026, Алматы. Earlier records are sparse and exclusively negative; September 2026 is partial. Forecast targets never include September.
- Accept positive `Расходная накладная` quantities. Quarantine negative, missing, invalid or other-document quantities; do not take absolute values or silently interpret negatives as returns. The target is **gross positive outgoing sales under this explicit assumption**, not net sales. Missing transaction dates contribute zero recorded sales; complete extraction is an assumption, not proof of no latent demand.
- Preserve SKU codes and split each SKU by unit. Evaluate IEK `шт`, `м`, `упак` separately; never pool these quantities. Systeme has `шт` only. No prices were supplied, so no revenue-weighted score or revenue ABC is claimed.
- Forecast origins: the first day of July–December 2025 (six validation origins), then January–August 2026 (eight held-out origins). Forecast 7 and 28 calendar days beginning at each origin. Different horizons overlap; they are evaluated separately. Within a horizon, target windows do not overlap.
- At each origin include SKU/unit series whose first observed positive sale was at least 90 days earlier. Do not require future sales. Include dormant series and zero-sales targets. This excludes new products; coverage is reported separately.
- Every model gets only observations strictly before the origin. Use the same eligible cohort and unchanged targets for every model. Seasonal factors, outlier thresholds and growth estimates must not use future observations or the supplied September coefficient sheets.
- Select the best of the four short-history methods separately by supplier/unit/horizon **using only July–December 2025 WAPE**. Freeze that selection for 2026. `selected_2025` reports its held-out performance. Seasonal methods have insufficient 2025 history and are reported as prespecified comparisons, not validation-selected winners. Do not tune parameters against 2026 results.

### Models

| ID | Exact rule |
| --- | --- |
| `sultan_mean59` | Mean daily recorded sales over the previous 59 calendar days × horizon. Transfers the historical Alliance report's demand estimator; stock subtraction and integer rounding are omitted to isolate forecast error. |
| `mean28` | Previous 28 calendar days' average × horizon. |
| `weekly_ewma` | Eight previous nonoverlapping 7-day totals; newest-to-oldest weights `0.72**week`; normalize weights, divide by 7 and multiply by horizon. Matches Sultan's `decay_072_8w_v2` shadow forecast. |
| `robust_ewma` | Same weighted average, but cap each weekly total at twice the median of positive weekly totals in those eight weeks. Fixed heuristic; it cannot establish whether a sale is a one-off customer project. |
| `seasonal364` | Recorded quantity over the corresponding horizon 364 days earlier (weekday-aligned). Fall back to EWMA until 364 days of global history exist. |
| `seasonal_blend` | 50% EWMA + 50% seasonal364 × growth ratio. Ratio = last 56 days / matching 56 days one year earlier, clipped to 0.5–2; use 1 if the denominator is zero. Fall back to EWMA until 420 days of global history exist. |

Seasonal history can be zero before an individual SKU's first sale; this is a limitation for young assortments even after the 90-day eligibility rule. Weekly caps reduce the influence of some spikes but can also suppress genuine growth or project demand. Actual future sales are **never capped or cleaned to favor a model**.

### Metrics and limits

- WAPE = `sum(abs(forecast − actual)) / sum(actual)`. Lower is better; it can exceed 100%. It is **not an accuracy percentage**. Report by supplier/unit, horizon and cohort.
- Bias = `sum(forecast − actual) / sum(actual)`. Negative indicates underforecasting. Overforecast and underforecast quantities are reported separately as percentages of recorded target sales. They are **not** excess inventory or stockout rates.
- Intermittent = positive sales in fewer than four of the last eight weeks; regular = at least four. This classification uses only pre-origin data.
- A sensitivity subset excludes SKU/unit series with any ambiguous/missing rows during the experiment dates. This is a retrospective data-quality diagnostic, not a deployable cohort rule or replacement headline score.
- WAPE is volume-weighted and can hide weaker low-volume SKU performance. Monthly scores and intermittent/regular splits are included. There are only eight held-out origins; no significance or generalization beyond this period is claimed.
- No historical inventory simulation: monthly opening stock cannot reconstruct daily stockouts, and historical transit schedules, lead times and customer IDs are absent. Forecast performance does not prove procurement savings, service levels or customer-concentrated outlier detection.
- Synthetic scenarios isolate a 1,000-unit one-off sale, known availability loss, and transit/order-multiple arithmetic. Their values are assumptions, not partner outcomes. No supplier order is sent.

### Reuse from Sultan OS

Reuse the separation between demand, target coverage, inventory gap, supplier grouping and a manager-reviewed draft. Adapt the stock equation to subtract **eligible arriving transit** and use confirmed free-stock scope, lead time, buffer, units, minimum quantities and multiples. Preserve unknown stock as unknown. Do not port the historical script's missing-stock-as-zero behavior, revenue ABC without prices, food-retail horizons, or unverified pack assumptions.

## Русский

Проверяем переносимость идеи Sultan OS на реальные данные двух поставщиков. Цель — прогноз **зарегистрированных положительных отгрузок**, а не доказательство истинного спроса, экономии, уровня сервиса или оптимальности заказа.

Запуск: `python scripts/backtest_demand.py`. Нужны Python, `numpy`, `openpyxl`. Исходные XLSX открываются только для чтения. Результаты, хеши источников, контроль импорта и прогнозы по SKU сохраняются в `artifacts/demand-experiment/`.

История — январь 2025–август 2026, Алматы. Сентябрь неполный и исключён. Положительные расходные накладные включены; отрицательные, пустые и прочие движения вынесены отдельно. Отсутствие движения трактуется как отсутствие **записанной продажи**, а не отсутствие скрытого спроса. Разные единицы IEK не суммируются.

На первое число каждого месяца прогнозируем 7 и 28 дней. Июль–декабрь 2025 используется для выбора из четырёх несезонных методов; январь–август 2026 — отложенная проверка без подбора параметров. SKU включается только после 90 дней с первой положительной продажи; фильтра по будущим продажам нет. Все модели оцениваются на одинаковых фактах, будущие продажи не обрезаются.

Сравниваем среднее за 59 дней из Sultan, среднее за 28 дней, недельный EWMA (`0,72`, 8 недель), EWMA с ограничением недельных пиков, соответствующий период 364 дня назад и смесь сезонности с ограниченным ростом. Сезонные варианты используют только прошлые данные; готовые коэффициенты Excel сентября 2026 не попадают в прошлые прогнозы.

WAPE — сумма абсолютных ошибок / сумма продаж; меньше лучше, показатель может быть выше 100% и не равен «точности». Bias — направленная ошибка; отрицательная означает недопрогноз. Отдельно показаны нерегулярные SKU, месяцы, охват зрелого ассортимента и чувствительность к неоднозначным движениям. Только восемь месяцев отложенной проверки: статистическая значимость и переносимость на другие периоды не доказаны.

Синтетические сценарии проверяют влияние разового пика, известного отсутствия товара, транзита и кратности. Это не реальные результаты бизнеса. Без точных stockout-периодов, истории поставок и customer ID нельзя честно измерить восстановление потерянного спроса, концентрацию на клиенте или эффект заказа на остатки.

Из Sultan переносим объяснимую структуру расчёта и проверку менеджером. Добавляем поступающий вовремя транзит, подтверждённый свободный остаток, сроки, единицы и правила поставщика. Не переносим нулевую подстановку неизвестного остатка, ABC по выручке без цен и фиксированные продуктовые горизонты без проверки. Итоги: [DEMAND_RESULTS.md](DEMAND_RESULTS.md).
