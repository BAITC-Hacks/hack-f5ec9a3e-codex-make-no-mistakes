# Inventory evaluation v1 / Оценка пополнения v1

## Русский

Это инфраструктура оценки и TDD, без реализации прогнозирования и заказов. Первый результат —
проверяемый отчёт готовности, **NOT EVALUATED**, а не успешный бизнес-результат.
Используется отдельный от Python 3.10 research benchmark контур: существующий backend Python 3.12,
его `uv.lock`, pytest и стандартная библиотека. База данных не нужна.

Из `backend/`:

```sh
uv sync --frozen
uv run python ../scripts/check_eval_contract.py
uv run pytest -q tests/evaluation
uv run python ../scripts/evaluate.py --year 2024
uv run python ../scripts/evaluate.py --year 2024 --require-app
```

Последняя команда обязана завершиться ненулевым кодом, пока отсутствует приложение или не оценён
ни один реальный случай. Обычный запуск создаёт отчёт с явными пропусками. Исключения приложения,
нарушения контракта и повреждённые источники не превращаются в успешные пропуски.

Результаты: `artifacts/inventory-evaluation/<UTC>-inventory-evaluation-v1/`.
Каждый каталог неизменяем: `manifest.json`, `results.json`, `cases.csv`, автономный `report.html`.
`--output <новый-каталог>` задаёт путь; существующий каталог никогда не перезаписывается.
Откройте `report.html` локально. Все строки, включая пропущенные, находятся в CSV.
HTML содержит те же JSON-метрики и пять строк CLI. Исходные книги не изменяются.

В обоих закреплённых месячных отчётах продаж единица измерения отсутствует. Поэтому протокол v1
сохраняет `unit: null` и причину `unknown_unit`, не переносит единицы из движений, остатков или
2026 года без подтверждения. Все SKU участвуют в 11 парах январь→февраль … ноябрь→декабрь 2024.
Числовой ноль допустим; пустые, отрицательные и противоречивые обязательные наблюдения исключаются.
В истории используются только валидные завершённые месяцы до цели; непосредственно предыдущий
месяц обязателен. Плохие более ранние необязательные месяцы не заполняются и не передаются модели.
Полнота периода здесь означает завершённый календарный месяц, не подтверждение полноты учёта продаж.

Источники — две месячные книги из `docs/sources/manifest.json`; хеш и размер проверяются до чтения
через существующие `Workbook`, `classify`, `observations`. Агрегатная вкладка сезонности отдельно
отмечена как исключённая. Складской охват неизвестен; его нельзя присоединять к именованному складу.
Исторические поступления и подтверждённое время остатков отсутствуют: эффект для запасов N/A.
Исторический остаток не считается альтернативной закупочной политикой. Нет заявлений об экономии.

## English: protocol and boundary

The fixed future entrypoint is `replenishment.calculation.calculate(batch: list[dict]) -> list[dict]`.
It is deliberately absent. Contracts and mechanical oracles live only in `backend/tests/evaluation`.
There is no plugin registry, endpoint, fake forecast, or production placeholder. Imports must remain
side-effect free; calculation must use only supplied as-of observations, including during preprocessing
and model fitting. Each case has its own origin; later cases in a batch must not train earlier predictions.
Deterministic case selection does not promise deterministic model training.

The version string is `inventory-evaluation-v1`. `contracts.py` is the executable schema:

- Requests require `contract_version`, `case_id`, `supplier`, exact string `sku`, nonempty `unit`,
  `origin`, `target_month`, `history`, `stock`, `receipts`, `constraints`.
- Months are `YYYY-MM`; target immediately follows origin. History is sorted, unique, nonnegative,
  includes origin, and contains no target actual. Each observation has `month`, `quantity`, `sources`.
- Evidence references contain `path`, SHA-256 `sha256`, `sheet`, `cell`. Quantities are finite,
  nonnegative decimal strings (no exponent). Missing optional observations are JSON `null`.
- Stock, if confirmed, has `free`, `as_of` (origin month-end), `scope`, `sources`. Historical opening
  balances or unspecified snapshots cannot populate it without verified timing and common scope.
- Receipts, if confirmed, are a list of `id`, `quantity`, `due`, `known_at`, `scope`, `sources`.
  `null` means unknown, `[]` means confirmed none. IDs unique; known by origin; due after origin.
  Only transit due within the coverage horizon can reduce an order. Arrival dates alone do not prove
  actual delivery for replay.
