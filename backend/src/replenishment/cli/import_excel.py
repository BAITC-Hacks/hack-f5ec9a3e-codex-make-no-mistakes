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
NORMALIZER_VERSION = "v1"


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


def import_workbook(engine, path, supplier=None, version=NORMALIZER_VERSION):
    path = Path(path)
    supplier = supplier_for(path, supplier)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version):
        raise ValueError("Normalizer version must be a nonempty stable identifier")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    counts = Counter()
    with engine.begin() as connection:
        intake.lock_import(connection)
        workbook_id, complete = intake.existing_workbook(connection, digest, version, supplier)
        if complete:
            return {"path": str(path), "sha256": digest, "status": "skipped", "normalizer_version": version}
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
        findings = {}

        def finding(code, sheet, row=None, column=None, details=None):
            key = f"{version}:{sheet}:{code}"
            entry = findings.setdefault(
                key,
                {
                    "id": uuid4(),
                    "workbook_id": workbook_id,
                    "finding_key": key,
                    "code": code,
                    "evidence": {"sheet": sheet, "normalizer_version": version, "count": 0, "examples": []},
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
        book = Workbook(content)
        try:
            for sheet in book.sheets:
                iterator = book.rows(sheet)
                prefix = list(islice(iterator, 40 if sheet.rows < 100 else 3))
                headers = dict(prefix)
                kind, header_end, sku_col, name_col, article_col, unit_col = classify(headers, supplier)
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
                if kind in ("shipments", "snapshot"):
                    header = headers[1 if kind == "shipments" else 2]
                    columns = list("DEFGHI") if kind == "shipments" else ["BC"]
                    records = []
                    for column in columns:
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
                        unit = value(cells, unit_col) if unit_col else None
                        category = value(cells, "E") if kind == "snapshot" else None
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
                        for table, item in observations(kind, supplier, cells, row, headers, unit, as_of):
                            if table == "movements":
                                name = item.pop("warehouse_name")
                                if not name:
                                    raise ValueError(f"Movement warehouse missing: {sheet.name}!G{row}")
                                if name not in warehouses:
                                    warehouses[name] = uuid4()
                                    warehouse_rows.append({"id": warehouses[name], "name": name})
                                item["warehouse_id"] = warehouses[name]
                                if item["quantity"] is None:
                                    finding("missing_movement_quantity", sheet.name, row, "H")
                                elif item["quantity"] < 0:
                                    finding("negative_movement", sheet.name, row, "H", str(item["quantity"]))
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
        finally:
            book.close()
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
    return {
        "path": str(path),
        "sha256": digest,
        "status": "imported",
        "normalizer_version": version,
        "counts": dict(counts),
        "findings": len(findings) - 1,
    }


FINDINGS = {
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
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required; apply `uv run alembic upgrade head` first")
    engine = create_engine(url)
    try:
        files = discover(args.path)
        assignments = [(path, supplier_for(path, args.supplier)) for path in files]
        for path, supplier in assignments:
            print(
                json.dumps(
                    import_workbook(engine, path, supplier, args.normalizer_version), ensure_ascii=False
                ),
                flush=True,
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
