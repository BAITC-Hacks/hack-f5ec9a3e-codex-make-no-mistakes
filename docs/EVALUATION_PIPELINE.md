# Evaluation pipeline implementation contract

Backend-only work, 2026-09-23. Metrics, evaluation, and experiments have separate responsibilities.

- `backend/src/replenishment/metrics/`: pure reusable standard-library metric formulas and promotion checks, no I/O, model or database imports; compatible with Python 3.10 research and Python 3.12 backend.
- `backend/src/replenishment/evaluation/`: read-only workbook ingestion, rolling historical targets, calls to the actual backend calculator, baseline predictions, report/manifest output.
- `backend/src/replenishment/cli/evaluate.py`: one-command evaluation entry point in the locked Python 3.12 backend environment.
- Existing `scripts/backtest_*.py` and `scripts/register_experiment.py`: experiments and immutable registry, preserved and reused rather than replaced.

## Ownership for parallel implementation

Controller owns evaluation runner, source ingestion, CLI, documentation, research scorer integration and full-data execution.
Metrics worker owns `metrics/**` and `tests/test_metrics.py`.
Artifact worker owns `evaluation/artifacts.py` and `tests/test_evaluation_artifacts.py`.
Acceptance worker owns `tests/test_evaluation_acceptance.py` and independently reviews leakage/target matching once runner exists.
No frontend, database writes, dependency installations, or changes to saved historical experiments.

## Shared interfaces (frozen first implementation)

`replenishment.metrics.forecast_metrics(actual, predicted, *, mae_scales=None, mse_scales=None) -> dict`:
finite nonnegative sequences, identical nonempty lengths; no implicit zip truncation. Returns `n`, `actual_qty`, `predicted_qty`, `wape_pct`, `bias_pct`, `underforecast_pct`, `overforecast_pct`, `mae`, `rmse`, `zero_actual_pct`, `mase`, `rmsse`, `mase_n`, `rmsse_n`. Zero-total WAPE/bias ratios are null, not fabricated zero. Positive bias means overforecast. Scaled scores exclude undefined/zero training scales and expose counts. Formula implementation must be stdlib-only and Python 3.10-compatible.

`replenishment.metrics.compare_metrics(candidate, baseline, *, min_improvement_pct=10, max_abs_bias_pct=5) -> dict`:
returns `status: pass|fail|not_evaluable`, `wape_improvement_pct`, `reasons`. Check identical n and actual_qty; zero baseline error yields no relative improvement (perfect equality can be explicitly handled as zero improvement). These are configurable internal gates, not industry standards; structural integrity failures are different from a legitimate model failing promotion gates.

`replenishment.evaluation.runner.evaluate_series(series, *, origins, horizons=(7,28), models=("backend_raw","backend_bulk","mean28","weekly_naive"), min_history_days=90, lookback_days=56) -> list[dict]`:
series is a list of plain dicts `{supplier, warehouse, unit, sku, name, start: date, end: date, sales: [{day: date,quantity: Decimal,document: str}]}`. The inclusive coverage start/end describe the whole supplied extract, not per-SKU last purchase. Missing days mean zero recorded positive sales, not confirmed zero demand. Eligibility is based on first positive sale before origin minus min_history_days, never future outcomes. Reject any origin/horizon beyond complete extract coverage. Models use only dates before origin. `backend_raw`/`backend_bulk` must call the public current `calculate` function, with explicitly synthetic stock/lead-time settings that isolate forecast quantity; do not duplicate its forecasting formula. Historical targets are gross-positive recorded sales, not latent regular demand.

Each prediction row is long-format `{supplier,warehouse,unit,sku,origin: ISO date,horizon:int,phase,segment,model_id,actual:float,forecast:float,mae_scale:float|null,mse_scale:float|null}`. Phase is development_2025 or retrospective_2026. Segment regular/intermittent uses only eight historical weeks (>=4 active weeks regular). Scaled-error denominators use preceding nonoverlapping horizon-sized totals and lag-one naive errors at the SAME aggregation grain; at least two blocks, zero scale undefined. Never mix units into an overall quantity score.

`replenishment.evaluation.runner.summarize(predictions) -> list[dict]`: group phase/supplier/warehouse/unit/horizon/model plus all/regular/intermittent. Include metric formula output and `sku_count`, `origin_count`. `monthly_metrics` are independently grouped by origin for stability reporting.

`replenishment.evaluation.artifacts.write_run(output_dir: Path, predictions: list[dict], summary: dict, *, code_files: list[Path], reproduction_command: str) -> dict`:
output directory must not already exist; write predictions.csv (long-format, registry-compatible), results.json, metrics.csv, report.md, manifest.json and code snapshots with original relative paths. Independently verify all models have exact identical target keys/actuals, no duplicates/nonfinite/negative forecasts, and recalculate each all-cohort metric from predictions before writing. summary contains source_files (supplier/source/sha256), models, metrics, monthly_metrics, configuration, gates, operational_metrics, environment, elapsed_seconds. Preserve all; add hashes/provenance without pretending unrecorded details were recorded. report.md contains retrospective all-cohort WAPE/bias/MASE/RMSSE table, gates, caveats and reproduction. JSON disallows NaN/Infinity. Hash outputs and source/code; target_sha256 canonical comparable to existing register key supplier/SKU/unit/origin/horizon. Report legacy registry incompatibility if multiple warehouses would collide under its older key.

## Evaluation protocol

Default follows existing benchmark: gross positive outgoing Алматы movements, 2025-01-01 through 2026-08-31, origins monthly July–December2025 and January–August2026, horizons7/28. Keep both suppliers and stock units separate, same eligible products per model. No tuning on known 2026 retrospective. Metrics for current raw/bulk calculator, fixed 28-day mean and weekly seasonal-naive baseline. Baseline for predeclared gate is mean28. Changing the baseline requires an explicit CLI option and recorded configuration.

CLI flags: `--data-dir` (defaults docs/data), `--output` (optional new directory; default timestamped artifacts/backend-evaluation run), `--models`, `--baseline` default mean28, `--limit-per-group` optional smoke subset (supplier/unit; explicitly partial), `--min-improvement-pct`, `--max-abs-bias-pct`, `--check-gates` (nonzero for failed/not-evaluable gates; default model failure still produces successful evaluation output), and `--register` to invoke existing immutable experiment register after successful artifact validation. Full default run uses no smoke limit. Emit progress per origin/supplier and final paths.

Operational fill rate, stockout duration and inventory savings are `not_evaluated`, with missing requirements stated: exact historical availability, inventory/receipt timing, agreed lead/review policies and demand treatment. Do not infer them from underforecast percentage or source monthly stock. Synthetic calculator acceptance remains a separate mechanism check.

## Verification

Metric hand calculations/undefined cases/mismatched lengths and groups; synthetic runner tests for future isolation, complete horizons, eligibility and identical cohorts; output validator rejects missing/duplicate model targets/tampered metrics; smoke CLI on original workbooks; full run on both suppliers; reuse register validation and immutable registration. Update final docs with actual measurements and all failed promotion gates.
