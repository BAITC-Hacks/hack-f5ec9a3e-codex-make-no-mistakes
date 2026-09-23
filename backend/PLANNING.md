# Расчёт закупок / Purchasing backend

For this branch, use [isolated startup and verification](../docs/PURCHASING_WORKTREE.md).

## Русский

Реализован backend сценариев: подготовка исходных данных → расчёт → сохранение версии → корректировка количества с причиной → явное утверждение → CSV. Интерфейс менеджера отложен по просьбе пользователя. Существующий просмотр исходных данных сохранён. Никаких отправок поставщикам нет.

### Быстрый запуск без базы

Из `backend/`:

```powershell
uv sync --frozen
uv run python -m replenishment.cli.planning_demo --case baseline
uv run python -m replenishment.cli.planning_demo --case more-transit
uv run python -m replenishment.cli.planning_demo --case early-shortage
uv run python -m replenishment.cli.planning_demo --json
```

Все семь примеров синтетические. Базовый пример даёт 100 единиц, увеличение своевременного транзита с 70 до 100 уменьшает заказ до 70. В `early-shortage` заказ равен нулю, но показан ранний дефицит до 30 единиц. `missing-inputs` сохраняет в результате строку IEK без достоверного количества.

### API и сохранение

Запустите БД из корня: `docker compose up -d --wait db`. Затем из `backend/`:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment'
uv run alembic upgrade head
uv run alembic check
uv run uvicorn replenishment.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Миграция `0002` добавляет три таблицы сценариев и не изменяет исходные данные. Для подготовки сценария из Excel сначала выполните [импорт](IMPORTING.md). Для синтетических примеров импорт не нужен. Интерактивный контракт доступен по `http://127.0.0.1:8000/docs`.

1. `GET /api/v1/planning/demo-cases`: возьмите `input` примера.
2. `POST /api/v1/planning/calculate`: передайте этот `input`, получите расчёт без записи в БД.
3. `POST /api/v1/scenarios`: `{name, input}` сохраняет первую версию.
4. `PUT /api/v1/scenarios/{id}`: `{expected_revision, name, input, overrides}` добавляет версию. Корректировка: `{row_id, quantity, reason}`. Причина обязательна.
5. `POST /api/v1/scenarios/{id}/approve`: `{expected_revision, approved_by, acknowledge_scenario: true}` утверждает именно эту версию. Строки `needs_input` блокируют утверждение.
6. `GET /api/v1/scenarios/{id}/export?expected_revision=N`: UTF-8 CSV с предложенным и утверждённым количеством, причиной, источниками и пометкой сценария.

Изменение входов или количества создаёт новую версию без утверждения. Старое утверждение хранится в истории. Конкурирующий запрос со старой версией получает 409. CSV строится только из сохранённой утверждённой версии; текст защищён от формул Excel. Имя утверждающего — атрибуция локального демо, а не аутентифицированная корпоративная учётная запись.

### Методика

- Прогноз — простая средняя по объявленному календарному окну либо явно заданный дневной спрос. Это отдельная объяснимая политика сценария, а не автоматически выбранная модель исследовательского бенчмарка.
- Положительные расходные документы агрегируются по поставщику, SKU, складу, единице, дате, номеру и тексту документа. Отрицательные/пустые движения остаются неразрешёнными замечаниями.
- `exclude_bulk` явно включает исследовательскую политику `document-mad-v1`: сравнение с медианой/MAD, минимум истории, сохранение повторяющегося роста. При наличии анонимного ID документы одного клиента за день объединяются. Это статистические кандидаты, не доказательство намерения клиента.
- `compensate_stockouts` восстанавливает спрос только для переданных полных дней отсутствия, по минимум двум дням той же недели. Дни вне списка предполагаются доступными в сценарии; неполный журнал отсутствия не доказывает фактическую доступность. Конфликт продаж с полным отсутствием блокирует расчёт.
- Сезонные факторы — явные относительные поправки к выбранной базе. Они не обучены автоматически и не являются абсолютными сезонными индексами очищенной истории. Рост применяется один раз.
- Буфер: отдельное значение строки → явная карта `category_buffer_days` → общий `buffer_days`. Неизвестные коды категорий не получают выдуманного смысла.
- Горизонт: срок новой поставки + интервал пересмотра; календарные дни, приход перед расходом дня. Неудовлетворённый спрос переносится. Свободный остаток вычитается один раз; подходящий транзит должен поступить до конца горизонта.
- Потребность переводится в закупочную единицу, затем применяются отдельные минимум и кратность. Нулевой спрос на закупку не создаёт заказ из-за MOQ. Внутренние дроби точные: периодическая десятичная запись не добавляет лишнюю единицу при округлении вверх.
- Дневной баланс до предлагаемого нового заказа показывает первый дефицит и максимальный дефицит до возможного прихода. Нулевой итоговый заказ не означает отсутствие раннего дефицита.

### Реальные источники и ограничения

