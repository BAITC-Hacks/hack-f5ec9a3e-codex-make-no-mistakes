# Качество данных / Data quality

Результат сверки / Reconciliation: **PASS**.
Время / Generated: 2026-09-23T10:14:15.505124+00:00. Версия / Version: v1.
Книг / Workbooks: 12; листов / sheets: 14.

PASS означает совпадение проверенных полей, а не пригодность данных для прогноза.
PASS means agreement within the stated coverage, not forecast readiness.

## Типизированные наблюдения / Typed observations

| Table | Rows |
|---|---:|
| supply_quantity_rules | 3046 |
| demand_movements | 248915 |
| inventory_monthly_stock | 117282 |
| demand_report_metrics | 10840 |
| demand_monthly_sales | 115962 |
| supply_shipment_lines | 16235 |
| demand_seasonality_observations | 725 |
| inventory_observations | 3479 |

## Сверка по листам / Per-sheet reconciliation

| File / sheet | Raw rows | Result |
|---|---:|---|
| MOQ  ИЭК.xlsx / Лист7 | 1939 | PASS |
| Динамика продаж_2025-2026.xlsx / Лист_1 | 171605 | PASS |
| Ежемесячные остатки продукции за последние 2 года  ИЭК.xlsx / Лист_1 | 2857 | PASS |
| Ежемесячные продажи в количественном выражении за последние 2 года.xlsx / Лист_1 | 2466 | PASS |
| Путь ИЭК 22.09.2026.xlsx / Лист4 | 2642 | PASS |
| Сезонность ИЭК.xlsx / Сезонность | 35 | PASS |
| MOQ SystemElectric.xlsx / Лист_1 | 556 | PASS |
| Динамика продаж_Syseme Electric_2025-2026.xlsx / Лист_1 | 77314 | PASS |
| Ежемесячные остатки SystemElectric 2024-2026.xlsx / Лист_1 | 702 | PASS |
| Ежемесячные продажи в кол-м выражении SystemElectric 2024-2026.xlsx / Лист_1 | 557 | PASS |
| Ежемесячные продажи в кол-м выражении SystemElectric 2024-2026.xlsx / Лист1 | 19 | PASS |
| Сезонность SystemElectric 2024-2026.xlsx / Лист1 | 19 | PASS |
| Товар в пути_SystemElectric на 22.09.2026.xlsx / TDSheet | 499 | PASS |
| Товар в пути_SystemElectric на 22.09.2026.xlsx / Лист1 | 19 | PASS |

## Ограничения проверки / Coverage limits

Все координаты числовых наблюдений сверены независимо через openpyxl; проверены SKU, месяцы, NULL, знаки и суммы. Оригинальные байты и множество непустых строк проверены полностью.
All numeric observation coordinates, SKU, monthly dates, NULLs, signs and sums are independently reconciled via openpyxl; original bytes and nonempty row membership are checked.

- Openpyxl float decoding: fractional tolerance 1e-8, integer values exact; total tolerance is number of observations times 1e-8. Original workbook bytes checked exactly.
- Large seasonal totals use independent XML decimal lexemes, avoiding openpyxl float loss.
- Raw row membership checked; individual JSONB cell contents/formulas/formats not re-compared.
- Typed numeric coordinates, SKU, monthly dates checked. Movement timestamps/documents/units, catalog attribute text, metric labels, seasonal year/month/basis and shipment dates not reconciled.
- No forecast accuracy, UI/API behavior or business correctness certification; source issues remain.
- Audit selected files/version only; other source versions may coexist in the database.

## Проблемы источников / Source issues

Отрицательные движения, ошибки Excel, пропуски и неизвестный складской охват сохраняются. Они не являются ошибками импорта. Повторяющиеся сводки нельзя суммировать. Полные распределения и замечания по листам находятся в JSON.
Negative movements, Excel errors, missing values and unknown warehouse scope remain source limitations, not import failures. Overlapping summaries must not be summed. See JSON for details.

Независимый подсчёт в Excel / Independent Excel counts:

- movements_count: 248915
- movements_negative: 417
- movements_null: 31
- movements_zero: 0
- average_formula_not_divided_by_12: 1
- duplicate_sku_rows: 8
- excel_errors: 73497
- formula_cache_missing: 0
- stock_components_differ_from_total: 493
- stock_identity_mismatch: 0
- thirteen_month_formula: 497
- unknown_warehouse_scope: 7068

Замечания уже записанные импортёром / Findings recorded by the importer (не независимая проверка / not independent validation):

- duplicate_sku: 2 DB findings
- excel_error: 1 DB findings
- inconsistent_average_formula: 1 DB findings
- missing_movement_quantity: 2 DB findings
- negative_movement: 2 DB findings
- nonpositive_quantity_rule: 1 DB findings
- numeric_rounding: 5 DB findings
- overlapping_seasonality_sources: 3 DB findings
- relative_change_not_multiplier: 1 DB findings
- stock_scope_overlap: 1 DB findings
- supplier_aggregate_only: 4 DB findings
- thirteen_month_total: 1 DB findings
- unknown_shipment_year: 1 DB findings
- unknown_warehouse_scope: 5 DB findings
- unstructured_unit_conversion: 1 DB findings

## Ошибки сверки / Reconciliation failures

Нет / None.
