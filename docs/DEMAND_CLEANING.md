# Demand cleaning / Очистка спроса — issue #3

## Scope and fixed protocol

The `document-mad-v1` policy is a research assumption, not partner-confirmed
transaction semantics. Original XLSX and database observations remain immutable.
The pure implementation is `backend/src/replenishment/demand/cleaning.py`; it uses
Decimal quantities, has no database dependencies and can be reused by the future
calculation service. This slice produces local preprocessing artifacts and paired
experiments, not a new database table or purchasing recommendation.

- Include positive outgoing invoices (`Расходная накладная`). Keep negative
  movements as `negative_unresolved`, separately from missing/invalid quantities,
  zero quantities and other documents. Do not turn negatives into sales or claim
  they are confirmed returns. Missing identity/date rows are quarantined.
- Preserve exact SKU strings. Group positive lines by supplier, SKU, unit,
  warehouse, calendar date, document number and document text. Repeated lines are
  aggregated, not silently deduplicated; the source audit found no exact duplicate
  movement rows. Retain all source row numbers.
- For each document total use positive document totals from the preceding **56
  calendar days**, excluding same-day peers. Require **8 orders across 4 days**.
  Sparse or new histories remain unchanged and are labeled insufficient history.
- Flag a quantity strictly above `max(4 * median, median + 6 * MAD)`. Replace an
  isolated candidate with the historical median; retain the excess as an
  explained exclusion. This identifies candidate bulk documents, not customers.
- Preserve elevated orders if at least **3 distinct days within ±7 days** exceed
  that order's historical threshold, using only evidence strictly before the
  calculation date. A very recent flag is provisional and can be revised once
  repeated growth appears. Neither the threshold nor this guard sees future
  observations relative to a forecast origin.
- No customer concentration analysis: customer IDs are absent. No stockout
  imputation: exact availability is absent. Do not merge conflicting monthly
  reports into the transaction series or invent unit conversions.

These settings were fixed before evaluating the new cleaning results. No grid
search for a favorable cleaning threshold is performed. Three large orders may
be real projects rather than growth, and sparse histories may conceal bulk orders;
the flags need business review. The policy does not establish latent regular
demand ground truth.

## Comparison

Use the existing benchmark: January 2025–August 2026 transaction history, Алматы;
July–December 2025 development origins and January–August 2026 retrospective
origins; 7/28-day horizons; at least 90 days since first raw positive sale.
Keep all target quantities, cohorts and raw-history segment labels unchanged.
September is partial and excluded. Zero daily values mean no recorded positive
sale, not proof of no demand.

1. Rerun all six baseline forecasts on raw and cleaned histories. Report
   `clean_fixed_baseline` using the same model as the original 2025 selection,
   plus `clean_selected` choosing among the same four short-history models using
   cleaned-history 2025 WAPE only. Seasonal variants remain diagnostic.
2. Rerun the fixed 150-round full-feature Tweedie LightGBM with raw versus cleaned
   features. Both training labels and evaluation labels remain **raw gross
   outgoing sales**. Thus this is a feature-cleaning ablation, not a claim to learn
   a validated regular-demand target. Weekly training examples use their own
   historical cutoff. Training labels must end by each forecast origin.
3. Compare WAPE, bias, underforecasting, monthly and intermittent/regular results
   separately for each supplier/unit/horizon. Never add meters to pieces or packs.
   2026 has already been inspected in earlier experiments and is not a fresh test.

The cached cleaning implementation precomputes historical thresholds and completed
seven-day neighborhoods, then recalculates the revisable tail at each origin. The
runner checks it against a complete prefix-only calculation at the first and last
benchmark origins. Synthetic tests also check future-data invariance.

## Reproduce and inspect

From the repository root (the experiment environment remains Python 3.10):

```powershell
experiments/.venv/Scripts/python.exe scripts/backtest_cleaning.py
experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py --cleaning
```

These require the existing `artifacts/demand-experiment` baseline outputs. If they
are absent, first run `scripts/backtest_demand.py` with the same interpreter.

`artifacts/demand-cleaning/` contains:

- `movement_ledger.csv`: every source movement, exact row and original value,
  classification and experiment-date inclusion. Source path, sheet and SHA-256
  live in `results.json`.
- `order_decisions.csv`: all grouped positive orders and explanations, as of
  **2026-09-01**. Original = regular + excluded for every order.
- `cleaned_daily.csv`: raw/regular nonzero daily observations for that same cutoff.
  Omitted days are zero recorded sales. **Do not use this final-cutoff export for
  historical backtests**: the runner reconstructs cleaning at every origin.
- `cleaning_by_origin.csv`, `predictions.csv`, `metrics.csv`,
  `monthly_metrics.csv`, `results.json`: counts, quantities, predictions, results,
  runtime, environment and source/code hashes.

`artifacts/lightgbm-cleaning/` contains the paired model outputs and training
cutoffs. Registered snapshots under `experiments/runs/` retain JSON summaries,
code and locally ignored compressed CSVs. For cleaning snapshots restore
`code/cleaning.py` to **`backend/src/replenishment/demand/cleaning.py`**; restore the
other code files to `scripts/`. Registration does not commit, push or post comments.

Backend checks: from `backend/`, run `uv run pytest -q -m "not postgres"`,
`uv run ruff check .` and `uv run lint-imports`. No storage behavior changes or
database migration are needed.

## Русский

Политика `document-mad-v1` отделяет положительные расходные накладные от
отрицательных/неизвестных движений и пропусков. Отрицательные значения не объявляем
возвратами без подтверждения. Строки одного документа суммируются отдельно по SKU,
единице и складу; исходные значения и строки Excel сохраняются.

Крупный разовый документ сравнивается с медианой и MAD предыдущих 56 дней.
Повторение высокого уровня на трёх разных днях сохраняет устойчивый рост; самые
свежие флаги предварительны. На каждом историческом срезе используется только
доступное тогда прошлое. Клиентских ID нет, концентрацию по клиенту не выдумываем.

Эксперименты сохраняют исходные факты, SKU и горизонты. LightGBM получает очищенные
признаки, но исходные обучающие и проверочные цели. WAPE и смещение считаются
отдельно по поставщику/единице; 2026 — ретроспектива. Сырые файлы и БД не изменяются.
Результаты сравнения сохраняются отдельно в `DEMAND_CLEANING_RESULTS.md`.
