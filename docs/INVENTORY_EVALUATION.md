# Forecast-first methodology v2 / Методология v2

This is the active calculation and evaluation contract. It replaces the unimplemented v1
application assumptions; saved v1 reports and registered 7/28-day experiments remain unchanged.
See [D12](DECISIONS.md#d12--forecast-first-core--основной-расчёт-2026-09-23).

## Русский

Основной вход — `replenishment.calculation.calculate(batch) -> results`, `contract_version: "2"`.
Чистый расчёт принимает закреплённые месячные ряды и доказательства, возвращает три датированных
прогноза и черновик для каждого ряда. SQL, HTTP и LLM находятся за пределами арифметики.

Идентичность ряда: поставщик + точный SKU + охват источника + единица. Главная история — отдельные
месячные книги продаж. Движения Алматы и встроенные продажи Systeme служат отдельной сверкой;
они не добавляются к месячным продажам. Конфликты не усредняются, повторные сводки не удваиваются.
Пустая ячейка, ноль, Excel error и формула без кеша различаются. Пропущенный месяц не становится нулём.
Итоги, будущие формулы, незавершённые месяцы и отрицательные продажи не входят в обучение.

Для среза принято **22 сентября 2026**. История заканчивается августом, сентябрь прогнозируется
внутренне; три публикуемые цели — **октябрь, ноябрь, декабрь 2026**. Единица может быть неизвестна:
прогноз тогда выражается в единицах количества источника. Это не даёт основания объединять
физические объёмы либо пересчитывать единицу закупки. Межисточниковый вывод единицы маркируется.

Кандидаты: среднее трёх последних валидных наблюдений; EWMA с `alpha=0.3`; календарная сезонность,
сглаженный десезонализированный уровень и затухающий тренд (`alpha=0.3`, damping `0.8`). Разреженная
сезонность стягивается к сопоставимой подтверждённой категории либо нормированному паттерну
поставщика. Короткая история использует уровень с ограничением; отсутствие истории даёт
`insufficient_data`, не нулевой спрос. Исторические коэффициенты Excel не применяются повторно.

Аномалии выявляются по остаткам после учёта уровня/сезонности/тренда и по сумме документа/SKU,
а не отдельной строке накладной. Изолированный избыток — кандидат корректировки; устойчивый рост
сохраняется. Сырые и скорректированные варианты сравниваются на одинаковых исходных фактах.
Вычитание транзакционного выброса из месячного ряда допустимо только при совместимом охвате
и сверке месячных сумм. Документ не является customer ID.

Обучение/предобработка повторяются независимо на каждой дате. Development origins: июнь–сентябрь
2025; retrospective comparison: январь–май 2026. Для каждой даты обучение заканчивается перед
месяцем планирования, затем мост и три цели. Все кандидаты используют одинаковые допустимые
ключи; пропуски, исключения и нулевая обучающая шкала учитываются отдельно. Данные 2026 уже
изучались и не называются unseen.

## English

The V2 batch contains `planning_date`, `source_selection`, `parameters`, and `series`. Each series
has an explicit scope, nullable unit, source-linked monthly history, selected attributes, inventory,
shipments, quantity rules and assumptions. Results separate forecast `status` from draft `state`.
Quantities serialize as finite Decimal strings. The current-month bridge is internal; exactly three
following calendar months are published.

The primary error is absolute forecast error divided by the series' mean observed training quantity,
averaged equally across SKUs and horizons and then equally across suppliers. Zero-scale series are
reported separately. Diagnostics include normalized bias, underforecast, per-horizon results, coverage,
runtime and LLM accounting. Physical WAPE is reported only within comparable known unit cohorts;
unknown quantity units never become a pooled physical total. Historical targets are never adjusted.

An expensive challenger must improve primary development error by at least **3%**, have no worse
absolute normalized bias, no supplier/horizon degradation over **5%**, and no coverage loss. Freeze
selection before the 2026 retrospective comparison. These are engineering acceptance thresholds,
not statistical-significance claims. LightGBM uses the existing fixed Tweedie research settings,
supplier-specific models, historical-scale-normalized targets, lag/rolling/missingness/calendar
features, and no missing targets converted to zero. Its dependencies stay in the research environment
unless promotion is supported by this evaluation.

A small deterministic LLM historical pilot sees only training history and known context, with no
future actuals or tools. It cannot establish catalogue-wide promotion. Paid stages require explicitly
configured model IDs and known prices. Cache exact input/schema/prompt/model, reserve worst-case
request cost before each dispatch/retry/escalation, and cap the run at **$1**. Refusal, incomplete or
invalid output, unknown pricing and exhausted budget are recorded failures/limitations; deterministic
forecasts survive. Mappings require local cell/type/period/reconciliation validation after schema checks.

Run records persist source selections, versions, parameters, quality and LLM accounting. Per-series
input snapshots, forecasts and draft lines commit atomically. Identical inputs and implementation
versions reuse completed runs; `--rerun` explicitly creates another. Failed transactions do not expose
completed partial results. The [backend instructions](../backend/README.md) describe import/run/export;
[API documentation](../backend/API.md) describes paginated reads.

## Evidence limits / Ограничения

- Recorded sales are not unconstrained demand. Monthly stock snapshots cannot establish exact
  stockout durations; no numerical lost-demand uplift follows from blanks or low sales alone.
- Customer concentration remains unverified: customer IDs are absent; document numbers do not replace them.
- Reported Excel growth/seasonality coefficients remain source evidence. Unverified periods (including
  the thirteen-month total) prevent a like-for-like numeric growth comparison; none is applied again.
- Missing stock, arrival dates, lead times, BOM and unit conversions remain explicit limitations or blockers.
- No inventory simulation, savings claim, supplier submission, approval workflow or purchasing UI is included.
- Tests use actual source-derived rows with controlled in-memory transformations. Provider stubs exercise
  transport failure handling only; they are not business evidence.

## Completed monthly comparison / Завершённое сравнение

[Frozen results and code](../experiments/monthly/20260923-forecast-first/results.json) cover all
3,017 series in the two dedicated monthly workbooks. Both model families use exactly the same
target keys and unchanged actuals: 17,539 valid development targets and 20,321 retrospective targets.
Missing actuals and absent training history are recorded as exclusions. The reported coverage
denominator is the target ledger for series with training history; exclusions also include series
without training history. Unknown units in these workbooks prevent physical WAPE aggregation.

| Candidate / Кандидат | Development normalized error | Retrospective normalized error |
| --- | ---: | ---: |
| Recent level, retained / сохранён | 0.856049 | 0.727624 |
| EWMA | 0.841429 | 0.709433 |
| EWMA with candidate adjustments | 0.834872 | 0.705226 |
| Seasonal damped trend | 1.037364 | 0.914029 |
| LightGBM Tweedie | 0.986543 | 0.823826 |

The best adjusted statistical improvement is 2.47%, below the 3% promotion threshold. LightGBM
is 15.24% worse on development and exceeds the 5% supplier/horizon degradation guard for every
supplier/horizon. Selection remains **recent_level**, frozen before the retrospective comparison.
Production repeats this development selection on its pinned canonical inputs and stores evaluation
summaries with each run; it does not select from the 2026 score. The September bridge is a full-month
forecast prorated exactly once for September 22–30, including the stock snapshot day.

LightGBM remains research-only. The isolated run used Python 3.10.20 and the repository's pinned
research dependencies; no production ML dependency was added. Paid LLM evaluation was not executed
without explicitly configured credentials/models/prices; recorded spend is **$0**, and numerical
LLM deployment remains unverified. Transport, caching, semantic mapping checks, escalation and
budget failures have runnable tests.

Русский: основной вариант — среднее трёх последних валидных наблюдений. Улучшение скорректированного
EWMA 2,47% не проходит порог 3%; LightGBM хуже на 15,24%. Выбор не использует ретроспективу 2026.
Численные LLM-прогнозы не внедрены без оплаченного сопоставимого испытания. Клиенты, stockout,
потерянный спрос и своевременность пополнения остаются непроверенными там, где нет исходных фактов.

## Delivered snapshot / Сохранённый срез

Local PostgreSQL run `3d3c6169-79ee-4488-a125-0f63bb895512` pins all 12 workbook hashes with
normalizer `v2.3` and planning date `2026-09-22`. It stores 3,017 input snapshots and 9,051
October–December results: **9,018 `ok`, 33 `insufficient_data`**. Drafts are **371 estimated Systeme,
183 blocked Systeme, 2,463 blocked IEK**. No line is presented as a verified executable order.
Repeating the identical CLI request reused that run. The all-supplier and Systeme CSVs were generated
from stored quantities; source-row references resolve through the existing read API.

Verification: full backend suite **95 passed**, including PostgreSQL; final focused rechecks **53 passed**.
Ruff, the V2 contract check and import boundaries pass. Dedicated test databases passed migration
upgrade, downgrade, recreation and schema-drift checks, concurrent run reuse, failed-write rollback,
source deduplication, reservation reconciliation, receipt timing and exact CSV/API quantities.

Русский: сохранено 3 017 рядов, 9 051 результатов прогноза, 371 оценочный черновик Systeme.
Остальные 2 646 строк блокируются явно; повторный запрос использует тот же завершённый запуск.
Проверки не доказывают экономию запасов или восстановление потерянного спроса.
