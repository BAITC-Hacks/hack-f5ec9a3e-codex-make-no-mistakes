"""Read-only composition of selected source evidence into explicit planning scenarios.

This adapter deliberately does not establish warehouse scope, stock freshness, transit
completeness or purchase conversions. Those are business inputs, not join defaults.
"""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from replenishment.browsing.tables import projection
from replenishment.planning.models import PlanningRequest

PRODUCT_SOURCES = (
    "products", "movements", "monthly-sales", "monthly-stock", "current-stock",
    "moq", "shipment-lines", "report-metrics",
)


def _read(connection, metadata, key, product_id, version=None, workbook_ids=()):
    joined, columns = projection(metadata, key)
    conditions = [columns["product_id"] == product_id]
    if version is not None:
        conditions.append(columns["normalizer_version"] == version)
    if workbook_ids:
        conditions.append(columns["workbook_id"].in_(workbook_ids))
    return [dict(row) for row in connection.execute(
        select(*(col.label(name) for name, col in columns.items()))
        .select_from(joined).where(*conditions).order_by(columns["id"])
    ).mappings()]


def _references(key, records, *, individual=False):
    result, seen = [], set()
    for record in records:
        identity = (record["workbook_id"], record["normalizer_version"],
                    record.get("source_row_id") if individual else None)
        if identity in seen:
            continue
        seen.add(identity)
        ref = {
            "label": f"{key}: {record['original_path']} [sha256 {record['sha256']}]",
            "workbook_id": str(record["workbook_id"]),
            "normalizer_version": record["normalizer_version"],
        }
        if individual and record.get("source_row_id"):
            ref["source_row_id"] = str(record["source_row_id"])
        result.append(ref)
    return result


def _unique(records, field):
    values = {row[field] for row in records if row.get(field) is not None}
    return next(iter(values)) if len(values) == 1 else None


