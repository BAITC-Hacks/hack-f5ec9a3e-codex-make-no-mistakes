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
недоступная БД → 503 без раскрытия строки подключения. API читает источники и результаты; запуск расчёта — через CLI или `POST /api/v2/calculation/runs`. Отправка поставщикам не входит в этот контракт.

## English

Run the command above from `backend` with `DATABASE_URL` configured. The factory supports an
injected SQLAlchemy engine for tests and creates no connection at module import. `/docs` and
`/openapi.json` expose the actual contract. The Vite same-origin proxy serves `/api`.

Use `/api/v1/tables` to discover 20 read-only projections and supported columns/filters;
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
visible. Invalid query → 422, missing table/row → 404, database unavailable → 503. The API reads completed forecasts and supplier draft lines; calculation runs are created by CLI or `POST /api/v2/calculation/runs`. Supplier submission remains separate.

Run API regression tests only with `API_TEST_DATABASE_URL` pointing at the dedicated
`replenishment_api_test` database: `uv run pytest tests/test_api.py`. Tests create/drop the
isolated test tables, never use the application database.

## Client delivery recommendations

`GET /api/v1/delivery-planning/demo-input` supplies the real-road Almaty example.
`POST /api/v1/delivery-planning/recommend` returns per-client SKU quantities, proposed
dates, vehicle routes, stock/capacity issues, and the fixed-day versus flexible-day
comparison. This stateless endpoint is separate from supplier purchasing scenarios.
See [input/output contract and runnable example](DELIVERY_PLANNING.md).
# Browser source uploads

The **Источники данных** page uploads XLSX, canonical UTF-8 CSV, or ZIP collections
through `POST /api/v1/sources/upload?filename=...&supplier=iek|systeme` using the
original binary request body (`application/octet-stream`). Supplier is optional
when it can be inferred from the filename/archive path. Maximum upload: 64 MiB;
ZIP: up to 30 XLSX/CSV files, 512 MiB expanded. Nginx permits the same body limit
and allows 15 minutes for synchronous imports.

The response contains `results`, one per workbook: `status` (`imported`, `skipped`,
or `failed`), original path, and on success the persistent `workbook_id`, counts,
and quality warnings. Each workbook commits atomically; a ZIP can therefore
report both committed workbooks and failures. Exact-byte retries are idempotent.
Existing domain writers retain original bytes and provenance; no migration is needed.

`GET /api/v1/sources/template.csv` supplies the exact CSV schema:
`record_type,sku,name,date,quantity,unit,warehouse,document_number,document_text`.
Supported record types: `monthly_sales`, `monthly_stock`, `movements`, `incoming`.
Dates are ISO dates (monthly records require day 01), numbers use a decimal point,
and SKU remains text. Movement rows require unit, warehouse, and both document
fields; original outgoing document classification is preserved. CSV shipments
have explicit expected dates. Missing quantities are rejected rather than made zero.

Persisted records appear through existing table endpoints filtered by `workbook_id`.
`GET /api/v1/sources/export/{table}.csv?workbook_id=...` exports the full selected
observation table with provenance, streaming rows with formula-injection protection.
This audit export has a different schema from the upload template.
The Sources page can prepare an explicit SKU/date/warehouse selection via
`POST /api/v1/planning/source-input` and download its input/provenance JSON.
Unknown stock, warehouse scope, conflicting sources, and missing business policies
remain explicit. After upload the connected workspace refreshes its product,
warehouse and workbook selectors for the existing source-based calculation flow.
## Calculation runs and reads v2 / Запуск и результаты расчёта

- `POST /api/v2/calculation/runs` — synchronously calculate and atomically persist a run from pinned sources.
- `GET /api/v2/calculation/runs` — planning date, pinned sources/versions, status, quality and LLM ledger.
- `GET /api/v2/calculation/calculation-inputs?run_id=<uuid>` — strict per-series snapshots.
- `GET /api/v2/calculation/forecasts?run_id=<uuid>&supplier=systeme` — three dated forecasts per series.
- `GET /api/v2/calculation/drafts?run_id=<uuid>&supplier=iek&state=blocked` — supplier drafts and blockers.
- `GET /api/v2/calculation/runs/<uuid>/export.csv?supplier=systeme` — recommendation-only CSV.

