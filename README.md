# hack-f5ec9a3e-codex-make-no-mistakes
Hackathon team repository for Codex, make no mistakes

HackAlem AI case: supplier order recommendations for Elektrokomplekt LLP (ekt.kz).

## Forecasting: what we use and what the research found

**Operational choice: uncapped weekly EWMA, selected through `forecast_method: "auto"`.**
There is no universally best model in the experiments. EWMA is our explainable
baseline for purchasing; full-feature Tweedie LightGBM is the strongest ML challenger,
not a validated replacement across all suppliers and forecast periods.

The calculation API and imported-source preparation support automatic forecasting:

- With at least 56 declared history days, use the last eight weeks with weights
  `0.72 ** floor(age_in_days / 7)`, without automatically capping large sales.
- With shorter history, or explicit stockout compensation, use the existing
  historical-mean policy. An explicitly entered daily-demand assumption takes precedence.
- Forecast the user's inclusive start/end dates, then apply scenario factors,
  buffer, eligible stock/transit, unit conversion, minimum order and order multiples.
  Supplier lead time controls arrival timing; it is not added to a custom date range.
- Return `forecast_method` with each result. Existing API callers that omit the
  selector retain `history_mean`; new source-prepared scenarios opt into `auto`.
  Bulk exclusion and stockout compensation remain off unless explicitly requested.

Seven registered experiments share 65,754 forecast keys. The table compares
2026 retrospective WAPE (%; lower is better) with the development-selected benchmark,
which is **not the same as the uncapped application EWMA**.

| Supplier / unit / horizon | Selected benchmark | Full Tweedie | Finding |
| --- | ---: | ---: | --- |
| IEK / meters / 28 days | 64.977 | 58.803 | Strong ML lead; Tweedie lost in 2025 development |
| IEK / packs / 28 days | 42.567 | 46.293 | Capped baseline has lower error, with more underforecasting |
| IEK / pieces / 28 days | 40.245 | 40.152 | Small difference; no convincing general replacement |
| Systeme / pieces / 28 days | 42.760 | 42.430 | Small difference; monitor bias as well as error |

The narrower **IEK packs, 7-day, Tweedie without weekly-lag features** candidate
scored 66.990 vs 81.969 retrospectively and 51.634 vs 51.879 in development.
Automatic cleaning worsened every 28-day baseline group. Combined raw/clean/bulk
features, SBA and TSB did not establish a universal improvement. Keep raw demand
and validate challengers at the actual purchasing horizon before promotion.

These are forecasts of recorded positive sales, not unconstrained demand or proven
inventory savings. WAPE is not an accuracy percentage. July–December 2025 was used
for selection; January–August 2026 has already informed multiple experiments and
is retrospective, not a fresh test. Arbitrary custom horizons are extrapolations;
LightGBM and calibrated safety buffers are not connected as automatic defaults.

Evidence: [registered comparison](experiments/INDEX.md),
[baseline findings](docs/DEMAND_RESULTS.md), [ablation findings](docs/LIGHTGBM_ABLATION.md),
[cleaning findings](docs/DEMAND_CLEANING_RESULTS.md),
[combined features](docs/COMBINED_FORECAST_RESULTS.md).
Implementation: [calculation policy](backend/src/replenishment/planning/calculator.py),
[custom-period contract](docs/CUSTOM_FORECAST_PERIOD.md).

Промышленный базовый выбор — недельный EWMA без ограничения пиков; при короткой
истории используется среднее. Tweedie — перспективный кандидат для отдельных
групп и горизонтов, а не доказанный общий победитель. Собственные даты передаются
в расчёт, а использованный метод возвращается для каждой позиции.

Start with the [project documentation](docs/README.md), then read the
[project context](docs/PROJECT_CONTEXT.md) and [data guide](docs/DATA_GUIDE.md).
The original brief and all 12 extracted supplier workbooks are included in `docs/`.

Current state: source documentation, audit checks, Excel ingestion, read API and React source tables,
plus backend purchasing calculations, saved scenario revisions, approval and CSV export are implemented.
The new Elektrokomplekt purchasing workspace connects imported products, calculation, saved revisions, approval and CSV export to the backend. Explicitly labelled synthetic examples remain available.
Calculable v0 recommendations are explicitly labelled scenarios. See the
[current verification and demo walkthrough](docs/DELIVERY_VERIFICATION.md).
Start with [purchasing backend RU/EN](backend/PLANNING.md) and the [parallel execution plan](docs/PARALLEL_DELIVERY_PLAN.md).
See [backend setup RU/EN](backend/README.md), [architecture](backend/ARCHITECTURE.md)
and [Excel-to-database mapping](docs/DATA_MODEL.md).

Текущее состояние: импорт Excel, API чтения и React-таблицы, backend расчёта закупок, сохранение версий,
утверждение и CSV. Новое рабочее место Электрокомплект подключено к backend: импортированные товары, расчёт, версии сценариев, утверждение и CSV. Учебные примеры явно обозначены.
Актуальная проверка и сценарий показа: [RU/EN](docs/DELIVERY_VERIFICATION.md).

Запуск / Run: [backend + import](backend/README.md), [frontend](frontend/README.md).
API: [contract RU/EN](backend/API.md). UI scope: [requirements RU/EN](docs/FRONTEND_REQUIREMENTS.md).

Проверка импорта / Import validation: [independent data-quality report](docs/reports/data-quality.md)
and [reproduction command](backend/IMPORTING.md#независимая-сверка--independent-reconciliation).

Согласованные требования к стеку, запуску через F5 и Docker, сценариям и демонстрации:
[план сдачи RU/EN](docs/DELIVERY_PLAN.md). Инструкции запуска: [Docker и F5](docs/STARTUP.md).

Approved stack, F5/Docker startup, scenarios and demonstration requirements:
[delivery plan RU/EN](docs/DELIVERY_PLAN.md). See [Docker and F5 startup](docs/STARTUP.md); Docker was verified, F5 configuration has not been launched in VS Code.
