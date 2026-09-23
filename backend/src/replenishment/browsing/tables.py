"""SQL Core read projections; never aggregate competing source observations."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select

TABLES = {
    "catalog": "catalog_products",
    "suppliers": "catalog_suppliers",
    "workbooks": "intake_workbooks",
    "sheets": "intake_sheets",
    "products": "catalog_product_observations",
    "warehouses": "catalog_warehouses",
    "movements": "demand_movements",
    "monthly-sales": "demand_monthly_sales",
    "monthly-stock": "inventory_monthly_stock",
    "current-stock": "inventory_observations",
    "moq": "supply_quantity_rules",
    "shipments": "supply_shipments",
    "shipment-lines": "supply_shipment_lines",
    "report-metrics": "demand_report_metrics",
    "seasonality": "demand_seasonality_observations",
    "findings": "intake_findings",
    "runs": "calculation_runs",
    "calculation-inputs": "calculation_inputs",
    "forecasts": "calculation_forecasts",
    "drafts": "calculation_drafts",
}
FILTERS = (
    "supplier_id", "product_id", "workbook_id", "sheet_id", "normalizer_version",
    "warehouse_id", "metric", "kind", "status", "category_code", "sku",
    "run_id", "series_id", "supplier", "scope", "unit", "state", "target_month",
)
SEARCH = ("sku", "name", "supplier_article", "category_code", "original_path", "description",
          "document_number", "document_text", "label", "header", "code", "supplier_code")


def json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def projection(metadata, key):
    table = metadata.tables[TABLES[key]]
    columns = {col.name: col for col in table.c if col.name not in {"content", "layout"}}
    joined = table
    if key in {"forecasts", "drafts"}:
        inputs = metadata.tables["calculation_inputs"]
        joined = joined.join(inputs, (table.c.run_id == inputs.c.run_id)
                             & (table.c.series_id == inputs.c.series_id))
        columns.update({name: inputs.c[name] for name in ("supplier", "sku", "scope", "unit")})
    if key == "catalog":
        columns["product_id"] = table.c.id
    elif "product_id" in columns:
        products = metadata.tables["catalog_products"]
        joined = joined.join(products, products.c.id == table.c.product_id)
        columns["sku"] = products.c.sku
        columns["supplier_id"] = products.c.supplier_id
    if "supplier_id" in columns:
        suppliers = metadata.tables["catalog_suppliers"]
        joined = joined.join(suppliers, suppliers.c.id == columns["supplier_id"])
        columns["supplier_code"] = suppliers.c.code
        columns["supplier_name"] = suppliers.c.name
    if "warehouse_id" in columns:
        warehouse = metadata.tables["catalog_warehouses"]
        joined = joined.outerjoin(warehouse, warehouse.c.id == columns["warehouse_id"])
        columns["warehouse_name"] = warehouse.c.name
    if "source_row_id" in columns:
        rows = metadata.tables["intake_rows"]
        joined = joined.join(rows, rows.c.id == columns["source_row_id"])
        columns["row_number"] = rows.c.row_number
        columns["sheet_id"] = rows.c.sheet_id
    if "source_sheet_id" in columns:
        columns["sheet_id"] = columns["source_sheet_id"]
    if "sheet_id" in columns:
        sheets = metadata.tables["intake_sheets"]
        joined = joined.join(sheets, sheets.c.id == columns["sheet_id"])
        columns["sheet_name"] = sheets.c.name
        columns["workbook_id"] = sheets.c.workbook_id
    if "workbook_id" in columns:
        books = metadata.tables["intake_workbooks"]
        joined = joined.join(books, books.c.id == columns["workbook_id"])
        columns["original_path"] = books.c.original_path
        columns["sha256"] = books.c.sha256
    return joined, columns


def describe_tables(metadata):
    result = []
    for key in TABLES:
        _, columns = projection(metadata, key)
        result.append({
            "key": key,
            "columns": [{"key": name, "type": str(col.type), "nullable": (
                name == "warehouse_name" or bool(getattr(col, "nullable", True))
            )} for name, col in columns.items()],
            "sortable": list(columns),
            "filters": [name for name in FILTERS if name in columns],
        })
    return result


def filter_conditions(columns, key, filters, q):
    """Apply the same filters to paginated browsing and CSV exports."""
    conditions = []
    for name, value in filters.items():
        if value is None:
            continue
        if name not in columns:
            raise ValueError(f"Filter {name} is not supported for {key}")
        if name == "warehouse_id" and value == "unknown":
            conditions.append(columns[name].is_(None))
        else:
            conditions.append(columns[name] == value)
    if q:
        searchable = [columns[name] for name in SEARCH if name in columns]
        if not searchable:
            raise ValueError(f"Text search is not supported for {key}")
        # Literal substring, including %, _, and backslash; all values are bound parameters.
        needle = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(or_(*(cast(col, String).ilike(f"%{needle}%", escape="\\")
                                for col in searchable)))
    return conditions


def read_table(connection, metadata, key, *, page, page_size, sort, direction, q, filters):
    joined, columns = projection(metadata, key)
    sort = sort or "id"
    if sort not in columns:
        raise ValueError(f"Unsupported sort column: {sort}")
    conditions = filter_conditions(columns, key, filters, q)
    if key in {"calculation-inputs", "forecasts", "drafts"}:
        runs = metadata.tables["calculation_runs"]
        conditions.append(columns["run_id"].in_(select(runs.c.id).where(runs.c.status == "completed")))
    order = columns[sort].desc() if direction == "desc" else columns[sort].asc()
    statement = select(*(col.label(name) for name, col in columns.items())).select_from(joined)
    statement = statement.where(*conditions).order_by(order.nulls_last(), columns["id"].asc())
    total = connection.scalar(select(func.count()).select_from(joined).where(*conditions))
    items = connection.execute(statement.offset((page - 1) * page_size).limit(page_size)).mappings()
    return {"table": key, "items": [json_value(dict(row)) for row in items],
            "total": total, "page": page, "page_size": page_size}


def source_row(connection, metadata, row_id):
    rows = metadata.tables["intake_rows"]
    sheets = metadata.tables["intake_sheets"]
    books = metadata.tables["intake_workbooks"]
    statement = select(rows, sheets.c.name.label("sheet_name"), sheets.c.workbook_id,
                       books.c.original_path, books.c.sha256).select_from(
        rows.join(sheets, rows.c.sheet_id == sheets.c.id).join(books, sheets.c.workbook_id == books.c.id)
    ).where(rows.c.id == row_id)
    row = connection.execute(statement).mappings().one_or_none()
    return json_value(dict(row)) if row else None