- Constraints, if historically confirmed, have `minimum`, positive `multiple`, positive
  `coverage_months`, `confirmed_at`, `sources`. Zero minimum is permitted. No inferred 2026 rules.
- Responses echo all identity fields and target; require `status`, `forecast`, `reason`.
  Status is `ok`, `insufficient_data`, or `unsupported`. `ok` requires a forecast. Other statuses
  require `forecast: null` and a nonempty reason. Missing ordering also requires an explicit reason.
- Optional `recommended_quantity`, `components`, `evidence` accompany supported ordering. Components:
  `coverage_demand`, `free_stock`, `eligible_transit`, `minimum`, `multiple`. Explanations must reconcile
  to rounded nonnegative order. No order without confirmed stock, receipt completeness and constraints.
- Unexpected fields, malformed nested records, duplicate/missing results and changed identity fail.

Run the same five commands above from `backend/`. For pending TDD alone, use
`uv run pytest -q tests/evaluation --require-app`. Normal tests skip absent-app checks with
`app_not_implemented`; strict tests fail. Once the exact module exists, missing dependencies,
missing `calculate`, exceptions and invalid responses fail normally. Strict CLI additionally runs
the future app acceptance tests after a real batch succeeds. Synthetic fixtures never enter reports.

The acceptance suite covers batch identity, missing stock, constraints, order monotonicity,
explanation reconciliation and future-case poisoning across fitting/preprocessing. These observable
checks are not proof against every hidden external data read; review the implemented model's as-of
data access before making a leakage-free claim.

## Metrics and measurement scope

Supplier/unit cohorts remain separate, including monthly breakdowns. WAPE = sum absolute error /
sum actual × 100; signed bias = sum(prediction − actual) / sum actual × 100; MAE = sum absolute error /
number evaluated; underforecast = sum max(actual − prediction, 0). No evaluated pairs means N/A.
Zero total actual means percentage metrics are undefined, even if MAE is defined. Each cohort records
candidate/evaluated/skipped counts, actual denominator and percentage status. Unknown units never pool.

`metrics.replay` is a test-support recorded-condition oracle: initialize once, carry stock and unique
pending receipt IDs forward, and stop at missing demand or a month gap. It is not a purchasing engine
and is not invoked for the current source data. Inventory metrics remain explicitly unavailable until
scope/timing and observed delivery continuity are established. No reconstruction from monthly stocks.

An available app receives one cold invocation (first call after module import), one warm-up and
20 measured invocations of an identical eligible batch. Median and nearest-rank p95 are informational;
no SLA. Copying/validation is outside call timing. Cold is not OS-cache-cold or module import time.
No eligible batch means app latency is N/A. Harness preparation/render timings stay separate.
CPU and peak RSS cover the entire evaluation process through calculation, not app-only resources;
source bytes mean file content opened, not physical disk reads. Rows inspected count adapter-yielded
rows including headers; rows supplied count history observations in one eligible batch. Internal XML
passes, hashing and source-header inspection are identified by scope rather than falsely called app work.
Report timing measures an in-memory HTML render, excludes final writes. LLM accounting is N/A when
provider-reported usage is unavailable; the harness itself makes no LLM calls. Add actual provider
accounting when an implemented app uses one; never estimate tokens/cost from these harness timings.

Manifests record source hashes, revision/dirty state, code hashes, Python/platform and command.
Each run also snapshots its evaluation code, adapters, lockfile and protocol under `code/`.
To reproduce, restore these paths into a separate checkout of the recorded revision, sync the backend
environment, and run the recorded command with a new output directory. Reports are Git-ignored local
artifacts; copy a complete run directory to share it. Source workbooks remain in their pinned locations.
Runs stay distinct from immutable 2025/2026 research comparisons; nothing updates those tables.

Verification also runs `uv run ruff check . ../scripts/evaluate.py ../scripts/check_eval_contract.py`,
`uv run lint-imports`, and `uv run pytest -q -m "not postgres" tests/test_excel_import.py
tests/test_audit_baseline.py`. Database/API integrations remain optional and retain their existing
dedicated test-database guards; evaluation never reads `DATABASE_URL`.
