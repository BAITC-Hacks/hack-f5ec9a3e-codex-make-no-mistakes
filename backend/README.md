# Backend data foundation / Основа данных

## Русский

Реализованы модели SQLAlchemy, миграция Alembic, импорт Excel, API просмотра и React-таблицы. Расчёт заказов и запуск F5 ещё предстоит реализовать. Текущий Compose запускает **только БД**.

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

Implemented: SQLAlchemy models, Alembic migration, Excel ingestion, read API, React tables and integration tests. Order calculations and F5 startup remain subsequent work. Current Compose starts **only PostgreSQL**, not the whole application.

The commands above migrate, import and start the API. In another terminal run `npm ci`, then `npm run dev` inside `frontend`; open `http://127.0.0.1:5173`. Reimporting identical files with the same normalizer version skips them. See [import](IMPORTING.md), [API](API.md) and [frontend](../frontend/README.md).

Install uv and start Docker, then run the commands above from the repository root. uv installs Python 3.12 if needed. For Bash use `export DATABASE_URL='...'` and `export TEST_DATABASE_URL='...'` instead of PowerShell assignments. Local PostgreSQL binds localhost:55432; the published credentials are development-only.

`uv sync --frozen` installs pinned dependencies; `uv run alembic upgrade head` creates the schema and `uv run alembic check` detects model/migration drift. Audit tests lock original hashes, sheet coverage, movement counts/signs, missing quantities, current stock and known source defects. Ruff and import-linter check code and module boundaries.

PostgreSQL tests require a dedicated empty database whose name ends in `_test`. Create it once with the shown `createdb` command. Successful tests leave it empty for reuse. They test upgrade, constraints, downgrade and recreation; a nonempty database is refused. Without `TEST_DATABASE_URL`, PostgreSQL tests are explicitly skipped. Never point these tests at a working database.

Stop using `docker compose stop db`; the named volume preserves data. Add new migrations for later schema changes. Changed source files require a new audit baseline, not silently rewritten expected hashes. See the bilingual architecture, mapping and decision documents linked above.

Use `127.0.0.1` for the database connection: Windows may resolve `localhost` to IPv6 while Compose binds IPv4. Check Docker and `docker compose ps` if connection fails. Connections have a five-second timeout.
