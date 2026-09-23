# Backend data foundation / Основа данных

## Русский

Реализованы модели SQLAlchemy, миграция Alembic, импорт Excel, API просмотра и React-таблицы. Основной forecast-first расчёт и экспорт доступны через CLI; запуск F5 и UI закупок — отдельные задачи. Текущий Compose запускает **только БД**.

Требуются uv и работающий Docker. Из корня репозитория:

```powershell
docker compose up -d --wait db
cd backend
uv sync --frozen
$env:DATABASE_URL = "postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment"
uv run alembic upgrade head
uv run alembic check
uv run python -m replenishment.cli.import_excel ../docs/data
uv run uvicorn replenishment.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

В другом терминале из `frontend`: `npm ci`, затем `npm run dev`. Откройте `http://127.0.0.1:5173`. Повторный импорт одинаковых файлов и версии пропускается. Подробности: [импорт](IMPORTING.md), [API](API.md), [интерфейс](../frontend/README.md).

Python 3.12 устанавливается uv при необходимости. Для Bash замените присваивание на `export DATABASE_URL='...'`. БД доступна только на localhost:55432; опубликованные учётные данные предназначены для локальной разработки.

Проверки исходных файлов и границ модулей:

```powershell
uv run pytest -q -m "not postgres"
uv run ruff check .
uv run lint-imports
```

Проверки миграции и ограничений требуют отдельную пустую БД с суффиксом `_test`:

```powershell
docker compose exec -T db createdb -U replenishment replenishment_test
$env:TEST_DATABASE_URL = "postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment_test"
uv run pytest -q
```

Создайте тестовую БД один раз. Успешный прогон оставляет её пустой для повторного запуска. Тест выполняет upgrade → проверки → downgrade → upgrade → проверка соответствия моделям → downgrade; на непустой БД он останавливается. Не используйте рабочую БД для этих проверок. Без `TEST_DATABASE_URL` PostgreSQL-тесты явно пропускаются.

Остановка: `docker compose stop db` из корня. Данные сохраняются в named volume. Для новой схемы добавляйте новую миграцию, не редактируйте уже применённую. Для новых исходных файлов добавляйте новую версию baseline, не подгоняйте старые хеши под изменения.

Для подключения используйте `127.0.0.1`, а не `localhost`: на Windows последний может разрешаться в IPv6, тогда как порт Compose привязан к IPv4. При ошибке соединения проверьте Docker и `docker compose ps`.

Документы: [архитектура](ARCHITECTURE.md), [Excel → БД](../docs/DATA_MODEL.md), [решения](../docs/DECISIONS.md).

## English

Implemented: SQLAlchemy models, Alembic migration, Excel ingestion, read API, React tables and integration tests. Forecast-first calculations and export run through the CLI; F5 startup and purchasing UI remain separate work. Current Compose starts **only PostgreSQL**, not the whole application.

The commands above migrate, import and start the API. In another terminal run `npm ci`, then `npm run dev` inside `frontend`; open `http://127.0.0.1:5173`. Reimporting identical files with the same normalizer version skips them. See [import](IMPORTING.md), [API](API.md) and [frontend](../frontend/README.md).

Install uv and start Docker, then run the commands above from the repository root. uv installs Python 3.12 if needed. For Bash use `export DATABASE_URL='...'` and `export TEST_DATABASE_URL='...'` instead of PowerShell assignments. Local PostgreSQL binds localhost:55432; the published credentials are development-only.

`uv sync --frozen` installs pinned dependencies; `uv run alembic upgrade head` creates the schema and `uv run alembic check` detects model/migration drift. Audit tests lock original hashes, sheet coverage, movement counts/signs, missing quantities, current stock and known source defects. Ruff and import-linter check code and module boundaries.

PostgreSQL tests require a dedicated empty database whose name ends in `_test`. Create it once with the shown `createdb` command. Successful tests leave it empty for reuse. They test upgrade, constraints, downgrade and recreation; a nonempty database is refused. Without `TEST_DATABASE_URL`, PostgreSQL tests are explicitly skipped. Never point these tests at a working database.

Stop using `docker compose stop db`; the named volume preserves data. Add new migrations for later schema changes. Changed source files require a new audit baseline, not silently rewritten expected hashes. See the bilingual architecture, mapping and decision documents linked above.

Use `127.0.0.1` for the database connection: Windows may resolve `localhost` to IPv6 while Compose binds IPv4. Check Docker and `docker compose ps` if connection fails. Connections have a five-second timeout.

## Forecast-first calculation / Прогноз и черновики

### Optional OpenAI configuration

