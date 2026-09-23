"""Pinned, source-derived inputs for the calculation boundary.

This module deliberately uses SQLAlchemy Core tables supplied by the composition
root.  Calculation code must not import one of the storage domains' ORM models.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, get_args

from sqlalchemy import and_, false, or_, select

SourceTable = Literal[
    "demand_monthly_sales",
    "demand_movements",
    "demand_report_metrics",
    "demand_seasonality_observations",
    "inventory_observations",
    "inventory_monthly_stock",
    "supply_shipments",
    "supply_shipment_lines",
    "supply_quantity_rules",
    "catalog_product_observations",
]
SOURCE_TABLES = get_args(SourceTable)

_ALIASES = {
    "monthly_sales": "demand_monthly_sales",
    "sales": "demand_monthly_sales",
    "movements": "demand_movements",
    "transactions": "demand_movements",
    "stock": "inventory_observations",
    "current_stock": "inventory_observations",
    "monthly_stock": "inventory_monthly_stock",
    "shipments": "supply_shipments",
    "shipment_lines": "supply_shipment_lines",
    "quantity_rules": "supply_quantity_rules",
    "products": "catalog_product_observations",
    "product_observations": "catalog_product_observations",
}
_SELECTION_FIELDS = {
    "table",
    "normalizer_version",
    "version",
    "source_row_id",
    "source_column",
    "product_id",
    "warehouse_id",
    "workbook_id",
    "sha256",
    "sheet_id",
}


def _table(metadata: Any, name: str) -> Any | None:
    return metadata.tables.get(name)


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _number(value: Any) -> str | None:
    parsed = _decimal(value)
    return format(parsed, "f") if parsed is not None else None


def _json(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "hex") and not isinstance(value, (str, bytes)):
        try:
            return str(value)
        except Exception:  # pragma: no cover - defensive for driver-specific IDs
            pass
    return value


def _field(table: Any | None, name: str) -> Any | None:
    return table.c.get(name) if table is not None else None


def _source_context(table: Any, metadata: Any) -> tuple[Any, Any | None, Any | None, Any | None]:
    """Return a source table joined to its immutable workbook evidence."""

    rows = _table(metadata, "intake_rows")
    sheets = _table(metadata, "intake_sheets")
    books = _table(metadata, "intake_workbooks")
    row = sheet = workbook = None
    from_clause = table
    if rows is not None and _field(table, "source_row_id") is not None:
        from_clause = table.join(rows, table.c.source_row_id == rows.c.id)
        row = rows
    if sheets is not None and _field(table, "source_sheet_id") is not None:
        from_clause = table.join(sheets, table.c.source_sheet_id == sheets.c.id)
        sheet = sheets
    elif sheets is not None and row is not None:
        from_clause = from_clause.join(sheets, rows.c.sheet_id == sheets.c.id)
        sheet = sheets
    if books is not None and sheet is not None:
        from_clause = from_clause.join(books, sheets.c.workbook_id == books.c.id)
        workbook = books
    return from_clause, row, sheet, workbook


def _source_identity(row: Mapping[str, Any]) -> str | None:
    value = row.get("sha256") or row.get("original_path")
    sheet = row.get("sheet_name")
    if value is None:
        return None
    return f"{value}:{sheet}" if sheet else str(value)


def _selection_specs(
    source_selection: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    normalizer_versions: Mapping[str, str | Sequence[str]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Normalize the public source-selection forms into table keyed filters."""

    specs: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(table: str, value: Any) -> None:
        table = _ALIASES.get(table, table)
        if isinstance(value, str):
            specs[table].append({"table": table, "normalizer_version": value})
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, dict)):
            for item in value:
                add(table, item)
            return
        if not isinstance(value, Mapping):
            raise ValueError(f"Invalid source selection for {table}")
        item = dict(value)
        item["table"] = table
        unexpected = set(item) - _SELECTION_FIELDS
        if unexpected:
            raise ValueError(f"Unsupported source selection fields for {table}: {sorted(unexpected)}")
        version = item.get("normalizer_version", item.get("version"))
        if not isinstance(version, str) or not version:
            raise ValueError(f"Pinned normalizer_version required for {table}")
        item["normalizer_version"] = version
        specs[table].append(item)

    if isinstance(source_selection, Mapping):
        for table, value in source_selection.items():
            add(table, value)
    elif source_selection is not None:
        for item in source_selection:
            if not isinstance(item, Mapping):
                raise ValueError("Source selection entries must be objects")
            table = item.get("table", item.get("source"))
            if not isinstance(table, str):
                raise ValueError("Source selection table is required")
            add(table, item)

    for table, value in (normalizer_versions or {}).items():
        add(table, value)

    if any(not spec.get("sha256") or spec["sha256"] == "*" for values in specs.values() for spec in values):
        raise ValueError("Every observation selection must pin a workbook sha256")
    if not specs.get("demand_monthly_sales"):
        raise ValueError("A pinned demand_monthly_sales source selection is required")
    return {
        table: [items[key] for key in sorted(items)]
        for table, values in sorted(specs.items())
        for items in [{json.dumps(value, sort_keys=True, default=_json): value for value in values}]
    }