The same `page`, `page_size`, `sort`, `direction`, `q` conventions apply. Result filters additionally
include `run_id`, `series_id`, `supplier`, `scope`, `unit`, `state`, `target_month` where supported by
the descriptor. Results are also registered in `/api/v1/tables` using keys `runs`, `calculation-inputs`,
`forecasts`, `drafts`. Input/forecast/draft queries expose only completed runs; run metadata includes failures.

Forecast `status` (`ok`, `insufficient_data`, `unsupported`) is separate from draft `state`
(`ready`, `estimated`, `blocked`). Quantities use Decimal strings, unknown units/quantities remain NULL.
CSV contains purchase/source units, state, components, assumptions and evidence. Quantities come from
stored values without recomputation; text identifiers are escaped against spreadsheet formula execution.
Failed or unknown runs cannot be exported (404). Export creates no approval and sends nothing to suppliers.

Русский: результаты доступны постранично по run, поставщику и состоянию. Сохранённый прогноз не
означает разрешение закупки; `estimated` содержит допущения, `blocked` — причину отсутствия количества.
CSV — рекомендация, а не утверждённый заказ.

### Create a forecast run / Запуск прогноза

Required JSON fields: `planning_date` and nonempty `source_selection` (at most 1,000 entries).
Each source pins `table`, lowercase 64-character `sha256`, and `normalizer_version`.
The hash/version must have a completed import. At least one `demand_monthly_sales` selection is
required. Accepted tables are listed in the OpenAPI `CalculationSource` schema; add stock, shipment,
quantity-rule and other evidence tables explicitly to include them. Omitted facts remain unknown.
Optional `supplier` is `iek` or `systeme`; omitted means all selected suppliers.
Optional boolean `rerun` defaults to `false`. Unknown fields are rejected.

This example uses the supplied Systeme monthly-sales workbook, after importing it with `v2.3`:

```sh
curl -X POST http://127.0.0.1:8000/api/v2/calculation/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "planning_date": "2026-09-22",
    "supplier": "systeme",
    "source_selection": [{
      "table": "demand_monthly_sales",
      "sha256": "f7782ab9ea5c06d68526543953c6fce7ca83a80d1c1a4e8d88fd083de415f9d0",
      "normalizer_version": "v2.3"
    }]
  }'
```

Response: `{id, status: "completed", reused, fingerprint}`. New runs return **201**;
identical inputs and code versions return **200** with the existing ID and `reused: true`.
`rerun: true` creates a new ID. Read forecasts/drafts using `run_id=<id>` or export with the route above.
Creation waits for calculation to finish; configure the HTTP client's timeout for catalogue-sized runs.
Planning dates must leave all three forecast months within V2's 2000–2099 range.

The API uses the CLI's import checks, repeatable-read input snapshot and atomic persistence with
concurrent duplicate protection. It performs deterministic forecasting; paid LLM pilots remain CLI-only.
Missing imports, empty supplier selections and invalid requests return **422**; database errors return
sanitized **503**. Failed writes expose no completed partial result. No schema migration is needed.

Русский: POST ожидает окончания расчёта; повтор использует сохранённый запуск, `rerun: true`
создаёт новый. Источники и версии задаются явно, оплачиваемые LLM-вызовы не выполняются.
Если выбран только отчёт продаж, отсутствие запасов и единиц сохраняется как блокировка закупки.


## Employee order documents (V2)

Employee UUIDs are demo attribution, **not authentication**. Any existing employee may edit or approve.
One document covers every supplier in one completed, nonempty run. Creation is idempotent by `run_id`:
repeating it returns the current document unchanged, including edits or approval.

| Method and path | Input / result |
| --- | --- |
| `GET /api/v2/employees` | Array of `{id, display_name}` |
| `POST /api/v2/order-documents` | `{run_id, employee_id}` → full document |
| `GET /api/v2/order-documents` | `page=1`, `page_size=50` (max 200), optional `run_id`, `status=editable\|approved`; returns `{items,total,page,page_size}` |
| `GET /api/v2/order-documents/{id}` | Full document, employee attribution, run provenance, original recommendations, input snapshots, forecasts, edits, revision |
| `PATCH /api/v2/order-documents/{id}` | `{employee_id, expected_revision, note?, lines?: [{id, quantity?, purchase_unit?, included?, manual_completion_reason?}]}` |
| `POST /api/v2/order-documents/{id}/approve` | `{employee_id, expected_revision}` → permanently locked document |

