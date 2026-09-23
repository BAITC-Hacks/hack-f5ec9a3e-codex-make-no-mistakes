"""Atomic, idempotent Excel source ingestion. Run with DATABASE_URL and a file/directory."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from itertools import chain, islice
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine

from replenishment.catalog import writing as catalog
from replenishment.demand import writing as demand
from replenishment.intake import writing as intake
from replenishment.intake.adapters.normalization import (
    classify,
    mapping_from_payload,
    number,
    observations,
    seasonality,
    shipment_header,
    value,
)
from replenishment.intake.adapters.xlsx import Workbook
from replenishment.inventory import writing as inventory
from replenishment.schema import metadata  # noqa: F401 -- assemble FK metadata at the composition root
from replenishment.supply import writing as supply

BATCH_SIZE = 500
NORMALIZER_VERSION = "v2.3"


def supplier_for(path, override=None):
    text = str(path).lower()
    inferred = (
        "iek"
        if "iek" in text or "иэк" in text
        else ("systeme" if any(s in text for s in ("system", "syseme")) else None)
    )
    if override and inferred and override != inferred:
        raise ValueError(f"Supplier override conflicts with source path: {path}")
    if not (override or inferred):
        raise ValueError(f"Cannot infer supplier from {path}; pass --supplier iek|systeme")
    return override or inferred


def discover(path):
    if not path.exists():
        raise ValueError(f"Source path does not exist: {path}")
    files = [path] if path.is_file() else sorted(path.rglob("*.xlsx"), key=lambda p: str(p).casefold())
    files = [p for p in files if not p.name.startswith("~$")]
    if not files or any(p.suffix.lower() != ".xlsx" for p in files):
        raise ValueError("Expected an .xlsx file or directory containing .xlsx files")
    return files


def _mapping_context(sheet, prefix, sample=()):
    cells = []
    for row, values in prefix:
        for column, cell in values.items():
            current = cell.get("cached_value") if cell.get("type") == "f" else cell.get("value")
            cells.append(
                {
                    "cell": f"{column}{row}",
                    "value": current,
                    "formula": cell.get("formula"),
                    "type": cell.get("cached_type", cell.get("type")),
                }
            )
    sample_cells = []
    for row, values in sample:
        for column, cell in values.items():
            current = cell.get("cached_value") if cell.get("type") == "f" else cell.get("value")
            sample_cells.append(
                {
                    "cell": f"{column}{row}",
                    "value": current,
                    "formula": cell.get("formula"),
                    "type": cell.get("cached_type", cell.get("type")),
                }
            )
    return {
        "sheet": sheet.name,
        "available_cells": [item["cell"] for item in cells],
        "header_cells": cells,
        "representative_cells": sample_cells,
        "merged_ranges": sheet.layout.get("merged_ranges", []),
    }


def _resolve_sheet_mapping(headers, supplier, *, sheet=None, prefix=(), sample=(), llm=None, resolver=None):
    try:
        return classify(headers, supplier), None
    except ValueError as deterministic_error:
        if resolver is not None:
            result = resolver(headers, supplier)
            if isinstance(result, dict):
                result = mapping_from_payload(result, headers, supplier)
            if result is None:
                raise deterministic_error
            return result, "injected"
        if llm is None:
            return None, str(deterministic_error)
        from replenishment.calculation.llm import extract_mapping

        context = _mapping_context(sheet, prefix, sample)
        result = extract_mapping(
            llm, context, validator=lambda payload: mapping_from_payload(payload, headers, supplier)
        )
        if not result.ok or result.value is None:
            return None, result.error or "mapping_failed"
        try:
            return mapping_from_payload(result.value, headers, supplier), result.model or "llm"
        except ValueError as error:
            return None, str(error)


def import_workbook(
    engine, path, supplier=None, version=NORMALIZER_VERSION, *, llm=None, mapping_resolver=None
):
    path = Path(path)
    supplier = supplier_for(path, supplier)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version):
        raise ValueError("Normalizer version must be a nonempty stable identifier")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    # Avoid parsing or paid mapping calls for an already committed hash/version.
    # Recheck under the write lock below to handle concurrent importers.
    with engine.connect() as connection:
        _, complete = intake.existing_workbook(connection, digest, version, supplier)
    if complete:
        return {"path": str(path), "sha256": digest, "status": "skipped", "normalizer_version": version}
    counts = Counter()
    findings = {}
    book = Workbook(content)
    try:
        # Resolve every worksheet before opening the database write transaction.
        # Paused row generators are reused below, so the workbook is parsed once.
        prepared = []
        for sheet in book.sheets:
            iterator = book.rows(sheet)
            prefix = list(islice(iterator, 40 if sheet.rows < 100 else 3))
            sample = list(islice(iterator, 3)) if sheet.rows >= 100 else []
            headers = dict(prefix)
            mapping, mapping_source = _resolve_sheet_mapping(
                headers,
                supplier,
                sheet=sheet,
                prefix=prefix,
                sample=sample,
                llm=llm,
                resolver=mapping_resolver,
            )
            prepared.append((sheet, iterator, prefix + sample, headers, mapping, mapping_source))

        with engine.begin() as connection:
            intake.lock_import(connection)
            workbook_id, complete = intake.existing_workbook(connection, digest, version, supplier)
            if complete:
                return {
                    "path": str(path),
                    "sha256": digest,
                    "status": "skipped",
                    "normalizer_version": version,
                }
            new_source = workbook_id is None
            workbook_id = workbook_id or uuid4()
            if new_source:
                intake.write_import_batch(
                    connection,
                    {
                        "workbooks": [
                            {
                                "id": workbook_id,
                                "sha256": digest,
                                "original_path": str(path.resolve()),
                                "archive_name": None,
                                "byte_size": len(content),
                                "content": content,
                                "capture_version": "xlsx-xml-v1",
                            }
                        ]
                    },
                )
            supplier_id, products, warehouses = catalog.identities(connection, supplier)
            existing_sheets = intake.existing_sheets(connection, workbook_id)

            def finding(code, sheet, row=None, column=None, details=None):
                key = f"{version}:{sheet}:{code}"
                entry = findings.setdefault(
                    key,
                    {
                        "id": uuid4(),
                        "workbook_id": workbook_id,
                        "finding_key": key,
                        "code": code,
                        "evidence": {
                            "sheet": sheet,
                            "normalizer_version": version,
                            "count": 0,
                            "examples": [],
                        },
                        "description": FINDINGS[code],
                        "status": "open",
                        "resolution": None,
                    },
                )
                entry["evidence"]["count"] += 1
                if len(entry["evidence"]["examples"]) < 20:
                    entry["evidence"]["examples"].append({"row": row, "column": column, "details": details})

            date_match = re.search(r"\d{2}\.\d{2}\.\d{4}", path.name)
            as_of = datetime.strptime(date_match[0], "%d.%m.%Y").date() if date_match else None
            for sheet, iterator, prefix, headers, mapping, mapping_source in prepared:
                if mapping is None:
                    kind, header_end = "unresolved", 0
                    sku_col = name_col = article_col = unit_col = None
                else:
                    kind, header_end, sku_col, name_col, article_col, unit_col = mapping
                finding(
                    "worksheet_mapping" if mapping is not None else "worksheet_unresolved",
                    sheet.name,
                    details={
                        "mapping": mapping.as_dict() if mapping is not None else None,
                        "resolution": mapping_source,
                    },
                )
                sheet_id = existing_sheets.get(sheet.name) or uuid4()
                if sheet.name not in existing_sheets:
                    intake.write_import_batch(
                        connection,
                        {
                            "sheets": [
                                {
                                    "id": sheet_id,
                                    "workbook_id": workbook_id,
                                    "name": sheet.name,
                                    "position": sheet.position,
                                    "reported_rows": sheet.rows,
                                    "reported_columns": sheet.columns,
                                    "layout": {**sheet.layout, "template": kind, "header_end": header_end},
                                }
                            ]
                        },
                    )
                shipments = {}
                if mapping is not None and kind in ("shipments", "snapshot"):
                    header_row = mapping.header_rows[-1] if mapping.header_rows else 1
                    header = headers.get(header_row, {})
                    records = []
                    for column in mapping.shipment_columns:
                        shipment_id = uuid4()
                        shipments[column] = shipment_id
                        records.append(
                            {
                                "id": shipment_id,
                                "supplier_id": supplier_id,
                                "source_sheet_id": sheet_id,
                                "source_column": column,
                                "normalizer_version": version,
                                **shipment_header(str(value(header, column))),
                            }
                        )
                    supply.write_import_batch(connection, {"shipments": records})
                    counts["shipments"] += len(records)
                seen = {}
                rows = chain(prefix, iterator)
                while chunk := list(islice(rows, BATCH_SIZE)):
                    source_ids = (
                        {}
                        if new_source
                        else intake.existing_rows(connection, sheet_id, [row for row, _ in chunk])
                    )
                    raw = []
                    batch = defaultdict(list)
                    product_rows, warehouse_rows, catalog_rows = [], [], []
                    for row, cells in chunk:
                        row_id = source_ids.get(row) or uuid4()
                        if row not in source_ids:
                            raw.append(
                                {"id": row_id, "sheet_id": sheet_id, "row_number": row, "cells": cells}
                            )
                        common = {"source_row_id": row_id, "normalizer_version": version}
                        if mapping is None:
                            continue
                        for column, cell in cells.items():
                            cell_type = cell.get("cached_type", cell["type"])
                            if cell_type == "e":
                                finding("excel_error", sheet.name, row, column, cell.get("value"))
                            if cell_type == "n" and value(cells, column) not in (None, ""):
                                original = Decimal(value(cells, column))
                                if number(cells, column) != original:
                                    finding("numeric_rounding", sheet.name, row, column, str(original))
                            if cell["type"] == "f" and cell.get("cached_value") is None:
                                finding("formula_cache_missing", sheet.name, row, column)
                        if kind == "seasonality":
                            for table, item in seasonality(cells, row, headers):
                                batch[table].append(
                                    {"id": uuid4(), **common, "supplier_id": supplier_id, **item}
                                )
                            continue
                        if row <= header_end:
                            continue
                        sku = value(cells, sku_col)
                        if sku is None or str(sku).strip() == "":
                            continue
                        if not isinstance(sku, str):
                            raise ValueError(f"SKU must be stored as text: {sheet.name}!{sku_col}{row}")
                        if kind != "movements" and sku in seen:
                            finding(
                                "duplicate_sku",
                                sheet.name,
                                row,
                                sku_col,
                                {"sku": sku, "first_row": seen[sku]},
                            )
                        seen[sku] = row
                        if sku not in products:
                            products[sku] = uuid4()
                            product_rows.append({"id": products[sku], "supplier_id": supplier_id, "sku": sku})
                        product_id = products[sku]
                        fields = mapping.fields
                        unit = value(cells, unit_col) if unit_col else None
                        category_column = fields.get("category")
                        category = value(cells, category_column) if category_column else None
                        catalog_rows.append(
                            {
                                "id": uuid4(),
                                **common,
                                "product_id": product_id,
                                "name": value(cells, name_col),
                                "supplier_article": value(cells, article_col) if article_col else None,
                                "unit": unit,
                                "category_code": str(category) if category is not None else None,
                                "category_year": 2026 if category is not None else None,
                            }
                        )
                        for table, item in observations(
                            kind, supplier, cells, row, headers, unit, as_of, mapping
                        ):
                            if table == "movements":
                                name = item.pop("warehouse_name")
                                if not name:
                                    finding(
                                        "missing_movement_warehouse",
                                        sheet.name,
                                        row,
                                        mapping.fields.get("warehouse"),
                                    )
                                    # SalesMovement requires a warehouse FK;
                                    # retain the raw row and finding without
                                    # assigning a guessed location.
                                    continue
                                if name not in warehouses:
                                    warehouses[name] = uuid4()
                                    warehouse_rows.append({"id": warehouses[name], "name": name})
                                item["warehouse_id"] = warehouses[name]
                                if item["quantity"] is None:
                                    finding(
                                        "missing_movement_quantity",
                                        sheet.name,
                                        row,
                                        mapping.fields.get("quantity"),
                                    )
                                elif item["quantity"] < 0:
                                    finding(
                                        "negative_movement",
                                        sheet.name,
                                        row,
                                        mapping.fields.get("quantity"),
                                        str(item["quantity"]),
                                    )
                            if table == "shipment_lines":
                                item.update(
                                    shipment_id=shipments[item["source_column"]], supplier_id=supplier_id
                                )
                            if table == "quantity_rules" and item["value"] is not None and item["value"] <= 0:
                                finding("nonpositive_quantity_rule", sheet.name, row, item["source_column"])
                            batch[table].append({"id": uuid4(), **common, "product_id": product_id, **item})
                        if kind == "snapshot":
                            ap = cells.get("AP", {}).get("formula", "")
                            if ap == f"=SUM(AC{row}:AO{row})":
                                finding("thirteen_month_total", sheet.name, row, "AP", ap)
                            aq = cells.get("AQ", {}).get("formula", "")
                            if aq and aq != f"=AP{row}/12":
                                finding("inconsistent_average_formula", sheet.name, row, "AQ", aq)
                            if sum(number(cells, c) or 0 for c in ("AT", "AU", "AV", "AW")) != number(
                                cells, "AX"
                            ):
                                finding("stock_scope_overlap", sheet.name, row, "AT:AX")
                    intake.write_import_batch(connection, {"rows": raw})
                    catalog.write_import_batch(connection, product_rows, warehouse_rows, catalog_rows)
                    demand.write_import_batch(connection, batch)
                    inventory.write_import_batch(connection, batch)
                    supply.write_import_batch(connection, batch)
                    counts["raw_rows"] += len(raw)
                    counts["product_observations"] += len(catalog_rows)
                    counts.update({table: len(items) for table, items in batch.items()})
                counts["sheets"] += 1
                if kind in ("monthly_stock", "monthly_sales", "snapshot"):
                    finding("unknown_warehouse_scope", sheet.name)
                if kind == "seasonality":
                    finding("supplier_aggregate_only", sheet.name)
                    if supplier == "systeme":
                        finding("overlapping_seasonality_sources", sheet.name)
                if kind == "snapshot":
                    finding("unknown_shipment_year", sheet.name, 2, "BC")
                    finding("relative_change_not_multiplier", sheet.name, 2, "AR:AS")
                if kind == "shipments" and supplier == "iek":
                    finding("unstructured_unit_conversion", sheet.name)
            findings[f"import:{version}"] = {
                "id": uuid4(),
                "workbook_id": workbook_id,
                "finding_key": f"import:{version}",
                "code": "import_complete",
                "evidence": {"supplier": supplier, "normalizer_version": version, "counts": dict(counts)},
                "description": "Импорт завершён атомарно / Import committed atomically",
                "status": "accepted_limitation",
                "resolution": "Completion marker; not a data quality defect",
            }
            intake.write_import_batch(connection, {"findings": list(findings.values())})
    finally:
        book.close()
    return {
        "path": str(path),
        "sha256": digest,
        "status": "imported",
        "normalizer_version": version,
        "counts": dict(counts),
        "findings": len(findings) - 1,
    }


FINDINGS = {
    "worksheet_mapping": (
        "Worksheet mapping resolved with cited source cells / Сопоставление листа разрешено с источниками"
    ),
    "worksheet_unresolved": (
        "Worksheet mapping unresolved; raw evidence retained without observations / "
        "Сопоставление не разрешено; исходные данные сохранены без наблюдений"
    ),
    "missing_movement_warehouse": (
        "Movement warehouse missing; row retained without a guessed scope / "
        "Склад движения отсутствует; строка сохранена без догаданного охвата"
    ),
    "excel_error": "Ошибка Excel сохранена; типизированное число NULL / Excel error retained, numeric NULL",
    "numeric_rounding": "Округлено до 12 знаков / Rounded to 12 decimals; original retained",
    "formula_cache_missing": "Нет кеша формулы / Formula cache absent, not recalculated",
    "duplicate_sku": "Дубликат SKU сохранён отдельно / Duplicate SKU retained separately",
    "missing_movement_quantity": "Количество отсутствует, не ноль / Missing quantity is not zero",
    "negative_movement": "Отрицательное движение сохранено / Negative movement retained",
    "nonpositive_quantity_rule": "Неположительная кратность / Nonpositive quantity rule",
    "thirteen_month_total": "Формула: 13 месяцев вместо 12 / Formula: 13 months instead of 12",
    "inconsistent_average_formula": "Нетипичный делитель среднего / Inconsistent average divisor",
    "stock_scope_overlap": "Компоненты не равны AX / Components differ from AX; scope unknown",
    "unknown_warehouse_scope": "Складской охват отчёта неизвестен / Report warehouse scope unknown",
    "supplier_aggregate_only": "Сезонность по поставщику, не SKU / Supplier seasonality, not SKU",
    "overlapping_seasonality_sources": "Сводки перекрываются / Summaries overlap; do not sum",
    "unknown_shipment_year": "В дате поставки отсутствует год / Shipment header omits year",
    "relative_change_not_multiplier": "Изменения, не множители / Relative changes, not multipliers",
    "unstructured_unit_conversion": "Перевод бухт/метров без правил / Unstructured coil/metre conversion",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--supplier", choices=("iek", "systeme"))
    parser.add_argument("--normalizer-version", default=NORMALIZER_VERSION)
    parser.add_argument("--llm-config", type=Path, help="Explicit model IDs and prices for unresolved sheets")
    parser.add_argument("--llm-cache", type=Path)
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required; apply `uv run alembic upgrade head` first")
    engine = create_engine(url)
    try:
        from replenishment.calculation.llm import BudgetLedger, load_llm_client

        llm = load_llm_client(args.llm_config, cache_path=args.llm_cache, budget=BudgetLedger())
        files = discover(args.path)
        assignments = [(path, supplier_for(path, args.supplier)) for path in files]
        for path, supplier in assignments:
            print(
                json.dumps(
                    import_workbook(engine, path, supplier, args.normalizer_version, llm=llm),
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if llm:
            print(json.dumps({"llm_accounting": llm.budget.snapshot()}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
