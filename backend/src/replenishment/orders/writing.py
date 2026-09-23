"""Transactional scenario commands. The API supplies validated server-calculated snapshots."""

import csv
import io
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from replenishment.orders.models import Scenario, ScenarioApproval, ScenarioRevision


class ScenarioNotFound(Exception):
    pass


class ScenarioConflict(Exception):
    pass


class InvalidScenario(ValueError):
    pass


def _name(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise InvalidScenario(f"{label} must contain 1 to 200 characters")
    return value.strip()


def _check_overrides(result: dict, overrides: list[dict]) -> None:
    rows = {row["row_id"]: row for row in result["rows"]}
    seen = set()
    for override in overrides:
        row_id = override["row_id"]
        if row_id in seen or row_id not in rows:
            raise InvalidScenario("Overrides must identify unique existing rows")
        seen.add(row_id)
        if rows[row_id]["status"] == "needs_input":
            raise InvalidScenario(f"Cannot override a row needing input: {row_id}")
        if not isinstance(override["reason"], str) or not override["reason"].strip():
            raise InvalidScenario("An override requires a nonblank reason")
        try:
            quantity = Decimal(str(override["quantity"]))
        except (InvalidOperation, ValueError) as error:
            raise InvalidScenario("Override quantity must be a finite nonnegative decimal") from error
        if not quantity.is_finite() or quantity < 0:
            raise InvalidScenario("Override quantity must be a finite nonnegative decimal")


def _load(connection: Connection, scenario_id: UUID, *, lock: bool = False) -> dict[str, Any]:
    scenarios = Scenario.__table__
    query = select(scenarios).where(scenarios.c.id == scenario_id)
    if lock:
        query = query.with_for_update()
    scenario = connection.execute(query).mappings().first()
    if scenario is None:
        raise ScenarioNotFound("Scenario not found")
    revisions = ScenarioRevision.__table__
    revision = connection.execute(select(revisions).where(
        revisions.c.scenario_id == scenario_id, revisions.c.revision == scenario["revision"]
    )).mappings().one()
    approvals = ScenarioApproval.__table__
    approval = connection.execute(select(approvals).where(
        approvals.c.scenario_id == scenario_id, approvals.c.revision == scenario["revision"]
    )).mappings().first()
    return {
        "id": scenario_id, "name": revision["name"], "revision": scenario["revision"],
        "input": revision["input"], "result": revision["result"], "overrides": revision["overrides"],
        "approved_revision": approval["revision"] if approval else None,
        "approved_by": approval["approved_by"] if approval else None,
        "approved_at": approval["approved_at"] if approval else None,
        "updated_at": scenario["updated_at"],
    }


def _expect(detail: dict, expected_revision: int) -> None:
    if detail["revision"] != expected_revision:
        raise ScenarioConflict(f"Stale revision: current revision is {detail['revision']}")


def list_scenarios(engine: Engine) -> dict:
    scenarios, approvals = Scenario.__table__, ScenarioApproval.__table__
    with engine.connect() as connection:
        rows = connection.execute(select(
            scenarios.c.id, scenarios.c.name, scenarios.c.revision,
            approvals.c.revision.label("approved_revision"), scenarios.c.updated_at,
        ).outerjoin(approvals, (approvals.c.scenario_id == scenarios.c.id)
                    & (approvals.c.revision == scenarios.c.revision))
          .order_by(scenarios.c.updated_at.desc(), scenarios.c.id)).mappings().all()
        return {"items": [dict(row) for row in rows]}


def get_scenario(engine: Engine, scenario_id: UUID) -> dict:
    # Locking prevents a writer from changing the head between snapshot reads.
    with engine.begin() as connection:
        return _load(connection, scenario_id, lock=True)


def create_scenario(engine: Engine, *, name: str, input: dict, result: dict) -> dict:
    name = _name(name, "Scenario name")
    scenario_id = uuid4()
    with engine.begin() as connection:
        connection.execute(Scenario.__table__.insert().values(id=scenario_id, name=name, revision=1))
        connection.execute(ScenarioRevision.__table__.insert().values(
            scenario_id=scenario_id, revision=1, name=name, input=input, result=result,
            overrides=[], actor="local-demo",
        ))
        return _load(connection, scenario_id)


def update_scenario(
    engine: Engine, scenario_id: UUID, *, expected_revision: int, name: str,
    input: dict, result: dict, overrides: list[dict],
) -> dict:
    name = _name(name, "Scenario name")
    _check_overrides(result, overrides)
    with engine.begin() as connection:
        current = _load(connection, scenario_id, lock=True)
        _expect(current, expected_revision)
        revision = expected_revision + 1
        connection.execute(ScenarioRevision.__table__.insert().values(
            scenario_id=scenario_id, revision=revision, name=name, input=input, result=result,
            overrides=overrides, actor="local-demo",
        ))
        connection.execute(Scenario.__table__.update().where(Scenario.id == scenario_id).values(
            revision=revision, name=name, updated_at=datetime.now(UTC),
        ))
        return _load(connection, scenario_id)


def approve_scenario(
    engine: Engine, scenario_id: UUID, *, expected_revision: int,
    approved_by: str, acknowledge_scenario: bool = False,
) -> dict:
    approved_by = _name(approved_by, "Approval actor")
    with engine.begin() as connection:
        current = _load(connection, scenario_id, lock=True)
        _expect(current, expected_revision)
        rows = current["result"]["rows"]
        if not rows or any(row["status"] == "needs_input" for row in rows):
            raise ScenarioConflict("Every row must be calculable before approval")
        if any(row["status"] == "scenario_only" for row in rows) and not acknowledge_scenario:
            raise ScenarioConflict("Explicit acknowledgement is required for assumed or synthetic scenarios")
        if current["approved_revision"] is not None:
            if current["approved_by"] != approved_by:
                raise ScenarioConflict("This revision is already approved; approval attribution is immutable")
            return current
        connection.execute(ScenarioApproval.__table__.insert().values(
            scenario_id=scenario_id, revision=expected_revision, approved_by=approved_by,
            acknowledge_scenario=acknowledge_scenario,
        ))
        connection.execute(Scenario.__table__.update().where(Scenario.id == scenario_id).values(
            updated_at=datetime.now(UTC),
        ))
        return _load(connection, scenario_id)


def _csv_text(value: Any) -> str:
    """Quote formula-leading text even when hidden behind whitespace or a BOM."""
    value = "" if value is None else str(value)
    if value.startswith(("\t", "\r", "\n")) or value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_scenario(engine: Engine, scenario_id: UUID, *, expected_revision: int) -> str:
    with engine.begin() as connection:
        detail = _load(connection, scenario_id, lock=True)
        _expect(detail, expected_revision)
        if detail["approved_revision"] != expected_revision:
            raise ScenarioConflict("Approve the current revision before exporting")
        overrides = {item["row_id"]: item for item in detail["overrides"]}
        inputs = {item["row_id"]: item for item in detail["input"]["rows"]}
        output = io.StringIO(newline="")
        fields = [
            "scenario_id", "scenario_name", "approved_revision", "approved_by", "approved_at",
            "order_basis", "supplier", "sku", "name", "warehouse", "purchase_unit", "basis", "status",
            "recommended_quantity", "approved_quantity", "override_reason", "explanation", "sources",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        rows = sorted(detail["result"]["rows"], key=lambda row: (row["supplier"], row["sku"], row["row_id"]))
        for row in rows:
            override = overrides.get(row["row_id"])
            record = {
                "scenario_id": scenario_id, "scenario_name": detail["name"],
                "approved_revision": expected_revision, "approved_by": detail["approved_by"],
                "approved_at": detail["approved_at"].isoformat(),
                "order_basis": "scenario" if row["status"] == "scenario_only" else "reviewed",
                **{key: row[key] for key in ("supplier", "sku", "name", "purchase_unit", "basis", "status",
                                           "recommended_quantity", "explanation")},
                "warehouse": inputs[row["row_id"]].get("warehouse"),
                "approved_quantity": override["quantity"] if override else row["recommended_quantity"],
                "override_reason": override["reason"] if override else "",
                "sources": json.dumps(row.get("sources", []), ensure_ascii=False),
            }
            writer.writerow({key: _csv_text(value) for key, value in record.items()})
        return output.getvalue()
