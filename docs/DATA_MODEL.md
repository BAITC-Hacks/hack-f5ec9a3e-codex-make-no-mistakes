# Excel → PostgreSQL

## Русский

Схема v1 покрывает данные всех **12 книг и 14 листов**. Это модели и миграция; массовый импорт ещё не реализован. Оригинальные файлы сохраняются целиком в `intake_workbooks`, поэтому «покрытие» не означает, что неизвестным полям приписан выдуманный смысл.

Для каждого листа — `intake_sheets`, для каждой непустой строки, включая шапки, итоги и служебные подписи, — `intake_rows`. Пустые/неизвестные поля остаются NULL; тип и ошибка ячейки доступны через исходную строку. Указанные ниже короткие имена сопоставляются с полными путями в [инвентаре](sources/workbook-inventory.json).

### Покрытие листов

| Книга / лист | Типизированные данные |
| --- | --- |
| IEK MOQ / Лист7 | B код → `catalog_products`; C артикул, D имя → `catalog_product_observations`; E → `supply_quantity_rules` (`minimum_shipment`, смысл не подтверждён). A номер сохраняется в сырье. Ошибки E остаются ошибками сырья, типизированное значение NULL. |
| IEK динамика / Лист_1 | A дата, B номер, C документ, D код, E имя, F единица, G склад, H подписанное количество → `demand_movements` + каталог/наблюдения названия/единицы. |
| IEK месячные остатки / Лист_1 | A имя, B единица, C код → каталог; D:AJ → `inventory_monthly_stock` (`opening_stock`); AK итог → `demand_report_metrics` (`stock_total`, только отчётное значение). |
| IEK месячные продажи / Лист_1 | A имя, B код → каталог; C:AI → `demand_monthly_sales`; AJ итог → `demand_report_metrics` (`sales_total`). |
| IEK путь / Лист4 | A код, B артикул, C имя → каталог; шапки D:I → `supply_shipments`, значения D:I → `supply_shipment_lines`. Служебные строки без SKU остаются в сырье. |
| IEK сезонность / Сезонность | Годовые/месячные суммы, средние, нормированные и прогнозные коэффициенты → `demand_seasonality_observations` с годом/месяцем, подписью, типом показателя и основанием. Все вспомогательные формулы сохраняются в сырье. |
| Systeme MOQ / Лист_1 | B имя, C код, D артикул → каталог; E кратность → `supply_quantity_rules` (`order_multiple`). A порядковый номер — сырьё. |
| Systeme динамика / Лист_1 | Те же A:H, что в IEK → `demand_movements` + каталог. |
| Systeme месячные остатки / Лист_1 | A номер — сырьё; B имя, C код, D единица → каталог; E:AK → `inventory_monthly_stock` (`stock_unspecified`). |
| Systeme месячные продажи / Лист_1 | A имя, B код, C артикул → каталог; D кратность → отдельное наблюдение `supply_quantity_rules`; E:AK → `demand_monthly_sales`; AL итог → `demand_report_metrics`. Не затирать конфликт кратности с отдельным MOQ. |
| Systeme месячные продажи / Лист1 | `demand_seasonality_observations`; самостоятельное происхождение, не независимое дополнительное измерение спроса. |
| Systeme сезонность / Лист1 | `demand_seasonality_observations`, включая итоговые коэффициенты L и поправку N15. |
| Systeme товар в пути / TDSheet | Подробная карта ниже. |
| Systeme товар в пути / Лист1 | `demand_seasonality_observations`; дубликат сводки в месячных продажах сохраняется, но не суммируется с ней. |

### Systeme TDSheet: все колонки

| Колонки | Модель и смысл |
| --- | --- |
| A | Порядковый номер в `intake_rows`, не ID товара |
| B:D | Артикул, код 1С, наименование → `catalog_products` + `catalog_product_observations` |
| E | `catalog_product_observations.category_code/category_year`; код категории 2026, без выдуманной расшифровки |
| F | `demand_report_metrics.cost_unspecified`, подпись «СС реал»; не цена сделки, валюта неизвестна |
| G:R, U:AO | Месячные продажи → `demand_monthly_sales`; отдельные наблюдения от другой месячной книги |
| S:T | `demand_report_metrics.sales_total/sales_average`, период 2024 |
| AP:AQ | `demand_report_metrics.sales_total/sales_average`; хранить исходную подпись и формулу. Фактический диапазон AP содержит 13 месяцев, не исправлять источник |
| AR:AS | `demand_report_metrics.growth_change/seasonality_change`; относительные изменения, не готовые множители |
| AT:AW | `inventory_observations`: showroom/trading_area/distribution_center/retail; сохранять исходные подписи и неизвестный складской охват |
| AX:AZ | `inventory_observations`: on_hand/reserved/free; не суммировать компоненты между собой |
| BA | `demand_report_metrics.coverage_unspecified`; готовая формула «Запас», бизнес-смысл требует подтверждения |
| BB | `demand_report_metrics.planned_order`, если появится значение; сейчас колонка пуста |
| BC | `supply_shipments` + `supply_shipment_lines`; «24.09» без года — исходная строка заголовка, `expected_on=NULL`, пока год не выбран явно с `date_basis=assumed_year` |
| BH | `demand_report_metrics.weight_unspecified`, если появится значение; сейчас пуста |
| BD:BG, BI:BR | Пустые/форматированные области и любые будущие неизвестные ячейки остаются в оригинале и сырье; автоматическая бизнес-интерпретация запрещена |

