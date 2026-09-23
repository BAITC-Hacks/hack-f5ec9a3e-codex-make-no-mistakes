"""Compose pure calculation with atomic, content-addressed result storage."""

import csv
import hashlib
import io
import json
import platform
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from replenishment.calculation.models import CalculationInput, CalculationRun, ForecastValue, OrderDraftLine


def json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, UUID)):
        return value.isoformat() if isinstance(value, date) else str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def code_versions():
    """Hash the actual calculation implementation at invocation, never during import."""
    directory = Path(__file__).parent
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(directory.glob("*.py"))
    }
    lock = directory.parents[2] / "uv.lock"
    if lock.is_file():
        hashes["uv.lock"] = hashlib.sha256(lock.read_bytes()).hexdigest()
    return {
        "code_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "files": hashes,
        "python": platform.python_version(),
    }


def _number(value):
    if value is None:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Invalid result quantity") from error
    if not number.is_finite() or number < 0 or number >= Decimal("1e18") or number.as_tuple().exponent < -12:
        raise ValueError("Result quantity must be finite, nonnegative and fit Numeric(30,12)")
    return number


def _validate(batch, results):
    from replenishment.calculation.contracts import validate_results

    validate_results(batch, results)
    # Validate cardinality and identity before any child insert. DB constraints are a second boundary.
    identities = {row["series_id"]: row for row in batch["series"]}
    if len(identities) != len(batch["series"]):
        raise ValueError("Duplicate input series")
    planning = date.fromisoformat(batch["planning_date"])
    targets = set()
    for offset in (1, 2, 3):
        year, month = divmod(planning.year * 12 + planning.month - 1 + offset, 12)
        targets.add(date(year, month + 1, 1).isoformat())
    expected = {(series, month) for series in identities for month in targets}
    seen = set()
    for row in results["forecasts"]:
        key = (row["series_id"], row["target_month"])
        if key not in expected or key in seen:
            raise ValueError("Forecast results do not match requested series and months")
        seen.add(key)
        source = identities[row["series_id"]]
        if any(row.get(field) != source.get(field) for field in ("supplier", "sku", "scope", "unit")):
            raise ValueError("Changed forecast identity")
        quantity = _number(row["quantity"])
        if row["status"] not in {"ok", "insufficient_data", "unsupported"}:
            raise ValueError("Invalid forecast status")
        if (row["status"] == "ok") != (quantity is not None):
            raise ValueError("Forecast status disagrees with quantity")
    if seen != expected:
        raise ValueError("Exactly three forecasts are required per series")
    drafts = results["drafts"]
    if len(drafts) != len(identities) or {row["series_id"] for row in drafts} != set(identities):
        raise ValueError("One draft is required per series")
    for row in drafts:
        if row["state"] not in {"ready", "estimated", "blocked"}:
            raise ValueError("Invalid draft state")
        if (row["state"] == "blocked") != (_number(row["quantity"]) is None):
            raise ValueError("Draft state disagrees with quantity")
        if row["state"] == "blocked" and not row.get("blocking_reason"):
            raise ValueError("Blocked draft requires a reason")