def _selection_condition(
    table: Any,
    specs: Sequence[Mapping[str, Any]],
    *,
    row: Any | None = None,
    sheet: Any | None = None,
    workbook: Any | None = None,
) -> Any:
    branches = []
    for spec in specs:
        if spec.get("sha256") not in (None, "*") and workbook is None:
            raise ValueError("Workbook hash selection requires source workbook evidence")
        if spec.get("workbook_id") not in (None, "*") and workbook is None:
            raise ValueError("workbook_id selection requires source workbook evidence")
        if spec.get("sheet_id") not in (None, "*") and sheet is None:
            raise ValueError("sheet_id selection requires source sheet evidence")
        conditions = [table.c.normalizer_version == spec["normalizer_version"]]
        for key, column in (
            ("source_row_id", _field(table, "source_row_id")),
            ("source_column", _field(table, "source_column")),
            ("product_id", _field(table, "product_id")),
            ("warehouse_id", _field(table, "warehouse_id")),
        ):
            if key in spec and column is not None and spec[key] != "*":
                conditions.append(column == spec[key])
        if "workbook_id" in spec and workbook is not None and _field(workbook, "id") is not None:
            if spec["workbook_id"] != "*":
                conditions.append(workbook.c.id == spec["workbook_id"])
        if "sha256" in spec and workbook is not None and _field(workbook, "sha256") is not None:
            if spec["sha256"] != "*":
                conditions.append(workbook.c.sha256 == spec["sha256"])
        if "sheet_id" in spec and sheet is not None:
            if spec["sheet_id"] != "*":
                conditions.append(sheet.c.id == spec["sheet_id"])
        branches.append(and_(*conditions))
    return or_(*branches) if branches else false()


def _scope(warehouse_id: Any, warehouse_name: Any = None, source_identity: str | None = None) -> str:
    if warehouse_id is None:
        # A missing warehouse is not a join key. Keep separate report origins
        # separate so embedded/reconciliation reports cannot become sales.
        label = str(warehouse_name).strip() if warehouse_name not in (None, "") else None
        parts = [part for part in (label, source_identity) if part]
        return f"unknown:{':'.join(parts)}" if parts else "unknown"
    return f"warehouse:{warehouse_id}"


def _source_ref(row: Mapping[str, Any]) -> dict[str, str]:
    ref: dict[str, str] = {}
    for key in (
        "source_row_id",
        "source_column",
        "normalizer_version",
        "sheet_name",
        "original_path",
        "sha256",
    ):
        value = row.get(key)
        if value is not None:
            ref[key] = str(_json(value))
    if "source_column" in ref and "row_number" in row and row["row_number"] is not None:
        ref["cell"] = f"{ref['source_column']}{row['row_number']}"
    return ref