### Идентичность, версии и качество

`catalog_products` содержит только стабильную пару поставщик + строковый SKU. Имена, артикулы, категории и единицы имеют происхождение в `catalog_product_observations`. Это сохраняет расхождения и не создаёт лишние товары из-за дубликатов MOQ.

`intake_findings` хранит код проблемы, стабильный ключ внутри книги, координаты/значения доказательства, описание, статус и решение. Начальные выводы закреплены в [DATA_AUDIT.md](DATA_AUDIT.md), [audit-baseline.json](sources/audit-baseline.json) и тестах. Их перенос в БД выполняется вместе с будущим импортом.

Уникальность нормализованного наблюдения задаётся строкой, колонкой (где применимо) и версией нормализатора. Это не разрешает суммировать все источники и версии. Канонический источник и выбор версии для расчёта — отдельные правила следующей задачи.

Отсутствующие customer ID, stockout-интервалы, нормативные lead time, BOM и конверсии единиц не заполнены синтетическими значениями. Таблицы будущих пользовательских сценариев и результатов расчёта добавятся отдельной миграцией; их входы должны иметь происхождение «пользователь/допущение/синтетика», а не маскироваться под Excel.

## English

Schema v1 covers all **12 workbooks and 14 sheets** through complete XLSX evidence plus typed observations. Models and migration are implemented; bulk ingestion is not. Every sheet and nonempty row, including headers, totals and notes, has a raw evidence location. Blank, zero, error and formula-result states remain distinguishable.

Sheet mapping:

- Both sales-dynamics sheets map A:H to dated, signed `demand_movements`, product observations and warehouse identity.
- IEK monthly sales C:AI and Systeme monthly sales E:AK map to `demand_monthly_sales`; their totals remain report metrics.
- IEK monthly stock D:AJ maps to opening stock; Systeme E:AK maps to stock with unspecified snapshot semantics in `inventory_monthly_stock`. Unknown warehouse scope remains NULL.
- Both MOQ sheets map to `supply_quantity_rules`; Systeme monthly-sales D remains a separate, potentially conflicting rule observation. Original duplicate rows and Excel errors remain evidence.
- IEK shipment headers D:I map to `supply_shipments`; their SKU quantities map to `supply_shipment_lines`.
- All four seasonal sheets (IEK standalone, Systeme standalone and two embedded sheets) map to `demand_seasonality_observations`, retaining year/month, metric, label, value and reported/derived/forecast/unknown basis. Repeated summaries must not be double-counted.
- Every source code/name/article/unit/category maps to supplier-scoped `catalog_products` and provenance-bearing `catalog_product_observations`. Source row numbers are not product IDs.

Systeme `TDSheet` mapping: A stays raw; B:D identify article/SKU/name; E records category code/year; F records an unknown cost metric; G:R and U:AO record monthly sales; S:T and AP:AQ record supplied totals/averages; AR:AS record growth/seasonality changes; AT:AW record separate stock components; AX:AZ record on-hand/reserved/free stock; BA records reported coverage; BB records planned order when present; BC records incoming shipment quantities with an explicitly uncertain year; BH records weight when present. Other blank/formatted regions remain in original evidence. The thirteen-month formula is retained as source evidence, not adopted as policy.

Workbook bytes are SHA-256 pinned and immutable. Typed observations link to source row/column and normalizer version. Product identity is supplier + exact string SKU; conflicting source attributes are preserved rather than overwritten. `intake_findings` records scoped issue keys, evidence, status and resolution. Audit baseline findings will be loaded when ingestion is implemented.

Source uniqueness prevents replay duplicates, but is not a rule for selecting the authoritative source. Future calculations must explicitly select and pin versions. Missing customer IDs, exact stockout intervals, lead-time directories, BOM and unit conversions are not invented. Scenario/override and calculation-result tables will be a separate migration, with user/assumed/synthetic inputs explicitly distinguished from Excel evidence.
