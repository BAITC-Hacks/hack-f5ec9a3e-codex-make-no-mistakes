# hack-f5ec9a3e-codex-make-no-mistakes
Hackathon team repository for Codex, make no mistakes

HackAlem AI case: supplier order recommendations for Elektrokomplekt LLP (ekt.kz).

## Development tasks

Run `make help` from the repository root. Requires GNU Make, uv, Node.js 22+;
Docker is needed for database tasks. On Windows use a POSIX shell with Make,
or the native PowerShell commands in [backend setup](backend/README.md).

```sh
make dev-setup       # Install dependencies, start DB, migrate, import workbooks
make dev-api         # API with reload; keep running
make dev-ui          # Frontend; run in a second terminal
make check           # Lint, DB-free tests, frontend build, registry guards
make test-eval       # Evaluation contracts and tests only; no DB
make evaluate        # Evaluate monthly three-period forecasts on original documents
make calculate       # Persist pinned forecast/order drafts in PostgreSQL
```

`make install` installs dependencies without starting Docker. `make test` runs
backend and frontend tests; `make test-postgres` requires an explicitly set
`TEST_DATABASE_URL` pointing to a dedicated empty `*_test` database (creation
instructions in the backend setup). `DATABASE_URL` defaults to local Compose;
override it through the environment when needed. `make db-stop` preserves data.

The main application implements the **v2 forecast-first contract**. Development origins are
June–September 2025; the January–May 2026 comparison is retrospective.
`make test-eval-strict` and `make evaluate-strict` exercise the implemented calculation contract. Reports use new immutable
directories under `artifacts/inventory-evaluation/`. See the
[evaluation protocol](docs/INVENTORY_EVALUATION.md). Forecast research retains its
separate [Python 3.10 environment](experiments/README.md).

Start with the [project documentation](docs/README.md), then read the
[project context](docs/PROJECT_CONTEXT.md) and [data guide](docs/DATA_GUIDE.md).
The original brief and all 12 extracted supplier workbooks are included in `docs/`.

Current state: source documentation, locked audit checks, modular SQLAlchemy models, PostgreSQL migration,
Excel ingestion, read API and React tables are implemented. The forecast-first calculation, supplier draft persistence and CSV export are the main backend path.
See [backend setup RU/EN](backend/README.md), [architecture](backend/ARCHITECTURE.md)
and [Excel-to-database mapping](docs/DATA_MODEL.md).

Текущее состояние: документация, проверки аудита, модульные модели SQLAlchemy, миграция PostgreSQL,
импорт Excel, API чтения и React-таблицы. Основной forecast-first расчёт, сохранение черновиков и CSV-экспорт доступны через CLI.

Запуск / Run: [backend + import](backend/README.md), [frontend](frontend/README.md).
API: [contract RU/EN](backend/API.md). UI scope: [requirements RU/EN](docs/FRONTEND_REQUIREMENTS.md).

Проверка импорта / Import validation: [independent data-quality report](docs/reports/data-quality.md)
and [reproduction command](backend/IMPORTING.md#независимая-сверка--independent-reconciliation).

Согласованные требования к стеку, запуску через F5 и Docker, сценариям и демонстрации:
[план сдачи RU/EN](docs/DELIVERY_PLAN.md). Режимы запуска ещё предстоит реализовать.

Approved stack, F5/Docker startup, scenarios and demonstration requirements:
[delivery plan RU/EN](docs/DELIVERY_PLAN.md). Startup modes are not implemented yet.