def _stable_series_id(supplier: str, sku: str, scope: str, unit: str | None) -> str:
    identity = json.dumps([supplier, sku, scope, unit], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _base_sales_rows(
    connection: Any, metadata: Any, specs: Sequence[Mapping[str, Any]], cutoff: date
) -> list[dict[str, Any]]:
    sales = _table(metadata, "demand_monthly_sales")
    products = _table(metadata, "catalog_products")
    suppliers = _table(metadata, "catalog_suppliers")
    warehouses = _table(metadata, "catalog_warehouses")
    rows = _table(metadata, "intake_rows")
    sheets = _table(metadata, "intake_sheets")
    books = _table(metadata, "intake_workbooks")
    if sales is None or products is None or suppliers is None:
        raise ValueError("Metadata is missing the canonical sales tables")

    columns = [
        sales.c.id.label("sales_id"),
        sales.c.source_row_id,
        sales.c.source_column,
        sales.c.normalizer_version,
        sales.c.product_id,
        sales.c.warehouse_id,
        sales.c.month,
        sales.c.quantity,
        sales.c.unit,
        sales.c.is_complete_period,
        products.c.sku,
        suppliers.c.code.label("supplier"),
        suppliers.c.id.label("supplier_id"),
    ]
    from_clause = sales.join(products, products.c.id == sales.c.product_id).join(
        suppliers, suppliers.c.id == products.c.supplier_id
    )
    if warehouses is not None:
        columns.append(warehouses.c.name.label("warehouse_name"))
        from_clause = from_clause.outerjoin(warehouses, warehouses.c.id == sales.c.warehouse_id)
    if rows is not None:
        columns.extend((rows.c.row_number,))
        from_clause = from_clause.join(rows, rows.c.id == sales.c.source_row_id)
    if sheets is not None and rows is not None:
        columns.append(sheets.c.name.label("sheet_name"))
        from_clause = from_clause.join(sheets, sheets.c.id == rows.c.sheet_id)
    if books is not None and sheets is not None:
        columns.extend((books.c.original_path, books.c.sha256))
        from_clause = from_clause.join(books, books.c.id == sheets.c.workbook_id)

    statement = (
        select(*columns)
        .select_from(from_clause)
        .where(
            sales.c.month < cutoff,
            sales.c.is_complete_period.is_not(False),
            _selection_condition(sales, specs, row=rows, sheet=sheets, workbook=books),
        )
    )
    result = []
    for raw in connection.execute(statement.order_by(sales.c.id)).mappings():
        item = dict(raw)
        item["month"] = _date(item.get("month"))
        if item["month"] is None:
            continue
        item["supplier"] = str(item["supplier"])
        item["sku"] = str(item["sku"])
        item["unit"] = str(item["unit"]) if item.get("unit") not in (None, "") else None
        item["scope"] = _scope(item.get("warehouse_id"), item.get("warehouse_name"), _source_identity(item))
        item["quantity"] = _decimal(item.get("quantity"))
        item["evidence"] = _source_ref(item)
        result.append(item)
    return result


def _product_attributes(
    connection: Any, metadata: Any, specs: Sequence[Mapping[str, Any]], product_ids: set[Any]
) -> dict[Any, dict[str, Any]]:
    table = _table(metadata, "catalog_product_observations")
    if table is None or not product_ids or not specs:
        return {}
    from_clause, source_row, source_sheet, workbook = _source_context(table, metadata)
    columns = [table]
    if source_sheet is not None:
        columns.append(source_sheet.c.name.label("sheet_name"))
    if workbook is not None:
        columns.extend((workbook.c.original_path, workbook.c.sha256))
    statement = (
        select(*columns)
        .select_from(from_clause)
        .where(
            table.c.product_id.in_(product_ids),
            _selection_condition(table, specs, row=source_row, sheet=source_sheet, workbook=workbook),
        )
    )
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(statement.order_by(table.c.id)).mappings():
        grouped[row["product_id"]].append(dict(row))
    result = {}
    for product_id, rows in grouped.items():
        units = {str(r["unit"]) for r in rows if r.get("unit") not in (None, "")}
        categories = {str(r["category_code"]) for r in rows if r.get("category_code") not in (None, "")}
        result[product_id] = {
            "unit_candidates": sorted(units),
            "category_candidates": sorted(categories),
            "category_year": max(
                (r["category_year"] for r in rows if r.get("category_code") and r.get("category_year")),
                default=None,
            ),
            "evidence": [_source_ref(r) for r in rows[:20]],
        }
    return result


def _load_inventory(
    connection: Any,
    metadata: Any,
    specs: Mapping[str, Sequence[Mapping[str, Any]]],
    keys: set[tuple[Any, str, str | None]],
    planning_date: date,
) -> dict[tuple[Any, str, str | None], dict[str, Any]]:
    table = _table(metadata, "inventory_observations")
    if table is None or not specs.get("inventory_observations"):
        table = None
    groups: dict[tuple[Any, str, str | None, date | None], dict[str, Any]] = {}
    if table is not None:
        from_clause, source_row, source_sheet, workbook = _source_context(table, metadata)
        columns = [table]
        if source_sheet is not None:
            columns.append(source_sheet.c.name.label("sheet_name"))
        if workbook is not None:
            columns.extend((workbook.c.original_path, workbook.c.sha256))
        statement = (
            select(*columns)
            .select_from(from_clause)
            .where(
                table.c.product_id.in_({key[0] for key in keys}),
                _selection_condition(
                    table,
                    specs["inventory_observations"],
                    row=source_row,
                    sheet=source_sheet,
                    workbook=workbook,
                ),
            )
        )
        for raw in connection.execute(statement.order_by(table.c.id)).mappings():
            row = dict(raw)
            as_of = _date(row.get("as_of"))
            if as_of is not None and as_of > planning_date:
                continue
            key = (
                row["product_id"],
                _scope(row.get("warehouse_id"), source_identity=_source_identity(row)),
                row.get("unit"),
                as_of,
            )
            group = groups.setdefault(
                key, {"metrics": {}, "evidence": [], "date_basis": row.get("date_basis")}
            )
            metric = row["metric"]
            quantity = _number(row.get("quantity"))
            previous = group["metrics"].get(metric, quantity)
            group["metrics"][metric] = quantity if previous == quantity else None
            group["evidence"].append(_source_ref(row))

    result: dict[tuple[Any, str, str | None], dict[str, Any]] = {}
    for key in keys:
        candidates = [
            (stamp, unit, group)
            for (product_id, scope, unit, stamp), group in groups.items()
            if (product_id, scope) == key[:2] and (unit is None or key[2] is None or unit == key[2])
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0] or date.min, reverse=True)
        if key[2] is None:
            latest = candidates[0][0]
            if len({unit for stamp, unit, _ in candidates if stamp == latest}) > 1:
                continue
        _, selected_unit, selected = candidates[0]
        inventory = dict(selected["metrics"])
        inventory.update(
            {
                "scope": key[1],
                "unit": selected_unit or key[2],
                "as_of": candidates[0][0].isoformat() if candidates[0][0] else None,
                "date_basis": selected.get("date_basis"),
                "evidence": selected["evidence"],
            }
        )
        if key[2] is None and selected_unit is not None:
            inventory["unit_inferred"] = True
        if (
            inventory.get("free") is None
            and inventory.get("on_hand") is not None
            and inventory.get("reserved") is not None
        ):
            free = _decimal(inventory["on_hand"]) - _decimal(inventory["reserved"])
            inventory["free"] = _number(free)
            inventory["free_derived"] = True
        result[key] = inventory
    return result


