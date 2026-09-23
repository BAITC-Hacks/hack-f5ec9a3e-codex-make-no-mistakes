# Импорт Excel / Excel ingestion

## Русский

Из `backend`, после установки зависимостей (`uv sync`) и задания `DATABASE_URL`:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment'
uv run alembic upgrade head
uv run python -m replenishment.cli.import_excel ../docs/data
```

Один файл: `uv run python -m replenishment.cli.import_excel "путь/файл.xlsx" --supplier iek`.
Поставщик определяется по пути (`IEK`/`ИЭК`, `Systeme`/`SystemElectric`/`Syseme`); для неоднозначного имени
обязателен `--supplier iek|systeme`. Явный параметр, конфликтующий с путём, отклоняется. Каталог обходится
детерминированно, временные файлы `~$` пропускаются. Поддерживаются предоставленные шаблоны XLSX,
а не произвольные Excel: неизвестная шапка или некорректная обязательная дата откатывает **всю книгу**.
Ранее успешно импортированные книги при ошибке следующей сохраняются.

Версия нормализатора по умолчанию — `v1`. Импорт одинаковых байтов и версии пропускается;
`--normalizer-version <новая-версия>` добавляет новый набор наблюдений, повторно используя неизменяемое сырьё.
Не меняйте версию ради повторного запуска: расчёт и интерфейс должны выбирать конкретную версию,
а не суммировать версии. Изменённые байты создают отдельную книгу. Перенос идентичных байтов в другую
папку не создаёт новый источник; первый `original_path` сохраняется. Одинаковые сводки в разных книгах
остаются отдельными наблюдениями. Повторяющиеся SKU не размножают идентичность товара.

Каждая книга загружается одной транзакцией. PostgreSQL advisory lock сериализует импортеры;
повторный параллельный запуск безопасен. В `intake_findings` запись `import_complete` — внутренний
маркер завершения версии, **не дефект данных**. Остальные замечания содержат количество случаев и
до 20 примеров координат; все исходные случаи доступны в сырье. Новая версия нормализатора
получает отдельные замечания качества.

### Сохранение данных

- В БД сохраняются исходные XLSX-байты, SHA-256, листы, непустые строки и неизвестные колонки.
  Заголовки, итоги и служебные строки остаются в сырье. Стили/объекты полностью остаются в оригинале;
  адресуемые сведения включают объединения, видимость, размеры колонок и особые параметры строк.
- OOXML читается потоково; числовые лексемы берутся непосредственно из XML, без преобразования
  через `float`. Формулы, параметры массивов/shared formulas, кеши, ошибки, форматы чисел сохраняются.
  Формулы не исполняются, ссылки на внешние книги не открываются.
- `Numeric(30,12)` округляется явно; потеря десятичных знаков регистрируется как `numeric_rounding`.
  XML-лексемы и исходные байты сохраняют полную точность. Числа вне диапазона откатывают книгу.
- В месячных диапазонах создаётся наблюдение для каждой пары SKU/месяц, включая NULL.
  В поставках сохраняются и пустые количества; число строк поставок не означает число положительных поставок.
  Ошибка Excel, пустота, отрицательное число и ноль не подменяются друг другом.
- Склад месячных отчётов/текущего снимка неизвестен (`NULL`); «Алматы» относится к движениям.
  Текущий снимок датируется именем файла с `date_basis=filename`. Год Systeme BC не придумывается:
  `expected_on=NULL`, `date_basis=unknown`. Даты IEK разбираются из заголовков как `explicit`.
- Готовые коэффициенты/итоги не становятся алгоритмом заказа. Данные о клиентах, lead time,
  stockout, BOM и конверсии единиц не создаются. Сводки сезонности не суммируются автоматически.

Пакеты ограничены 500 исходными строками. Месячные наблюдения создаются внутри этого пакета;
память не зависит линейно от количества движений. Исходные сжатые байты, общий словарь строк XLSX,
малый справочник SKU/складов и метаданные листа хранятся в памяти. Это CLI для локальных доверенных
файлов; загрузка произвольных файлов через HTTP в этот срез не входит.

### Проверенный импорт исходного набора, 2026-09-23

| Таблица / Table | Строки / Rows |
| --- | ---: |
| `intake_workbooks` | 12 |
| `intake_sheets` | 14 |
| `intake_rows` | 261 229 |
| `catalog_suppliers` | 2 |
| `catalog_products` | 3 909 |
| `catalog_warehouses` | 1 |
| `catalog_product_observations` | 261 098 |
| `demand_movements` | 248 915 |
| `demand_monthly_sales` | 115 962 |
| `inventory_monthly_stock` | 117 282 |
| `inventory_observations` | 3 479 |
| `supply_quantity_rules` | 3 046 |
| `supply_shipments` | 7 |
| `supply_shipment_lines` | 16 235 |
| `demand_report_metrics` | 10 840 |
| `demand_seasonality_observations` | 725 |
| `intake_findings` | 43 (31 замечание + 12 маркеров / 31 findings + 12 markers) |

IEK: 171 603 движения, 115 отрицательных, 18 NULL. Systeme: 77 312, 302 отрицательных, 13 NULL.
Эти числа совпали с закреплённым аудитом. Повторный запуск пропустил все 12 книг; количество строк
**во всех 17 таблицах** осталось прежним. SKU `300200745_`: свободный остаток 23, транзит 120,
неизвестные склад и год поставки сохранены. Хеши всех 12 сохранённых оригиналов совпали с файлами.

Проверки: `uv run pytest tests/test_excel_import.py -q`. Для PostgreSQL-проверок задайте
`IMPORT_TEST_DATABASE_URL` на отдельную БД с именем, заканчивающимся `_import_test`.
Тесты создают схему при отсутствии миграции, добавляют уникальные тестовые данные, не удаляют данные
и не очищают прикладную БД. Проверяются точность XML, кеши/ошибки/пустоты, все 14 шаблонов,
конкурентный импорт, новая версия нормализатора, атомарный откат и реальный снимок Systeme.

## Независимая сверка / Independent reconciliation

После импорта выполните из `backend` с тем же `DATABASE_URL`:

```powershell
uv run python -m replenishment.cli.audit_data ../docs/data --output-dir ../docs/reports
```

Проверка читает PostgreSQL в транзакции только для чтения и независимо читает исходные XLSX через
openpyxl; точные числовые значения сезонных сводок дополнительно читает из XML внутри XLSX.
Она не исправляет файлы или БД. Результат — `data-quality.json` и `data-quality.md`.
Ошибки переноса данных завершают команду ненулевым кодом; предупреждения о дефектах исходных
данных отделены от ошибок импорта. Точное покрытие и ограничения перечислены в отчёте.

Run the command above after importing, using the same `DATABASE_URL`. The auditor independently
reads source XLSX through openpyxl (plus exact seasonal numeric XML values) and uses a read-only
PostgreSQL transaction; it never repairs
source files or database records. JSON and Markdown reports separate import correctness failures
(nonzero exit) from source-quality warnings. Consult the report for actual coverage and limitations.
CI runs migration, full import and this audit against a fresh isolated database and uploads the reports.

## English

From `backend`, set `DATABASE_URL`, run `uv sync`, apply `uv run alembic upgrade head`, then:

```sh
uv run python -m replenishment.cli.import_excel ../docs/data
# A single ambiguously named workbook requires an explicit supplier:
uv run python -m replenishment.cli.import_excel /path/file.xlsx --supplier systeme
```

The importer supports the supplied XLSX templates and rejects unknown headers. Directory discovery is
deterministic and ignores Excel lock files. Each workbook is atomic; an error rolls back that workbook,
not previously committed workbooks. A PostgreSQL advisory lock serializes imports. Identical SHA-256
and normalizer version (`v1` by default) skip cleanly, including concurrent reruns. A deliberately new
`--normalizer-version` appends observations while reusing immutable evidence. Different bytes create
a new source; identical bytes at another path reuse the first source. Consumers must select versions,
never sum them. Completion markers in `intake_findings` are bookkeeping, not data quality defects.

All original bytes, populated source rows, extra columns, formulas and cached values/errors are retained.
Numeric XML lexemes are read directly, avoiding binary-float precision loss; normalized decimals use
12 places and report rounding. Formula execution/external link fetching is never performed. Empty
monthly/shipment cells produce nullable observations, not invented zeros. Duplicate source rows retain
separate provenance without duplicating product identities. Warehouse scope and missing shipment year
remain unknown. No customer IDs, lead times, stockout durations, BOM or unit conversions are fabricated.
Spreadsheet coefficients remain observations, not replenishment rules.

Streaming batches contain 500 source rows; complete movement sheets are never materialized. Original
compressed bytes, the XLSX shared-string dictionary, source layout and small identity maps stay in memory.
This is a trusted-local-file CLI, not an HTTP file-upload service. Findings count all occurrences and retain
up to 20 coordinate examples; complete source evidence remains queryable.

The table above records the successful real PostgreSQL import. All 248,915 movements match the frozen
audit sign/missingness counts. A second full run skipped all 12 sources and left every table count unchanged.
All 12 retained originals match source hashes. Six tests cover precise raw capture, every supplied template,
concurrent replay, normalizer versions, workbook rollback and actual Systeme stock/transit provenance.
Run `uv run pytest tests/test_excel_import.py -q`; PostgreSQL tests use `IMPORT_TEST_DATABASE_URL` pointing
to a dedicated database ending `_import_test`. They migrate an empty schema and append unique fixtures;
they never reset or delete application data.