Copy `.env.example` to `.env` in the repository root. Set `OPENAI_ENABLED=true`,
`OPENAI_API_KEY`, `OPENAI_MODEL`, and both `OPENAI_INPUT_PER_MILLION` and
`OPENAI_OUTPUT_PER_MILLION` to explicit deployment values (USD per million tokens).
No model or price is assumed. Missing credentials or either price block paid calls;
missing models and malformed settings raise errors without printing their values.
Unset/false `OPENAI_ENABLED` returns no client. Settings are read at invocation,
not module import; the application does not automatically load dotenv files.

From `backend/`, load the file explicitly with uv:

```sh
uv run --env-file ../.env python -m replenishment.cli.import_excel ../docs/data
uv run --env-file ../.env python -m replenishment.cli.calculate --planning-date 2026-09-22
```

Optional `OPENAI_STRONG_MODEL` plus `OPENAI_STRONG_INPUT_PER_MILLION` and
`OPENAI_STRONG_OUTPUT_PER_MILLION` configure extraction escalation. Leave all
`OPENAI_STRONG_*` settings blank to disable it. Input/output limits default to
8000/512 for each model; override with `OPENAI_MAX_INPUT_TOKENS`,
`OPENAI_MAX_OUTPUT_TOKENS` and their `OPENAI_STRONG_*` equivalents.

Explicit `--llm-config path.json` preserves JSON configuration behavior, independently
of `OPENAI_ENABLED`, and overrides all environment model/pricing/token settings.
Its `api_key_env` selects the credential variable (default `OPENAI_API_KEY`).
Both CLIs accept `--llm-cache path.json` for the existing exact-input cache.
Structured validation, failure accounting and the $1/run cap remain in force.
The calculation forecast pilot remains diagnostic-only. The existing Responses
endpoint and 30-second timeout are unchanged; no HTTP API or storage changes.
See the [official OpenAI quickstart](https://developers.openai.com/api/docs/quickstart).

After `alembic upgrade head` and the default **v2.3** import of all supplied workbooks:

```sh
uv run python -m replenishment.cli.calculate --planning-date 2026-09-22
uv run python -m replenishment.cli.calculate --supplier systeme --export systeme-recommendations.csv
uv run python -m replenishment.cli.calculate --export-run <run-uuid> --supplier iek --export iek.csv
```

The default planning date is the documented source-snapshot assumption, **22 September 2026**.
The run fits complete history through August, forecasts September internally, and publishes
**October–December 2026**. `--manifest` defaults to the repository source manifest. Every workbook
hash and normalizer version is pinned; missing imports fail explicitly. `--sources selection.json`
can supply a narrower explicit list of `{table, sha256, normalizer_version}` selections.
`--normalizer-version` selects one existing normalization version; no latest-version guessing.

`calculate(batch)` is the main V2 pure boundary; there is no legacy strategy switch. The CLI loads
a repeatable-read database snapshot and persists the run, inputs, forecasts and draft lines in one
transaction. Identical inputs/implementation versions reuse completed results. `--rerun` creates a
new run. CSV refuses to overwrite an existing file and carries recommendation-only labeling,
`ready`/`estimated`/`blocked` states, units, assumptions and evidence. No supplier sending.

Русский: неизвестные остатки/единицы не становятся нулями/штуками. Прогноз может быть готов при
заблокированном заказе. CSV содержит сохранённые количества и явные ограничения. Отсутствующий
lead time запрещает обещать своевременное пополнение; customer concentration и точные stockout
интервалы остаются непроверенными без соответствующих исходных данных.

Methodology and evaluation: [RU/EN](../docs/INVENTORY_EVALUATION.md). Draft arithmetic:
[RU/EN](../docs/PURCHASING_CONTRACT.md). Result reads and CSV: [API](API.md).

Run the result integration checks only on another empty dedicated database:

```sh
# CALCULATION_TEST_DATABASE_URL must name a dedicated empty *_test database.
uv run pytest -q tests/test_calculation_storage.py
```

The suite exercises a real monthly source workbook, concurrent idempotence, failed-write rollback,
exact export, API filters and migration upgrade/downgrade/recreation/drift. `API_TEST_DATABASE_URL`
retains the separate `replenishment_api_test` guard. Never use working data for these checks.


### Employee approval demo

After `uv run alembic upgrade head`, run `uv run python -m replenishment.cli.seed_demo`.
This transactionally seeds two employees and one synthetic three-line calculation run; replay preserves
existing data. See [API.md](API.md#employee-order-documents-v2) for the create/edit/approve example.

Run the isolated PostgreSQL acceptance and migration lifecycle checks with:

```sh
# Must target a dedicated, initially empty database whose name ends in _test.
ORDERING_TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/replenishment_ordering_test \
  uv run pytest -q tests/test_ordering.py
```

CI creates this database independently of existing integration databases. The test covers seed replay,
atomic errors, approval attribution, edit/approval concurrency, permanent locking, upgrade/downgrade,
recreation and Alembic schema drift. Test cleanup drops only its isolated test schema.