`POST /api/v1/planning/source-input` принимает выбранные `product_ids`, дату, склад, необязательные `normalizer_version` и `workbook_ids`. Не больше 20 SKU за запрос. Возвращаются `input` и `usage` по каждому семейству источников. Несколько версий требуют выбора; конфликтующие книги движений не складываются. Для истории используются 56 дней до даты расчёта; полнота выгрузки не считается доказанной.

Свободный остаток Systeme сохраняется вместе с неопределённостью склада и датой из имени файла. У IEK текущий снимок не выдумывается. Неизвестные сроки/год/количества поставок, полнота транзита и закупочные конверсии остаются неизвестными. Месячные отчёты, неоднозначные формулы, сводки сезонности и категории присутствуют как контекст с причиной неиспользования в арифметике до согласования.

Все вычислимые результаты v0 имеют статус `scenario_only`, даже при исходных наблюдениях `basis=observed`: бизнес-политики не подтверждены. `needs_input` отличается от нулевого заказа. Нет BOM, подтверждённых реальных stockout-интервалов, customer ID или полного справочника lead time. Сценарии показывают работу механизма, а не доказанную экономию или производственную готовность. Перед применением нужно согласовать эти определения и валидировать политики на реальной эксплуатации.

## English

The backend implements source preparation, explained calculation, saved revisions, quantity overrides with reasons, explicit approval, and CSV export. The manager interface is deliberately deferred. The existing source browser is preserved; no supplier messages are sent.

Run the commands above from `backend`. The CLI requires no database and generates seven labelled synthetic cases. `baseline` orders 100, `more-transit` orders 70, and `early-shortage` orders zero while reporting a 30-unit early shortfall. The JSON mode includes validated inputs and results.

Start the existing Compose PostgreSQL service, set DATABASE_URL, apply migration 0002, then launch Uvicorn. Migration 0002 adds three workflow tables without changing source records. Imported workbooks are needed only for source preparation; synthetic scenarios work without importing Excel. `/docs` exposes the interactive API. [PLANNING_API.md](../docs/PLANNING_API.md) specifies every field and endpoint.

Use preview → create → optional update/override → approve → export. Each update appends an immutable calculation revision and invalidates current approval; previous approvals remain in history. Stale operations receive 409. Scenario approval requires explicit acknowledgement; blocked rows cannot be overridden or approved. CSV contains both suggested and approved values, the reason, revision, basis and source references. Approval names are local-demo attribution, not authenticated identities.

The forecast is a simple calendar-window mean or explicit daily assumption, not the research benchmark's automatically selected model. Optional document-MAD bulk processing retains repeated elevated demand; supplied anonymous customer IDs group same-day documents. Known full-day stockouts use comparable weekdays, with the unlisted days assumed available in the scenario. Seasonal factors are explicit relative adjustments to the chosen baseline, not learned absolute indices. Category buffer precedence is row override, mapped category, then global default.

Coverage is lead time plus review interval, in calendar days. Arrivals precede consumption; unmet demand carries forward. Free stock is subtracted once. Incoming deliveries must have matching scope/unit and an eligible date. Convert to purchase units before minimum/multiple rounding; zero need remains zero. Exact rational internal arithmetic prevents repeating decimals from causing overordering. Daily balances expose shortages that a later routine order cannot prevent.

Source preparation is read-only and conservative: exact supplier/SKU, selected versions, 56 prior calendar days of positive outgoing documents, immutable workbook references, and explicit missing/conflicting fields. Monthly reports, ambiguous formulas and supplier-level seasonal summaries remain contextual until reconciled. It never manufactures customer IDs, stockout intervals, current IEK stock, transit year, lead times, conversions, or BOM. All calculable v0 results remain `scenario_only`; `observed` describes source provenance, not confirmed planning policy. Synthetic checks establish mechanism behavior, not real inventory savings.

## Проверки / Verification

```powershell
uv run pytest -q -m "not postgres"
uv run ruff check .
uv run lint-imports
```

PostgreSQL suites must target separate, empty databases. Never use the application database:

```powershell
# Create once from the repository root; existing populated databases must not be reused.
docker compose exec -T db createdb -U replenishment replenishment_orders_test
docker compose exec -T db createdb -U replenishment replenishment_sources_test
# From backend:
$env:ORDERS_TEST_DATABASE_URL = 'postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment_orders_test'
$env:SOURCE_TEST_DATABASE_URL = 'postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment_sources_test'
uv run pytest -q tests/test_orders_postgres.py tests/test_planning_sources.py
```

The workflow suite checks migration upgrade, drift, downgrade, recreation, concurrency, restart persistence, immutable revisions, approval invalidation and export. The source suite checks version isolation, signed/missing/future movements, warehouse scope, source references and the composed FastAPI workflow. [Independent acceptance](../docs/BACKEND_ACCEPTANCE.md) records synthetic requirements and tolerances. [Worktree handoff](../docs/PURCHASING_WORKTREE.md) records task ownership and integration results.