def _load_shipments(
    connection: Any, metadata: Any, specs: Mapping[str, Sequence[Mapping[str, Any]]], product_ids: set[Any]
) -> dict[Any, list[dict[str, Any]]]:
    headers = _table(metadata, "supply_shipments")
    lines = _table(metadata, "supply_shipment_lines")
    if (
        headers is None
        or lines is None
        or not specs.get("supply_shipments")
        or not specs.get("supply_shipment_lines")
    ):
        return defaultdict(list)
    rows = _table(metadata, "intake_rows")
    sheets = _table(metadata, "intake_sheets")
    books = _table(metadata, "intake_workbooks")
    line_rows = rows.alias("shipment_line_rows") if rows is not None else None
    line_sheets = sheets.alias("shipment_line_sheets") if sheets is not None else None
    line_books = books.alias("shipment_line_books") if books is not None else None
    header_sheets = sheets.alias("shipment_header_sheets") if sheets is not None else None
    header_books = books.alias("shipment_header_books") if books is not None else None
    from_clause = lines.join(
        headers, and_(headers.c.id == lines.c.shipment_id, headers.c.supplier_id == lines.c.supplier_id)
    )
    if line_rows is not None:
        from_clause = from_clause.join(line_rows, lines.c.source_row_id == line_rows.c.id)
    if line_sheets is not None:
        from_clause = from_clause.join(line_sheets, line_rows.c.sheet_id == line_sheets.c.id)
    if line_books is not None:
        from_clause = from_clause.join(line_books, line_sheets.c.workbook_id == line_books.c.id)
    if header_sheets is not None:
        from_clause = from_clause.join(header_sheets, headers.c.source_sheet_id == header_sheets.c.id)
    if header_books is not None:
        from_clause = from_clause.join(header_books, header_sheets.c.workbook_id == header_books.c.id)
    columns = [
        lines,
        headers.c.supplier_id,
        headers.c.expected_on,
        headers.c.ordered_on,
        headers.c.date_basis,
        headers.c.warehouse_id,
        headers.c.header,
        headers.c.document_number,
    ]
    if line_sheets is not None:
        columns.append(line_sheets.c.name.label("sheet_name"))
    if line_books is not None:
        columns.extend((line_books.c.original_path, line_books.c.sha256))
    statement = (
        select(*columns)
        .select_from(from_clause)
        .where(
            lines.c.product_id.in_(product_ids),
            _selection_condition(
                lines, specs["supply_shipment_lines"], row=line_rows, sheet=line_sheets, workbook=line_books
            ),
            _selection_condition(
                headers, specs["supply_shipments"], sheet=header_sheets, workbook=header_books
            ),
        )
    )
    result: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for raw in connection.execute(statement.order_by(lines.c.id)).mappings():
        row = dict(raw)
        row["expected_on"] = _date(row.get("expected_on"))
        row["ordered_on"] = _date(row.get("ordered_on"))
        row["scope"] = _scope(row.get("warehouse_id"), source_identity=_source_identity(row))
        row["quantity"] = _number(row.get("quantity"))
        row["evidence"] = [_source_ref(row)]
        result[row["product_id"]].append(row)
    return result


