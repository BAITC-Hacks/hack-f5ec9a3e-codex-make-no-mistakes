"""Insert clearly synthetic fixtures after migrations; replay never updates existing rows."""

import json
import os
from datetime import UTC, date, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert

from replenishment.schema import metadata


def fixture_id(name):
    return uuid5(NAMESPACE_URL, f"replenishment:synthetic-order-demo:v1:{name}")


RUN_ID = fixture_id("run")
EMPLOYEE_IDS = (fixture_id("employee:alex"), fixture_id("employee:sam"))


def seed_demo(engine):
    with engine.begin() as connection:

        def add(table_name, **values):
            table = metadata.tables[table_name]
            connection.execute(insert(table).values(**values).on_conflict_do_nothing(index_elements=["id"]))

        for employee_id, name in zip(
            EMPLOYEE_IDS, ("Alex — synthetic demo", "Sam — synthetic demo"), strict=True
        ):
            add("ordering_employees", id=employee_id, display_name=name)
        add(
            "calculation_runs",
            id=RUN_ID,
            fingerprint="d" * 64,
            contract_version="v2",
            planning_date=date(2026, 9, 23),
            status="completed",
            completed_at=datetime(2026, 9, 23, tzinfo=UTC),
            source_selection=[],
            parameters={"synthetic": True, "purpose": "Employee approval demo"},
            versions={"fixture": "synthetic-order-demo-v1"},
            quality={"synthetic": True},
            llm_accounting={},
        )
        for index, (supplier, state, amount, unit) in enumerate(
            [
                ("SYNTHETIC-A", "ready", "12", "piece"),
                ("SYNTHETIC-A", "estimated", "8", "piece"),
                ("SYNTHETIC-B", "blocked", None, None),
            ],
            start=1,
        ):
            series_id = f"synthetic-{index}"
            evidence = [{"kind": "synthetic", "fixture": "synthetic-order-demo-v1"}]
            snapshot = dict(
                series_id=series_id,
                supplier=supplier,
                sku=f"DEMO-{index}",
                scope="synthetic-warehouse",
                unit=unit,
                purchase_unit=unit,
                history=[{"month": "2026-08", "quantity": "4", "evidence": evidence}],
                inventory={
                    "free": "0",
                    "scope": "synthetic-warehouse",
                    "unit": unit,
                    "as_of": "2026-09-23",
                    "date_basis": "synthetic",
                },
                shipments=[],
                quantity_rules=[
                    {
                        "kind": "minimum_shipment",
                        "value": "6",
                        "unit": "piece",
                        "interpretation_confirmed": True,
                        "evidence": evidence,
                    },
                    {
                        "kind": "order_multiple",
                        "value": "2",
                        "unit": "piece",
                        "interpretation_confirmed": True,
                        "evidence": evidence,
                    },
                ]
                if index == 1
                else [],
                assumptions=["Synthetic demonstration only"],
            )
            add(
                "calculation_inputs",
                id=fixture_id(f"input:{index}"),
                run_id=RUN_ID,
                series_id=series_id,
                supplier=supplier,
                sku=f"DEMO-{index}",
                scope="synthetic-warehouse",
                unit=unit,
                snapshot=snapshot,
            )
            for month in (10, 11, 12):
                add(
                    "calculation_forecasts",
                    id=fixture_id(f"forecast:{index}:{month}"),
                    run_id=RUN_ID,
                    series_id=series_id,
                    target_month=date(2026, month, 1),
                    quantity="4",
                    model="synthetic",
                    status="ok",
                    explanation={"synthetic": True, "evidence": evidence},
                )
            add(
                "calculation_drafts",
                id=fixture_id(f"draft:{index}"),
                run_id=RUN_ID,
                series_id=series_id,
                quantity=amount,
                purchase_unit=unit,
                coverage_start=date(2026, 9, 23),
                coverage_end=date(2027, 1, 1),
                urgency="normal",
                state=state,
                blocking_reason="missing_purchase_unit_conversion" if state == "blocked" else None,
                components={
                    "synthetic": True,
                    "blockers": ["missing_purchase_unit_conversion"] if state == "blocked" else [],
                },
                evidence=evidence,
                assumptions=["Synthetic demonstration only"],
            )
    return {"run_id": str(RUN_ID), "employee_ids": [str(value) for value in EMPLOYEE_IDS]}


def main():
    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 5})
    try:
        print(json.dumps(seed_demo(engine), indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