def prepare_source_input(connection, metadata, request):
    """Return a source snapshot without choosing competing normalizer/book versions."""
    products = metadata.tables["catalog_products"]
    suppliers = metadata.tables["catalog_suppliers"]
    identities = {row["id"]: dict(row) for row in connection.execute(
        select(products.c.id, products.c.sku, products.c.supplier_id,
               suppliers.c.name.label("supplier"))
        .join(suppliers, products.c.supplier_id == suppliers.c.id)
        .where(products.c.id.in_(request.product_ids))
    ).mappings()}
    if len(identities) != len(request.product_ids):
        raise ValueError("One or more selected products do not exist")
    rows, usage = [], []
    for product_id in request.product_ids:
        product = identities[product_id]
        records = {key: _read(connection, metadata, key, product_id,
                              request.normalizer_version, request.workbook_ids)
                   for key in PRODUCT_SOURCES}
        versions = {row["normalizer_version"] for values in records.values() for row in values}
        if len(versions) > 1:
            raise ValueError("Multiple normalizer versions: select normalizer_version explicitly")
        notes = [
            "Source preparation is a scenario: warehouse scope, stock freshness, delivery completeness, "
            "lead time and purchase units require confirmation.",
            "No-transaction days mean zero recorded sales, not confirmed zero underlying demand.",
            "Customer IDs, exact stockout intervals, supplier lead times and BOM are unavailable.",
        ]
        sources = []
        for key, values in records.items():
            individual = key in ("current-stock", "moq", "shipment-lines")
            sources.extend(_references(key, values, individual=individual))

        def record_usage(source, status, reason, product=product):
            usage.append({"source": f"{product['supplier']} / {product['sku']} / {source}",
                          "status": status, "reason": reason})

        names = {r["name"] for r in records["products"] if r["name"]}
        if len(names) > 1:
            notes.append("Product names differ across sources; identify this row by exact supplier/SKU.")
        categories = {r["category_code"] for r in records["products"] if r["category_code"]}
        category = next(iter(categories)) if len(categories) == 1 else None
        notes.append("Category codes have no confirmed dictionary/policy; no category multiplier applied.")
        record_usage("products", "contextual" if records["products"] else "unavailable",
                     "Exact supplier/SKU identity; conflicting names are not selected automatically; "
                     "category policy is unconfirmed.")

        history_start = request.planning_date - timedelta(days=56)
        history_end = request.planning_date - timedelta(days=1)
        movements = [r for r in records["movements"] if r["warehouse_name"] == request.warehouse]
        movement_books = {r["workbook_id"] for r in movements}
        sales = []
        units = {r["unit"] for r in movements}
        stock_unit = next(iter(units)) if len(units) == 1 else "unknown"
        if len(movement_books) > 1 or len(units) != 1:
            record_usage("movements", "conflicting" if movements else "unavailable",
                         "Select one movement workbook and one stock unit; history was not combined.")
            notes.append("Sales source/unit unresolved; provide explicit demand or select a workbook.")
        else:
            selected = [r for r in movements if
                        datetime.combine(history_start, time.min) <= r["occurred_at"]
                        < datetime.combine(request.planning_date, time.min)]
            totals = defaultdict(Decimal)
            rejected = Counter()
            for movement in selected:
                quantity = movement["quantity"]
                if quantity is None:
                    rejected["missing_quantity"] += 1
                elif quantity < 0:
                    rejected["negative_unresolved"] += 1
                elif not movement["document_text"].startswith("Расходная накладная"):
                    rejected["other_document"] += 1
                elif quantity > 0:
                    identity = (movement["occurred_at"].date(), movement["document_number"],
                                movement["document_text"])
                    totals[identity] += quantity
            sales = [{"day": day, "quantity": quantity, "document": number + " | " + document,
                      "customer_id": None}
                     for (day, number, document), quantity in sorted(totals.items())]
            if rejected:
                notes.append(f"Movement rows excluded from gross-positive demand: {dict(rejected)}.")
            record_usage("movements", "used" if sales else "unavailable",
                         f"Gross positive outgoing document totals for {request.warehouse}, "
                         f"{history_start} through {history_end}; no customer inference. "
                         f"Excluded: {dict(rejected)}.")

        stock = [r for r in records["current-stock"] if r["metric"] == "free"]
        stock_row = stock[0] if len(stock) == 1 else None
        free = stock_row["quantity"] if stock_row else None
        if free is not None and free < 0:
            notes.append("Negative free stock requires reconciliation; it was not made positive.")
            free = None
        stock_status = "contextual" if stock_row else "conflicting" if stock else "unavailable"
        record_usage("current-stock", stock_status,
                     "Free stock retained as reported; selected warehouse and planning-date freshness "
                     "are unconfirmed. On-hand/reserved/components are not added to free stock.")

        incoming = []
        shipments = metadata.tables["supply_shipments"]
        warehouse_table = metadata.tables["catalog_warehouses"]
        shipment_ids = {line["shipment_id"] for line in records["shipment-lines"]}
        shipment_map = {r["id"]: dict(r) for r in connection.execute(
            select(shipments, warehouse_table.c.name.label("warehouse_name"))
            .outerjoin(warehouse_table, shipments.c.warehouse_id == warehouse_table.c.id)
            .where(shipments.c.id.in_(shipment_ids))
        ).mappings()} if shipment_ids else {}
        for line in records["shipment-lines"]:
            shipment = shipment_map[line["shipment_id"]]
            quantity = line["quantity"]
            if quantity is not None and quantity < 0:
                notes.append("A negative incoming quantity was retained in source evidence for review.")
                quantity = None
            incoming.append({"id": str(line["shipment_id"]), "quantity": quantity,
                             "expected_on": shipment["expected_on"],
                             "warehouse": shipment["warehouse_name"], "stock_unit": line["unit"]})
        record_usage("shipments", "contextual" if incoming else "unavailable",
                     "Reported delivery lines retained, including unknown quantity/year/warehouse/unit; "
                     "no assumption that the report covers every incoming delivery.")
        if len({r["shipment_id"] for r in records["shipment-lines"]}) != len(incoming):
            notes.append("Repeated delivery identities require reconciliation before confirming incoming.")

        rules = records["moq"]
        minimum = _unique([r for r in rules if r["kind"] == "minimum_shipment"], "value")
        multiple = _unique([r for r in rules if r["kind"] == "order_multiple"], "value")
        if minimum is not None and minimum < 0:
            minimum = None
        if multiple is not None and multiple <= 0:
            multiple = None
        record_usage("moq", "contextual" if rules else "unavailable",
                     "Minimum and multiple are separate source candidates; meanings/units must be confirmed. "
                     "Conflicting values stay unknown.")
        for key, reason in (
            ("monthly-sales", "Separate warehouse-unspecified report; not added to movement totals."),
            ("monthly-stock", "Monthly snapshots do not establish current free stock or stockout duration."),
            ("report-metrics", "Historical growth/coverage/formula outputs are evidence, not an independent "
             "growth forecast; no automatic formula adoption."),
        ):
            record_usage(key, "contextual" if records[key] else "unavailable", reason)
            notes.append(f"{key}: {reason}")

        seasonal_join, seasonal_columns = projection(metadata, "seasonality")
        seasonal_conditions = [seasonal_columns["supplier_id"] == product["supplier_id"]]
        if versions:
            seasonal_conditions.append(seasonal_columns["normalizer_version"] == next(iter(versions)))
        if request.workbook_ids:
            seasonal_conditions.append(seasonal_columns["workbook_id"].in_(request.workbook_ids))
        seasonal = [dict(r) for r in connection.execute(
            select(*(col.label(name) for name, col in seasonal_columns.items()))
            .select_from(seasonal_join).where(*seasonal_conditions)
        ).mappings()]
        sources.extend(_references("seasonality", seasonal))
        record_usage("seasonality", "contextual" if seasonal else "unavailable",
                     "Supplier aggregates/repeated summaries; no per-SKU use without explicit policy.")
        notes.append("Supplier seasonality is contextual; provide explicit scenario month factors.")
        rows.append({
            "row_id": str(product_id), "supplier": product["supplier"], "sku": product["sku"],
            "name": next(iter(names)) if len(names) == 1 else "", "warehouse": request.warehouse,
            "stock_unit": stock_unit, "purchase_unit": None, "free_stock": free,
            "stock_as_of": stock_row["as_of"] if stock_row else None, "stock_scope_confirmed": False,
            "incoming_complete": False, "constraints_confirmed": False,
            "minimum_order": minimum, "order_multiple": multiple, "category": category,
            "history_start": history_start if sales else None, "history_end": history_end if sales else None,
            "sales": sales, "incoming": incoming, "basis": "observed", "notes": notes, "sources": sources,
        })
    scenario = PlanningRequest.model_validate({"planning_date": request.planning_date, "rows": rows})
    return {"input": scenario.model_dump(mode="json"), "usage": usage}