def _load_rules(
    connection: Any, metadata: Any, specs: Mapping[str, Sequence[Mapping[str, Any]]], product_ids: set[Any]
) -> dict[Any, list[dict[str, Any]]]:
    table = _table(metadata, "supply_quantity_rules")
    if table is None or not specs.get("supply_quantity_rules"):
        return defaultdict(list)
    from_clause, source_row, source_sheet, workbook = _source_context(table, metadata)
    columns = [table]
    if source_sheet is not None:
        columns.append(source_sheet.c.name.label("sheet_name"))
    if workbook is not None:
        columns.extend((workbook.c.original_path, workbook.c.sha256))
    statement = (
        select(*columns)
        .select_from(from_clause)
        .where(
            table.c.product_id.in_(product_ids),
            _selection_condition(
                table, specs["supply_quantity_rules"], row=source_row, sheet=source_sheet, workbook=workbook
            ),
        )
    )
    result: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for raw in connection.execute(statement.order_by(table.c.id)).mappings():
        row = dict(raw)
        result[row["product_id"]].append(
            {
                "label": row.get("label"),
                "kind": row.get("kind"),
                "value": _number(row.get("value")),
                "unit": row.get("unit"),
                "interpretation_confirmed": bool(row.get("interpretation_confirmed")),
                "evidence": [_source_ref(row)],
            }
        )
    return result


