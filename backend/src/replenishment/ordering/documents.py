"""Transactional document operations. Caller owns the transaction and supplies source metadata."""

from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import func, select

from replenishment.ordering.models import Employee, OrderDocument, OrderDocumentLine

employees = Employee.__table__
documents = OrderDocument.__table__
lines = OrderDocumentLine.__table__


class DocumentError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def quantity(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number >= Decimal("1e18"):
            raise ValueError
        with localcontext() as context:
            context.prec = 42
            if number != number.quantize(Decimal("1e-12")):
                raise ValueError
        return number
    except (InvalidOperation, ValueError, TypeError) as error:
        raise DocumentError(422, "Quantity must be finite, nonnegative and fit Numeric(30,12)") from error


def employee(connection, employee_id):
    if connection.scalar(select(employees.c.id).where(employees.c.id == employee_id)) is None:
        raise DocumentError(404, "Employee not found")


def document(connection, document_id, *, write=False):
    row = (
        connection.execute(
            select(documents).where(documents.c.id == document_id).with_for_update(read=not write)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise DocumentError(404, "Order document not found")
    return dict(row)


def detail(connection, metadata, document_id):
    result = document(connection, document_id)
    drafts = metadata.tables["calculation_drafts"]
    inputs = metadata.tables["calculation_inputs"]
    runs = metadata.tables["calculation_runs"]
    forecasts = metadata.tables["calculation_forecasts"]
    result["run"] = dict(
        connection.execute(select(runs).where(runs.c.id == result["run_id"])).mappings().one()
    )
    identities = {row["id"]: dict(row) for row in connection.execute(select(employees)).mappings()}
    for role in ("creator", "last_editor", "approver"):
        result[role] = identities.get(result[f"{role}_id"])
    source_drafts = {
        row["series_id"]: dict(row)
        for row in connection.execute(select(drafts).where(drafts.c.run_id == result["run_id"])).mappings()
    }
    source_inputs = {
        row["series_id"]: dict(row)
        for row in connection.execute(select(inputs).where(inputs.c.run_id == result["run_id"])).mappings()
    }
    source_forecasts = {}
    for row in connection.execute(
        select(forecasts).where(forecasts.c.run_id == result["run_id"]).order_by(forecasts.c.target_month)
    ).mappings():
        source_forecasts.setdefault(row["series_id"], []).append(dict(row))
    result["lines"] = []
    for row in connection.execute(
        select(lines).where(lines.c.document_id == document_id).order_by(lines.c.series_id)
    ).mappings():
        item = dict(row)
        item["recommendation"] = source_drafts[row["series_id"]]
        item["input"] = source_inputs[row["series_id"]]
        item["forecasts"] = source_forecasts.get(row["series_id"], [])
        result["lines"].append(item)
    return result


def create(connection, metadata, run_id, employee_id):
    employee(connection, employee_id)
    runs = metadata.tables["calculation_runs"]
    # The run lock serializes duplicate creation before a document row exists.
    state = connection.scalar(select(runs.c.status).where(runs.c.id == run_id).with_for_update())
    if state is None:
        raise DocumentError(404, "Calculation run not found")
    existing = connection.scalar(select(documents.c.id).where(documents.c.run_id == run_id))
    if existing is not None:
        return detail(connection, metadata, existing)
    if state != "completed":
        raise DocumentError(409, "Calculation run is not completed")
    drafts = metadata.tables["calculation_drafts"]
    source = connection.execute(select(drafts).where(drafts.c.run_id == run_id)).mappings().all()
    if not source:
        raise DocumentError(409, "Calculation run is empty")
    document_id = connection.scalar(
        documents.insert()
        .values(run_id=run_id, creator_id=employee_id, last_editor_id=employee_id)
        .returning(documents.c.id)
    )
    connection.execute(
        lines.insert(),
        [
            dict(
                document_id=document_id,
                run_id=run_id,
                series_id=row["series_id"],
                quantity=row["quantity"],
                purchase_unit=row["purchase_unit"],
                included=True,
            )
            for row in source
        ],
    )
    return detail(connection, metadata, document_id)


def validate_line(line, *, complete=False):
    number = quantity(line["quantity"]) if line["quantity"] is not None else None
    unit = line["purchase_unit"]
    if complete and (number is None or not unit):
        raise DocumentError(422, "Included lines require quantity and purchase unit")
    if complete and line["recommendation"]["state"] == "blocked":
        if not (line["manual_completion_reason"] or "").strip():
            raise DocumentError(422, "Blocked lines require a manual completion reason")
    if number is None or number == 0:
        return
    for rule in line["input"]["snapshot"].get("quantity_rules") or []:
        if not rule.get("interpretation_confirmed") or not unit or rule.get("unit") != unit:
            continue  # Unknown interpretations/units/conversions never become invented constraints.
        if rule.get("kind") not in {"minimum_shipment", "order_multiple"}:
            continue
        value = quantity(rule.get("value"))
        if rule["kind"] == "minimum_shipment" and number < value:
            raise DocumentError(422, "Quantity is below confirmed minimum")
        if rule["kind"] == "order_multiple":
            with localcontext() as context:
                context.prec = 60
                if value == 0 or number % value != 0:
                    raise DocumentError(422, "Quantity violates confirmed order multiple")


def mutate(connection, metadata, document_id, employee_id, expected_revision, *, edits=None, approve=False):
    employee(connection, employee_id)
    current = document(connection, document_id, write=True)
    if current["status"] == "approved":
        raise DocumentError(409, "Approved document is permanently locked")
    if current["revision"] != expected_revision:
        raise DocumentError(409, "Stale document revision")
    result = detail(connection, metadata, document_id)
    changes = dict(revision=expected_revision + 1, updated_at=func.now())
    if approve:
        included = [line for line in result["lines"] if line["included"]]
        for line in included:
            validate_line(line, complete=True)
        if not any(line["quantity"] > 0 for line in included):
            raise DocumentError(422, "Approval requires a positive included quantity")
        changes.update(status="approved", approver_id=employee_id, approved_at=func.now())
    else:
        changes["last_editor_id"] = employee_id
        if "note" in edits:
            changes["note"] = edits["note"]
        by_id = {line["id"]: line for line in result["lines"]}
        seen = set()
        for edit in edits.get("lines", []):
            line_id = edit["id"]
            if line_id not in by_id:
                raise DocumentError(404, "Document line not found")
            if line_id in seen:
                raise DocumentError(422, "Duplicate line edit")
            seen.add(line_id)
            line = by_id[line_id]
            values = {key: value for key, value in edit.items() if key != "id"}
            if "quantity" in values:
                values["quantity"] = quantity(values["quantity"])
            if "purchase_unit" in values:
                known = line["recommendation"]["purchase_unit"]
                if known is not None and values["purchase_unit"] != known:
                    raise DocumentError(422, "Known purchase unit cannot change")
            line.update(values)
            validate_line(line)
            if values:
                connection.execute(lines.update().where(lines.c.id == line_id).values(**values))
    connection.execute(documents.update().where(documents.c.id == document_id).values(**changes))
    return detail(connection, metadata, document_id)


def summaries(connection, *, page, page_size, run_id=None, status=None):
    statement = select(documents)
    if run_id is not None:
        statement = statement.where(documents.c.run_id == run_id)
    if status is not None:
        statement = statement.where(documents.c.status == status)
    total = connection.scalar(select(func.count()).select_from(statement.subquery()))
    items = (
        connection.execute(
            statement.order_by(documents.c.created_at.desc(), documents.c.id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        .mappings()
        .all()
    )
    return dict(items=[dict(row) for row in items], total=total, page=page, page_size=page_size)
