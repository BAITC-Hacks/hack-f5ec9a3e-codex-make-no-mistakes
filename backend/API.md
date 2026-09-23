# API данных / Source data API v1

Purchasing endpoints are now documented in [PLANNING.md](PLANNING.md) and the exact
[planning contract](../docs/PLANNING_API.md). The source endpoints below remain read-only;
their historical statement that the application has no scenario writes applies only to this source-data slice.
Расчёт, сценарии, утверждение и экспорт добавлены отдельными маршрутами; исходные данные не изменяются.

## Русский

Запуск из `backend` с заданным `DATABASE_URL`:

```sh
uv run uvicorn replenishment.api.app:create_app --factory --reload
```

OpenAPI: `/openapi.json`, интерактивная документация: `/docs`. React использует тот же origin
через прокси Vite `/api`; CORS для произвольных сайтов не включён.

- `GET /api/v1/health` проверяет соединение с БД.
- `GET /api/v1/tables` — разрешённые таблицы, типы/nullable полей, сортировки и фильтры.
- `GET /api/v1/tables/{table}` — страница данных; короткий алиас `/api/v1/{table}`.
- `GET /api/v1/source-rows/{uuid}` — ячейки исходной строки, формулы, ошибки, сохранённые
  результаты, файл/хеш, лист и номер строки. Отсутствующий ключ ячейки означает пустоту.

Таблицы: `catalog`, `suppliers`, `workbooks`, `sheets`, `products`, `warehouses`, `movements`,
`monthly-sales`, `monthly-stock`, `current-stock`, `moq`, `shipments`, `shipment-lines`,
`report-metrics`, `seasonality`, `findings`. Двоичный XLSX не передаётся в списках.

Параметры: `page` от 1, `page_size` 1–200 (по умолчанию 50), `sort` — поле из descriptor,
`direction=asc|desc`, `q` — буквальный поиск подстроки (до 200 символов, `%` и `_` не маски).
Доступные точные фильтры перечислены в descriptor: `supplier_id`, `product_id`, `workbook_id`,
`sheet_id`, `normalizer_version`, `warehouse_id`, `metric`, `kind`, `status`, `category_code`, `sku`.
`warehouse_id=unknown` выбирает только NULL, без присвоения склада «Алматы».
Поиск `q` охватывает только текстовые поля самой проекции. Поиск названия/артикула/категории
выполняется в `products`; остальные наблюдения можно выбрать по найденному `product_id`.

Формат страницы: `{table, items, total, page, page_size}`. `items` содержит поля descriptor.
UUID, даты и Decimal передаются строками; Decimal имеет фиксированную десятичную запись,
включая `"0.000000000000"`. NULL сохраняется. Сортировка всегда дополняется уникальным `id`,
NULL в конце. Пагинация стабильна для неизменившегося набора данных; при параллельном импорте
следует зафиксировать `workbook_id` и `normalizer_version`.

**`catalog` — одна строка на идентичность товара:** `id` = `product_id`, точный `sku` и поставщик.
Название, артикул и категория не выбираются произвольно из конкурирующих источников.
Выбрав товар, используйте `product_id` в таблице наблюдений и остальных фактах.

**`products` — наблюдения атрибутов из источников, не канонический каталог:** `id` идентифицирует
наблюдение; `product_id` — стабильный товар поставщика; одинаковый SKU закономерно повторяется
по строкам, книгам и версиям. Никакого неявного latest/dedup/sum. Для наблюдений передаются
`source_row_id`, `source_column` (где есть), `row_number`, `sheet_id`, `sheet_name`, `workbook_id`,
`original_path`, `sha256`. Формулы доступны по ссылке на строку, не копируются в каждую страницу.
`date_basis`, `scope_label`, `is_complete_period`, `basis`, `interpretation_confirmed` остаются
явными полями неопределённости. Движения имеют локальные даты без придуманного UTC.

Неверные UUID/границы/фильтры/сортировки → 422, неизвестная таблица/строка → 404,
недоступная БД → 503 без раскрытия строки подключения. API только читает источники:
прогнозов, расчёта заказа, утверждений и сохранения сценариев здесь пока нет.

## English

Run the command above from `backend` with `DATABASE_URL` configured. The factory supports an
injected SQLAlchemy engine for tests and creates no connection at module import. `/docs` and
`/openapi.json` expose the actual contract. The Vite same-origin proxy serves `/api`.

Use `/api/v1/tables` to discover 16 read-only projections and supported columns/filters;
`/api/v1/tables/{table}` returns `{table, items, total, page, page_size}`. Pagination is one-based,
bounded to 200 rows, and ordered by the selected whitelisted column plus unique ID (NULL last).
`q` is a literal case-insensitive substring, not a SQL pattern. Exact optional filters are
listed in each descriptor; unsupported filters return 422. `warehouse_id=unknown` means NULL.

`catalog` returns one row per supplier-scoped identity: `id` equals `product_id`, with exact SKU
and supplier fields only. Names/articles/categories are not arbitrarily selected from conflicting
sources. Use its `product_id` to inspect observations and facts.

`products` rows represent **source observations**, not a canonical merged catalogue. Stable
`product_id` is supplier-scoped; observation `id`, workbook hash, row, sheet, source column and
normalizer version preserve evidence. Specify `workbook_id` and `normalizer_version` to pin a
source; omitted filters expose all versions without summing or deduplicating them. Offset
pagination assumes an unchanged dataset. Search product name/article/category in `products`,
then use `product_id` in fact tables. Decimals are fixed-point strings, unknown values stay NULL,
and local movement timestamps acquire no synthetic timezone. `/api/v1/source-rows/{uuid}`
returns raw cell types, formulas, cached values, errors and provenance; missing keys mean blank.

Workbook binary content is excluded. Date/warehouse uncertainty and interpretation flags remain
visible. Invalid query → 422, missing table/row → 404, database unavailable → 503. This contract
does not claim any forecast, recommended order, approval or scenario-write capability.

Run API regression tests only with `API_TEST_DATABASE_URL` pointing at the dedicated
`replenishment_api_test` database: `uv run pytest tests/test_api.py`. Tests create/drop the
isolated test tables, never use the application database.
