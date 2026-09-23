# Combined forecast experiment / Совместные признаки прогноза

## Hypothesis fixed before this run

Replacing raw history with cleaned history discarded useful signals. Instead,
predict **total recorded positive outgoing sales** using both histories and
document-level bulk-candidate signals. This experiment concerns forecasting,
not buyer review or purchasing UI.

Compare two fixed full-feature Tweedie models:

- `tweedie_raw`: the existing 29 features, reproduced as an exact control.
- `tweedie_combined`: the same 29 raw features plus 17 cleaned-demand features
  (five means, eight weekly lags, maximum, standard deviation, positive-sale size,
  recent ratio) and 13 document-level signals. For 7/28/56/84 prior days, add
  bulk-candidate order count, fraction of observed orders flagged, and mean
  excluded quantity per flagged order. Add days since the last candidate,
  capped at 84; no candidate in that window also maps to 84.

Keep the existing 150 rounds, tree settings, Tweedie variance power 1.5 and seed.
No parameter search or cleaning-threshold change. Cleaning remains the fixed
`document-mad-v1` policy described in [DEMAND_CLEANING.md](DEMAND_CLEANING.md).
Candidate flags are statistical, not verified customer/project labels.

## Evaluation and selection

Reuse exactly the existing source files, 65,754 forecast keys, actual quantities,
raw-history cohort and segment labels. Fit separately per supplier/unit/horizon
(7 and 28 days). Training and scoring labels are unchanged raw positive outgoing
sales. Features for every weekly/monthly training example use only information
available strictly before that example's date. Only labels fully observed by the
forecast origin enter its training set. No future cleaning/growth decisions enter
historical features.

Use July–December 2025 WAPE to select:

- `lgbm_selected`: raw or combined Tweedie, with raw winning ties.
- `forecast_selected`: existing baseline selection, raw Tweedie, or combined
  Tweedie, with the baseline first in tie order. This is selection within these
  three options, not a claim to beat every historical model in the registry.

Freeze those choices for January–August 2026. That period has been examined in
earlier experiments and is **retrospective**, not an untouched holdout. Show all
candidates, bias, underforecasting, monthly variation and regular/intermittent
segments so a small aggregate improvement does not hide failure cases. Include
the prior clean-only experiment as a comparison without refitting/tuning it.
Do not pool pieces, meters and packs or claim inventory savings from forecast error.

## Reproduce

From the repository root, using the pinned research environment:

```powershell
experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py --combined
```

The existing `artifacts/demand-experiment` baseline is required (generate it with
`scripts/backtest_demand.py` if absent). Outputs go to the new
`artifacts/lightgbm-combined/` directory, preserving earlier runs. The summary
records source/code hashes, feature names, selections, metrics and runtime.
Register the completed run before changing its code. As with cleaning snapshots,
restore `code/cleaning.py` under `backend/src/replenishment/demand/`, and the other
files under `scripts/` when reproducing an archived version.

Checks: hand-calculated feature values, preservation of the raw feature block,
rejection of current/future order signals, cached versus full-prefix cleaning and
bulk features at training/test cutoffs, exact earlier raw predictions, complete
matching targets, and registry metric reconciliation.

## Русский

Модель получает исходные продажи, очищенную историю и признаки крупных заказов
одновременно. Цель — фактические положительные отгрузки, а не искусственно
очищенные будущие продажи. Настройки модели и очистки фиксированы. Выбор отдельно
для поставщика/единицы и горизонтов 7/28 дней — только по 2025; 2026 является
ретроспективой. Сравниваем также смещение и недопрогноз, не только WAPE.