def run_calculation(engine, batch, *, rerun=False, calculator=None):
    """Identical inputs/versions reuse a completed run; failed work leaves only failure metadata."""
    if calculator is None:
        from replenishment.calculation import calculate

        calculator = calculate
    batch = json_value(batch)
    versions = code_versions()
    fingerprint_batch = {key: value for key, value in batch.items() if key != "llm_accounting"}
    fingerprint_batch["parameters"] = {
        key: value for key, value in batch.get("parameters", {}).items() if key != "llm_pilot"
    }
    encoded = json.dumps(
        {"batch": fingerprint_batch, "versions": versions},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    run_id = uuid4()
    run = {
        "id": run_id,
        "fingerprint": fingerprint,
        "contract_version": batch["contract_version"],
        "planning_date": date.fromisoformat(batch["planning_date"]),
        "status": "running",
        "source_selection": batch.get("source_selection", []),
        "parameters": batch.get("parameters", {}),
        "versions": versions,
        "quality": {},
        "llm_accounting": batch.get("llm_accounting", {}),
    }
    runs = CalculationRun.__table__
    try:
        with engine.begin() as connection:
            # Only identical requests serialize; unrelated source/date selections remain independent.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(fingerprint[:16], 16) - 2**63}
            )
            if not rerun:
                existing = connection.execute(
                    select(runs.c.id)
                    .where(runs.c.fingerprint == fingerprint, runs.c.status == "completed")
                    .order_by(runs.c.created_at.desc(), runs.c.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if existing:
                    return {"id": existing, "status": "completed", "reused": True, "fingerprint": fingerprint}
            connection.execute(runs.insert(), run)
            results = json_value(calculator(batch))
            _validate(batch, results)
            inputs = [
                {
                    "run_id": run_id,
                    "series_id": series["series_id"],
                    "supplier": series["supplier"],
                    "sku": series["sku"],
                    "scope": series["scope"],
                    "unit": series.get("unit"),
                    "snapshot": series,
                }
                for series in batch["series"]
            ]
            if inputs:
                connection.execute(CalculationInput.__table__.insert(), inputs)
            forecasts = [
                {
                    "run_id": run_id,
                    "series_id": row["series_id"],
                    "target_month": date.fromisoformat(row["target_month"]),
                    "quantity": _number(row["quantity"]),
                    "model": row["model"],
                    "status": row["status"],
                    "explanation": row["explanation"],
                }
                for row in results["forecasts"]
            ]
            if forecasts:
                connection.execute(ForecastValue.__table__.insert(), forecasts)
            drafts = [
                {
                    "run_id": run_id,
                    "series_id": row["series_id"],
                    "quantity": _number(row["quantity"]),
                    "purchase_unit": row.get("purchase_unit", row.get("unit")),
                    "coverage_start": date.fromisoformat(row["coverage_start"]),
                    "coverage_end": date.fromisoformat(row["coverage_end"]),
                    "urgency": row["urgency"],
                    "state": row["state"],
                    "blocking_reason": row.get("blocking_reason"),
                    "components": row["components"],
                    "evidence": row["evidence"],
                    "assumptions": row.get("assumptions", []),
                }
                for row in results["drafts"]
            ]
            if drafts:
                connection.execute(OrderDraftLine.__table__.insert(), drafts)
            connection.execute(
                runs.update()
                .where(runs.c.id == run_id)
                .values(
                    status="completed",
                    completed_at=func.now(),
                    quality=results.get("quality", {}),
                    llm_accounting=results.get("llm_accounting", batch.get("llm_accounting", {})),
                )
            )
    except Exception as error:
        # The previous transaction rolled back every input/result and its running marker.
        try:
            with engine.begin() as connection:
                connection.execute(
                    runs.insert(),
                    {
                        **run,
                        "status": "failed",
                        "failure": {
                            "type": type(error).__name__,
                            "message": "Calculation or persistence failed",
                        },
                    },
                )
        except Exception:
            pass  # A database outage can also prevent failure recording; preserve the original exception.
        raise
    return {"id": run_id, "status": "completed", "reused": False, "fingerprint": fingerprint}


def export_csv(connection, metadata, run_id, supplier=None):
    """Recommendation document from stored quantities, never a supplier submission."""
    runs, inputs, drafts = (metadata.tables[f"calculation_{name}"] for name in ("runs", "inputs", "drafts"))
    if connection.scalar(select(runs.c.status).where(runs.c.id == run_id)) != "completed":
        raise ValueError("Completed calculation run not found")
    statement = (
        select(
            inputs.c.supplier,
            inputs.c.sku,
            inputs.c.scope,
            inputs.c.unit.label("source_unit"),
            drafts.c.purchase_unit.label("unit"),
            drafts,
        )
        .select_from(
            drafts.join(
                inputs, (drafts.c.run_id == inputs.c.run_id) & (drafts.c.series_id == inputs.c.series_id)
            )
        )
        .where(drafts.c.run_id == run_id)
        .order_by(inputs.c.supplier, drafts.c.series_id)
    )
    if supplier is not None:
        statement = statement.where(inputs.c.supplier == supplier)
    output = io.StringIO(newline="")
    fields = [
        "document_type",
        "run_id",
        "supplier",
        "sku",
        "scope",
        "unit",
        "source_unit",
        "quantity",
        "state",
        "coverage_start",
        "coverage_end",
        "urgency",
        "blocking_reason",
        "components",
        "evidence",
        "assumptions",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for stored in connection.execute(statement).mappings():
        row = {key: json_value(stored[key]) for key in fields if key != "document_type"}
        row["document_type"] = "recommendation_only"
        # Source-row links recover workbook/path details through the read API;
        # repeating those long paths for every cell makes a catalogue CSV huge.
        row["evidence"] = [
            {
                key: value
                for key, value in evidence.items()
                if key in {"source_row_id", "source_column", "normalizer_version", "cell"}
            }
            if isinstance(evidence, dict) and "source_row_id" in evidence
            else evidence
            for evidence in row["evidence"]
        ]
        for key in ("components", "evidence", "assumptions"):
            row[key] = json.dumps(row[key], ensure_ascii=False, sort_keys=True)
        # Protect identifiers/labels from spreadsheet formula interpretation. Quantities remain exact.
        for key in ("supplier", "sku", "scope", "unit", "source_unit", "blocking_reason"):
            if isinstance(row[key], str) and row[key].startswith(("=", "+", "-", "@", "\t", "\r")):
                row[key] = "'" + row[key]
        writer.writerow(row)
    return output.getvalue()
