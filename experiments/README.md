# Experiments / Эксперименты

Start with the generated [comparison table](INDEX.md) and machine-readable [comparison.csv](comparison.csv). Discuss ownership, findings and decisions in [issue #4](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/4).

Use one **immutable snapshot directory per completed run**, named with its UTC registration timestamp and approach. Registration never overwrites an old run. Working output directories under `artifacts/` can be regenerated; register a completed run before changing its code or rerunning it.

## What every run keeps

- `manifest.json`: run ID, reproduction command, selected models, notes, source/data hashes, code provenance, environment/runtime when recorded, and selected metrics.
- `results.json`: the original model configuration, parameter selections and full metrics.
- `code/`: snapshots of the scripts needed to reproduce the run.
- `*.csv.gz`: compressed predictions and detailed metrics. These remain local and are Git-ignored to avoid growing the repository with every forecast. Share a specific archive through the team's agreed artifact storage when needed. Git alone does not distribute these ignored files.

Compact manifests, JSON summaries, code snapshots, `INDEX.md`, and `comparison.csv` are intended for Git. Registering a run does **not** commit or push anything. Raw input workbooks remain in their existing location; their SHA-256 hashes identify the data used.

To reproduce an older snapshot after scripts have changed, restore its `code/` files to their original `scripts/` paths in a separate checkout, then run the manifest command. The snapshots retain the scripts' original relative-path assumptions; do not execute them directly inside `runs/.../code/`.

The register independently recalculates full-cohort WAPE, bias, underforecast ratio and MAE from exported predictions. It rejects duplicate, invalid or missing predictions and mismatched metrics. Only runs with matching workbook hashes **and** exact target keys/actual quantities share a comparison section. This does not prove absence of feature leakage: model code and its temporal checks still need review.

Old baseline outputs did not record their original runtime or code hashes. Their registration states that limitation rather than inventing provenance. New model scripts record those details at execution.

## Environment and running

The research environment is separate from the application environment:

```sh
uv venv experiments/.venv --python 3.10
uv pip install --python experiments/.venv/Scripts/python.exe -r experiments/requirements.txt
experiments/.venv/Scripts/python.exe scripts/backtest_demand.py
experiments/.venv/Scripts/python.exe scripts/backtest_intermittent.py
experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py
```

These are Windows commands. On macOS/Linux use `experiments/.venv/bin/python`. The actual tested interpreter is Python 3.10.4; the planned application Python 3.12 runtime is separate. Requirements pin the experiment dependencies.

After a run, register it. Example:

```sh
python scripts/register_experiment.py artifacts/lightgbm-experiment --name lightgbm-v1 --models lgbm_l2 lgbm_tweedie lgbm_selected --scripts scripts/backtest_lightgbm.py scripts/backtest_demand.py scripts/backtest_intermittent.py --command "experiments/.venv/Scripts/python.exe scripts/backtest_lightgbm.py" --notes "Fixed two-objective grid; 2025-only selection; 2026 retrospective"
```

This checks predictions, freezes artifacts and code, then regenerates the comparison table. Use a new name such as `lightgbm-v2` when changing the feature set or tuning protocol. `python scripts/register_experiment.py --refresh` rebuilds the comparison from existing manifests. `python scripts/check_experiment_registry.py` checks the register's rejection rules.

## Comparison rules

The [shared protocol](../docs/DEMAND_EXPERIMENT.md) uses 2025 development and a 2026 retrospective comparison, both 7/28-day horizons, both suppliers and separate unit groups. Preserve these targets. Current registration supports this benchmark's 2025/2026 phase convention only.

Tune on development data only; write down the hypothesis and fixed candidate settings before running the comparison. Use WAPE alongside bias, underforecasting, segment/monthly stability and runtime. Avoid declaring a winner solely from the displayed 2026 table. That period is already known and is not a fresh test set. No forecast-error score proves inventory savings or a service level.

For each new attempt post a short issue comment: run ID, hypothesis, what changed, development result, retrospective result, failure cases, keep/reject/follow-up decision. The tables should be generated from artifacts rather than manually copied between notebooks.

This file-based register is enough for the current local team experiments. Consider MLflow or another shared service when runs move to multiple machines and artifact synchronization becomes a recurring burden.

## Monthly forecast-first comparison

The separate [monthly V2 result](monthly/20260923-forecast-first/results.json) uses three calendar
targets after a bridge month. It is not comparable with the registered 7/28-day benchmark above.
It retains exact source hashes, code snapshots, the fixed LightGBM settings and promotion rejection.
Detailed target ledgers are local `*.jsonl.gz` archives; compact results and code can be tracked.

```sh
experiments/.venv/bin/python scripts/backtest_monthly_lightgbm.py --output artifacts/monthly-forecast-new
```

An existing output directory is refused. To reproduce the frozen run, restore its `code/` files
to their original repository-relative paths in a separate checkout and use the pinned research
requirements. Recent level was retained; LightGBM was 15.24% worse on development. No production
ML dependency was added, and the historical register remains unchanged.

## Русский

Общий журнал — `INDEX.md` и `comparison.csv`; обсуждение — issue #4. Каждый завершённый запуск регистрируется отдельным каталогом с параметрами, метриками, хешами данных, снимками кода и сжатыми прогнозами. Старые запуски не перезаписываются.

Регистрация сверяет метрики с прогнозами, проверяет дубликаты и одинаковые цели. Разные данные/цели показываются отдельно. Большие CSV-архивы остаются локальными и не попадают в Git; компактные результаты и код предназначены для репозитория. Команда регистрации сама ничего не коммитит и не публикует.

2025 используется для выбора параметров, 2026 — уже известное ретроспективное сравнение. Смотрим не только WAPE, но и смещение, недопрогноз, устойчивость и время расчёта. MLflow пока не нужен; он станет полезен при регулярных запусках на нескольких машинах и необходимости общего хранилища артефактов.