All Decimal quantities in responses are strings. Send quantities as strings to preserve precision.
Quantities must be finite, nonnegative, less than `1e18`, and exactly representable with 12 decimal places.
Confirmed minimum/multiple rules apply in their recorded purchase unit; zero is allowed.
Unknown rules and conversions are never inferred. Supplier, SKU, scope, and original known purchase units
cannot be edited. A missing purchase unit may be supplied explicitly.

Documents start at revision 1, with every line included. Each successful edit/approval increments revision.
Omitted fields remain unchanged; `note: null` clears the note. Quantity and unit cannot be cleared.
Blocked lines start without quantity; employees may save partial work, but approval requires an explicit
quantity, purchase unit, and nonblank manual-completion reason for every included blocked line.
Original blockers remain visible under `lines[].recommendation`; the reason records employee responsibility,
not a recalculation or a claim that missing evidence became known. Estimated recommendations remain eligible,
with assumptions disclosed. At least one included quantity must be positive.

Full reads include `creator`, `last_editor`, `approver` identities and their `_id` fields; creation initializes
last editor, edits update it, and approval records its own approver and timestamp. Each line contains employee
fields plus `recommendation`, `input` (including `snapshot`), and `forecasts`. Original calculation rows and
recommendation CSV exports remain unchanged. PATCH is atomic, including validation failures partway through.
The document row lock and expected revision serialize edit/approval; only one can succeed at a given revision.
PostgreSQL guards additionally reject updates/deletes of approved documents and changes to their lines.

Errors: missing employee/run/document/line (including a line belonging to another document) → 404;
invalid fields, quantities, rules, incomplete approval, or no positive included quantity → 422;
stale revision, unfinished/empty run, repeated approval, or editing approved documents → 409;
database failures → sanitized 503 `{"detail":"Database unavailable"}`. Duplicate line IDs in a PATCH are invalid.

### Synthetic demo: seed → create → edit → approve

From `backend/`, with `DATABASE_URL` set, run migrations before the seed:

```sh
uv run alembic upgrade head
uv run python -m replenishment.cli.seed_demo
uv run uvicorn replenishment.api.app:create_app --factory --port 8000
```

The seed prints stable run and employee IDs, inserts two clearly synthetic employees and three lines across
two synthetic suppliers (ready, estimated, blocked), plus input snapshots and nine forecasts. No workbooks,
network inference, or real supplier records are required. One transaction inserts missing fixture rows;
replay never updates existing rows or employee edits. The seed intentionally does not create a document.

In another terminal from `backend/`, run this complete API example (Python standard library only):

```sh
uv run python - <<'PYTHON'
import json
from urllib.request import Request, urlopen
from replenishment.cli.seed_demo import EMPLOYEE_IDS, RUN_ID

def call(path, body=None, method="GET"):
    request = Request("http://127.0.0.1:8000/api/v2" + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"}, method=method)
    with urlopen(request) as response:
        return json.load(response)

print(call("/employees"))
doc = call("/order-documents", {"run_id": str(RUN_ID),
                              "employee_id": str(EMPLOYEE_IDS[0])}, "POST")
path = "/order-documents/" + doc["id"]
if doc["status"] != "approved":
    first, second, blocked = doc["lines"]
    doc = call(path, {
        "employee_id": str(EMPLOYEE_IDS[1]), "expected_revision": doc["revision"],
        "note": "Reviewed synthetic demo",
        "lines": [
            {"id": first["id"], "quantity": "20"},
            {"id": second["id"], "included": False},
            {"id": blocked["id"], "quantity": "3", "purchase_unit": "box",
             "manual_completion_reason": "Supplier confirmed three demo boxes"},
        ],
    }, "PATCH")
    doc = call(path + "/approve", {"employee_id": str(EMPLOYEE_IDS[0]),
                                    "expected_revision": doc["revision"]}, "POST")
print(json.dumps(call(path), indent=2))
PYTHON
```

After approval, every further PATCH/approval returns 409. Rerunning the seed preserves that approval.