def _load_transactions(
    connection: Any, metadata: Any, specs: Mapping[str, Sequence[Mapping[str, Any]]], product_ids: set[Any]
) -> dict[tuple[Any, str, str | None], list[dict[str, Any]]]:
    table = _table(metadata, "demand_movements")
    if table is None or not specs.get("demand_movements"):
        return defaultdict(list)
    from_clause, source_row, source_sheet, workbook = _source_context(table, metadata)
    columns = [table]
    if source_sheet is not None:
        columns.append(source_sheet.c.name.label("sheet_name"))
    if workbook is not None:
        columns.extend((workbook.c.original_path, workbook.c.sha256))
    statement = (
        select(*columns)
        .select_from(from_clause)
        .where(
            table.c.product_id.in_(product_ids),
            _selection_condition(
                table, specs["demand_movements"], row=source_row, sheet=source_sheet, workbook=workbook
            ),
        )
    )
    result: dict[tuple[Any, str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for raw in connection.execute(statement.order_by(table.c.id)).mappings():
        row = dict(raw)
        occurred = _date(row.get("occurred_at"))
        if occurred is None:
            continue
        item = {
            "month": occurred.strftime("%Y-%m-01"),
            "quantity": _number(row.get("quantity")),
            "document_number": row.get("document_number"),
            "occurred_on": occurred.isoformat(),
            "evidence": [_source_ref(row)],
        }
        result[
            (
                row["product_id"],
                _scope(row.get("warehouse_id"), source_identity=_source_identity(row)),
                row.get("unit"),
            )
        ].append(item)
    return result


def _load_report_metrics(
    connection: Any, metadata: Any, specs: Mapping[str, Sequence[Mapping[str, Any]]], product_ids: set[Any]
) -> dict[Any, list[dict[str, Any]]]:
    table = _table(metadata, "demand_report_metrics")
    if table is None or not specs.get("demand_report_metrics"):
        return defaultdict(list)
    from_clause, source_row, source_sheet, workbook = _source_context(table, metadata)
    columns = [table]
    if source_sheet is not None:
        columns.append(source_sheet.c.name.label("sheet_name"))
    if workbook is not None:
        columns.extend((workbook.c.original_path, workbook.c.sha256))
    statement = (
        select(*columns)
        .select_from(from_clause)
        .where(
            table.c.product_id.in_(product_ids),
            _selection_condition(
                table, specs["demand_report_metrics"], row=source_row, sheet=source_sheet, workbook=workbook
            ),
        )
    )
    result: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for raw in connection.execute(statement.order_by(table.c.id)).mappings():
        row = dict(raw)
        result[row["product_id"]].append(
            {
                "metric": row.get("metric"),
                "label": row.get("label"),
                "value": _number(row.get("value")),
                "unit": row.get("unit"),
                "period_start": _json(row.get("period_start")),
                "period_end": _json(row.get("period_end")),
                "evidence": [_source_ref(row)],
            }
        )
    return result


def _load_seasonality(
    connection: Any, metadata: Any, specs: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[Any, list[dict[str, Any]]]:
    table = _table(metadata, "demand_seasonality_observations")
    if table is None or not specs.get("demand_seasonality_observations"):
        return defaultdict(list)
    from_clause, source_row, source_sheet, workbook = _source_context(table, metadata)
    columns = [table]
    if source_sheet is not None:
        columns.append(source_sheet.c.name.label("sheet_name"))
    if workbook is not None:
        columns.extend((workbook.c.original_path, workbook.c.sha256))
    statement = (
        select(*columns)
        .select_from(from_clause)
        .where(
            _selection_condition(
                table,
                specs["demand_seasonality_observations"],
                row=source_row,
                sheet=source_sheet,
                workbook=workbook,
            ),
        )
    )
    grouped = {}
    for raw in connection.execute(statement.order_by(table.c.id)).mappings():
        row = dict(raw)
        key = tuple(row.get(k) for k in ("supplier_id", "year", "month", "metric", "value", "unit", "basis"))
        entry = grouped.setdefault(
            key, {k: _json(row.get(k)) for k in ("year", "month", "metric", "value", "unit", "basis")}
        )
        entry.setdefault("evidence", []).append(_source_ref(row))
    result = defaultdict(list)
    for key, entry in grouped.items():
        result[key[0]].append(entry)
    return result


def require_imports(connection, metadata, selection):
    """An incomplete selected source set is an error, never a smaller silent catalogue."""
    if not selection or any(
        not item.get("sha256") or not item.get("normalizer_version") for item in selection
    ):
        raise ValueError("Every source selection must pin sha256 and normalizer_version")
    pairs = {(item["sha256"], item["normalizer_version"]) for item in selection}
    books = metadata.tables["intake_workbooks"]
    findings = metadata.tables["intake_findings"]
    statement = (
        select(books.c.sha256, findings.c.evidence)
        .select_from(books.join(findings, findings.c.workbook_id == books.c.id))
        .where(books.c.sha256.in_({digest for digest, _ in pairs}), findings.c.code == "import_complete")
    )
    completed = {
        (digest, evidence["normalizer_version"]) for digest, evidence in connection.execute(statement)
    }
    if missing := pairs - completed:
        raise ValueError(f"Import selected sources first; {len(missing)} hash/version pairs are missing")


def load_run_batch(engine, metadata, planning_date, source_selection, *, supplier=None):
    """Load a nonempty, import-verified snapshot shared by CLI and HTTP run creation."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        require_imports(connection, metadata, source_selection)
        batch = load_batch(connection, metadata, planning_date, source_selection=source_selection)
    if supplier:
        batch["series"] = [series for series in batch["series"] if series["supplier"] == supplier]
    if not batch["series"]:
        raise ValueError("No canonical monthly series in the selected sources")
    return batch


def load_batch(
    connection: Any,
    metadata: Any,
    planning_date: date | str,
    *,
    source_selection: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    normalizer_versions: Mapping[str, str | Sequence[str]] | None = None,
    contract_version: str = "2",
) -> dict[str, Any]:
    """Read a deterministic v2 batch from pinned normalized observations.

    The loader never treats an absent observation as zero and never sums data from
    different scopes or units.  Optional source tables are only read when their
    versions are explicitly selected.
    """

    if contract_version != "2":
        raise ValueError("Only calculation contract version 2 is supported")
    planning = _date(planning_date)
    if planning is None:
        raise ValueError("planning_date must be ISO date")
    cutoff = date(planning.year, planning.month, 1)
    specs = _selection_specs(source_selection, normalizer_versions)
    rows = _base_sales_rows(connection, metadata, specs["demand_monthly_sales"], cutoff)
    product_ids = {row["product_id"] for row in rows}
    attributes = _product_attributes(
        connection, metadata, specs.get("catalog_product_observations", ()), product_ids
    )
    primary, comparison = [], []
    for row in rows:
        # Dedicated supplied monthly reports own forecasts. Embedded snapshot sales
        # remain comparison evidence and never add another catalogue forecast.
        path = (row.get("original_path") or "").casefold()
        (comparison if path and "ежемесячные продажи" not in path else primary).append(row)
        candidates = attributes.get(row["product_id"], {}).get("unit_candidates", [])
        if row["unit"] is None and len(candidates) == 1:
            row["unit"] = candidates[0]
            row["unit_inferred"] = True
    series_rows = defaultdict(list)
    for row in primary:
        series_rows[(row["product_id"], row["supplier"], row["sku"], row["scope"], row["unit"])].append(row)
    keys = {(r["product_id"], r["scope"], r["unit"]) for r in rows}
    inventory = _load_inventory(connection, metadata, specs, keys, planning)
    shipments = _load_shipments(connection, metadata, specs, product_ids)
    rules = _load_rules(connection, metadata, specs, product_ids)
    transactions = _load_transactions(connection, metadata, specs, product_ids)
    transactions_by_product = defaultdict(list)
    for key, values in transactions.items():
        transactions_by_product[key[0]].append((key, values))
    report_metrics = _load_report_metrics(connection, metadata, specs, product_ids)
    seasonality = _load_seasonality(connection, metadata, specs)
    embedded = defaultdict(list)
    for row in comparison:
        embedded[row["product_id"]].append(row)

    def monthly_history(observations, assumptions):
        by_month = defaultdict(list)
        for row in observations:
            by_month[row["month"].isoformat()].append(row)
        history = []
        for month, values in sorted(by_month.items()):
            quantities = {_number(item.get("quantity")) for item in values}
            evidence = [item["evidence"] for item in values]
            quantity = next(iter(quantities)) if len(quantities) == 1 else None
            if len(quantities) > 1:
                assumptions.append({"kind": "conflicting_observation", "month": month, "evidence": evidence})
            history.append({"month": month, "quantity": quantity, "evidence": evidence})
        return history

    output = []
    for (product_id, supplier, sku, scope, unit), observations in sorted(
        series_rows.items(), key=lambda item: repr(item[0])
    ):
        assumptions = [{"kind": "completed_period_by_planning_cutoff", "cutoff": cutoff.isoformat()}]
        history = monthly_history(observations, assumptions)
        attribute = attributes.get(product_id, {})
        if any(row.get("unit_inferred") for row in observations):
            assumptions.append(
                {
                    "kind": "unit_inferred_from_consistent_sources",
                    "value": unit,
                    "evidence": attribute.get("evidence", []),
                }
            )
        category_candidates = attribute.get("category_candidates", [])
        category_year = attribute.get("category_year")
        category = (
            category_candidates[0]
            if len(category_candidates) == 1 and category_year and category_year <= planning.year
            else None
        )
        key = (product_id, scope, unit)
        item_inventory = inventory.get(key)
        stock_scope = scope
        embedded_groups = defaultdict(list)
        for row in embedded.get(product_id, []):
            embedded_groups[(row["scope"], row["unit"])].append(row)
        for (other_scope, other_unit), other_rows in embedded_groups.items():
            other_history = monthly_history(other_rows, [])
            actuals = {h["month"]: h["quantity"] for h in history if h["quantity"] is not None}
            comparable = [h for h in other_history if h["month"] in actuals and h["quantity"] is not None]
            matched = bool(comparable) and all(
                Decimal(h["quantity"]) == Decimal(actuals[h["month"]]) for h in comparable
            )
            assumptions.append(
                {
                    "kind": "embedded_sales_reconciliation",
                    "scope": other_scope,
                    "status": "match" if matched else "mismatch",
                    "compared_months": len(comparable),
                    "used_for_history": False,
                    "evidence": other_history[:1],
                }
            )
            # Matching report history permits an explicitly estimated scope link,
            # never a claim that either report covers a known physical warehouse.
            candidate_stock = inventory.get((product_id, other_scope, other_unit))
            if (
                supplier == "systeme"
                and len(embedded_groups) == 1
                and matched
                and unit
                and unit == other_unit
                and candidate_stock
            ):
                stock_scope = other_scope
                item_inventory = {**candidate_stock, "scope": scope, "unit": unit}
                assumptions.append(
                    {
                        "kind": "report_scope_assumption",
                        "from_scope": other_scope,
                        "to_scope": scope,
                        "basis": "matching_embedded_monthly_sales",
                    }
                )

        item_shipments = None
        if specs.get("supply_shipments") and specs.get("supply_shipment_lines"):
            candidates = shipments.get(product_id, [])
            matching = [r for r in candidates if r["scope"] == stock_scope]
            # An unrelated report is not evidence of zero incoming stock.
            item_shipments = [] if matching else None
            for row in matching:
                shipment = {k: _json(v) for k, v in row.items() if k not in {"product_id", "supplier_id"}}
                shipment["id"] = str(row["shipment_id"])
                shipment["scope"] = scope
                if shipment.get("unit") is None and unit:
                    shipment["unit"] = unit
                    assumptions.append(
                        {"kind": "quantity_rule_unit_inferred", "applies_to": "transit", "value": unit}
                    )
                if shipment["expected_on"] is None and item_inventory and item_inventory.get("as_of"):
                    import re

                    match = re.search(r"(?<!\d)(\d{1,2})[.](\d{1,2})(?![.\d])", shipment.get("header") or "")
                    if match:
                        try:
                            due = date(planning.year, int(match[2]), int(match[1]))
                        except ValueError:
                            due = None
                        if due and due >= planning:
                            shipment["expected_on"] = due.isoformat()
                            assumptions.append(
                                {
                                    "kind": "shipment_year_assumed_from_snapshot",
                                    "year": planning.year,
                                    "evidence": shipment["evidence"],
                                }
                            )
                item_shipments.append(shipment)
        item_rules = (
            [dict(rule) for rule in rules.get(product_id, [])] if specs.get("supply_quantity_rules") else None
        )
        for rule in item_rules or []:
            if rule["unit"] is None and unit:
                rule["unit"] = unit
                assumptions.append(
                    {"kind": "quantity_rule_unit_inferred", "value": unit, "evidence": rule["evidence"]}
                )
        if report_metrics.get(product_id):
            assumptions.append(
                {"kind": "reported_metrics", "values": report_metrics[product_id], "used_for_history": False}
            )
        transaction_evidence = []
        for (_, tx_scope, tx_unit), tx_rows in transactions_by_product.get(product_id, []):
            tx_rows = [r for r in tx_rows if r["month"] < cutoff.isoformat()]
            documents = defaultdict(list)
            for row in tx_rows:
                documents[(row["occurred_on"], row["document_number"])].append(row)
            totals = {
                doc: sum((_decimal(r["quantity"]) for r in items), Decimal(0))
                for doc, items in documents.items()
                if all(_decimal(r["quantity"]) is not None for r in items)
            }
            from statistics import median

            positive = [q for q in totals.values() if q > 0]
            level = median(positive) if positive else Decimal(0)
            mad = median(abs(q - level) for q in positive) if positive else Decimal(0)
            threshold = max(level * 3, level + mad * 5)
            anomalies = [
                {
                    "date": doc[0],
                    "document": doc[1],
                    "quantity": _number(q),
                    "regular_quantity": _number(level),
                    "evidence": [e for r in documents[doc] for e in r["evidence"]],
                }
                for doc, q in totals.items()
                if q > threshold
            ]
            tx_months = defaultdict(list)
            for row in tx_rows:
                tx_months[row["month"]].append(row)
            monthly = [
                {
                    "month": m,
                    "quantity": _number(sum((_decimal(r["quantity"]) for r in rr), Decimal(0)))
                    if all(_decimal(r["quantity"]) is not None for r in rr)
                    else None,
                }
                for m, rr in sorted(tx_months.items())
            ]
            transaction_evidence.append(
                {
                    "scope": tx_scope,
                    "unit": tx_unit,
                    "monthly_history": monthly,
                    "document_count": len(documents),
                    "anomaly_count": len(anomalies),
                    "anomalies": anomalies[:20],
                    "reconciliation": "scope_unconfirmed" if tx_scope != scope else "requires_monthly_match",
                    "customer_concentration": "unverified_customer_ids_absent",
                    "used_for_history": False,
                }
            )
        output.append(
            {
                "series_id": _stable_series_id(supplier, sku, scope, unit),
                "supplier": supplier,
                "sku": sku,
                "scope": scope,
                "unit": unit,
                "history": history,
                "category": category,
                "parameters": {
                    "category_available_from": f"{category_year}-01-01" if category_year else None,
                    "transaction_evidence": transaction_evidence,
                },
                "inventory": item_inventory,
                "shipments": item_shipments,
                "quantity_rules": item_rules,
                "assumptions": assumptions,
            }
        )
    selected = [{k: _json(v) for k, v in spec.items()} for table in sorted(specs) for spec in specs[table]]
    selected = sorted(
        {json.dumps(s, sort_keys=True): s for s in selected}.values(),
        key=lambda s: json.dumps(s, sort_keys=True),
    )
    return {
        "contract_version": "2",
        "planning_date": planning.isoformat(),
        "series": output,
        "parameters": {
            "history_cutoff": cutoff.isoformat(),
            "missing_months_preserved": True,
            "reported_seasonality": {str(supplier): values for supplier, values in seasonality.items()},
            "embedded_series_excluded": len({(r["product_id"], r["scope"], r["unit"]) for r in comparison}),
        },
        "source_selection": selected,
    }
