# Supplied data guide

Inventory from read-only inspection on 2026-09-23. The original workbook files are unchanged. This is a structural overview, not a full data-quality audit.

The subsequent full [data audit (Russian)](DATA_AUDIT.md) covers all 12 workbooks and 14 sheets, with actual row counts, join coverage, inconsistencies, and a suggested demo scenario. Its findings supersede the preliminary availability questions below.

## Workbook inventory

Paths are relative to `docs/data/`. Dimensions are worksheet-reported rows × columns, including headers and possible blank/formatted cells.

| Supplier folder | Workbook | Sheets and dimensions |
| --- | --- | --- |
| IEK | MOQ  ИЭК.xlsx | Лист7: 1,939 × 5 |
| IEK | Динамика продаж_2025-2026.xlsx | Лист_1: 171,605 × 8 |
| IEK | Ежемесячные остатки продукции за последние 2 года  ИЭК.xlsx | Лист_1: 2,857 × 37 |
| IEK | Ежемесячные продажи в количественном выражении за последние 2 года.xlsx | Лист_1: 2,466 × 36 |
| IEK | Путь ИЭК 22.09.2026.xlsx | Лист4: 2,642 × 9 |
| IEK | Сезонность ИЭК.xlsx | Сезонность: 41 × 15 |
| Systeme electric | MOQ SystemElectric.xlsx | Лист_1: 557 × 5 |
| Systeme electric | Динамика продаж_Syseme Electric_2025-2026.xlsx | Лист_1: 77,314 × 8 |
| Systeme electric | Ежемесячные остатки SystemElectric 2024-2026.xlsx | Лист_1: 704 × 37 |
| Systeme electric | Ежемесячные продажи в кол-м выражении SystemElectric 2024-2026.xlsx | Лист_1: 557 × 38; Лист1: 35 × 15 |
| Systeme electric | Сезонность SystemElectric 2024-2026.xlsx | Лист1: 35 × 15 |
| Systeme electric | Товар в пути_SystemElectric на 22.09.2026.xlsx | TDSheet: 499 × 70; Лист1: 23 × 15 |

See [workbook-inventory.json](sources/workbook-inventory.json) for exact source paths, worksheet names, dimensions, and initial rows.

## Observed structure and import caveats

- **Sales dynamics:** both files have `Дата`, `Номер`, `Документ`, `Код`, `Номенклатура`, `Ед.`, `Склад`, `Количество` in A1:H1. No explicit customer ID or price column is present in those headers. Document numbers must not be assumed to identify customers.
- **Dates and signs:** IEK sales rows 2–15 include 2023 dates despite the filename's 2025–2026 label, and negative quantities for outgoing invoices. Determine actual date coverage and transaction semantics before converting quantities to demand; do not blindly take absolute values.
- **SKU joins:** preserve codes as strings, including leading zeros, Cyrillic prefixes, and trailing underscores. Code headers vary between `Код`, `Код 1с`, and `Номенклатура.Код`. Supplier article numbers are separate identifiers.
- **Monthly reports:** columns run from January 2024 through September 2026. Some reports also contain `Итого` totals and multiple header rows. Unpivot month columns, keeping totals out of the time series. Confirm how blanks and the partial September period should be treated.
- **Stock:** IEK's first three header rows label monthly quantities as `нач. остаток` (opening balance). Monthly snapshots cannot establish the exact duration of stockouts or today's available stock.
- **MOQ:** IEK labels its quantity `Мин. разр. к отгр.`; Systeme Electric uses `Кратность`. Confirm the distinction between shipment minimum and order multiple before rounding recommendations.
- **Transit:** IEK has SKU/article/name columns followed by six shipment columns whose headers include anticipated arrival dates. Some product names explicitly distinguish purchasing cable in coils from stocking it in meters. Systeme Electric's `TDSheet` contains 497 SKU rows, category codes (E), calculated growth/seasonality changes (AR:AS), stock/reserved/free stock (AX:AZ), and transit (BC). Warehouse scope needs confirmation: AT:AW do not generally sum to AX. The apparent 12-month sum in AP actually spans 13 months in the inspected formula.
- **Seasonality:** separate worksheets have year/month summary layouts rather than transaction headers. Confirm their units and calculation definitions before applying any factors to SKU quantities. Supplementary sheets also exist inside two Systeme Electric workbooks; do not silently ignore them or assume they are duplicates.

## Inputs still requiring confirmation

The files provide sales movements, monthly sales and stock reports, MOQ/multiple information, seasonality reports, and transit reports. Full inspection found category codes, historical growth calculations, and stock/reserved/free-stock fields for Systeme Electric in its transit workbook. Their business definitions, snapshot date, and warehouse scope require confirmation; there is no equivalent current snapshot identified for IEK. A dedicated lead-time directory, anonymized customer mapping, exact stockout intervals, independent growth forecast, and 1C bill of materials were not found in the 14 sheets.

See the full audit for measured coverage and limitations. Resolve the remaining business-definition questions before treating the supplied data as sufficient for every requirement in the brief.
