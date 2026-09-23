"""Synthetic checks only: no database connection or source writes."""

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from evaluate_application_baseline import controls, scales


def test_controls_and_actual_engine_preserve_as_of_scope():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hackathon-replenishment/backend/src"))
    from replenishment.calculation.contracts import Scenario
    from replenishment.calculation.engine import calculate

    origin, identity = date(2026, 1, 1), UUID(int=1)
    scenario = Scenario(
        supplier_id=identity,
        warehouse_id=identity,
        unit="шт",
        as_of=origin,
        lead_time_days=14,
        review_days=7,
        safety_days=0,
        sales={"sheet_id": identity, "normalizer_version": "v1"},
        confirm_no_incoming=True,
        stock_overrides=[{"sku": "sku", "quantity": 0}],
    )
    history = [Decimal(1)] * 60
    history[-1] = Decimal(100)
    movements = [
        {
            "product_id": identity,
            "warehouse_id": identity,
            "unit": "шт",
            "occurred_at": datetime.combine(origin - timedelta(days=60 - index), datetime.min.time()),
            "quantity": quantity,
            "document_number": str(index),
            "document_text": "Расходная накладная",
            "source_row_id": UUID(int=index + 1),
            "sheet_id": identity,
            "workbook_id": identity,
            "sha256": "synthetic",
            "normalizer_version": "v1",
        }
        for index, quantity in enumerate(history)
    ]
    inputs = {key: [] for key in ("current-stock", "monthly-stock", "shipment-lines", "moq")}
    inputs.update(products=[{"id": identity, "sku": "sku"}], movements=movements, source_manifest={})
    result = calculate(scenario, inputs)["items"][0]["forecast"]
    expected = controls(history, 21, "IEK", "шт")
    assert abs(result - expected["weekly_ewma"]) < Decimal("1e-8")
    assert expected["capped_ewma_fixed"] < result
    for changes in (
        {"occurred_at": datetime(2026, 1, 1)},
        {"warehouse_id": UUID(int=2)},
        {"unit": "м"},
        {"quantity": Decimal(-999)},
        {"document_text": "Приходная"},
    ):
        inputs["movements"] = movements + [movements[-1] | {"quantity": Decimal(999999)} | changes]
        assert calculate(scenario, inputs)["items"][0]["forecast"] == result
    inputs["movements"] = []
    assert calculate(scenario, inputs)["items"][0]["status"] == "needs_review"
    natural = scenario.model_copy(update={"stock_overrides": []})
    assert calculate(natural, inputs)["items"] == []


def test_constant_zero_and_legacy_pack_controls():
    history = [Decimal(2)] * 90
    assert set(controls(history, 28, "IEK", "шт").values()) == {Decimal(56)}
    assert set(controls([Decimal(0)] * 90, 21, "IEK", "шт").values()) == {Decimal(0)}
    history[-1] = Decimal(1000)
    assert controls(history, 7, "IEK", "упак")["legacy_selected"] == sum(history[-59:]) / 59 * 7
    assert scales([Decimal(0)] * 90, 28) == (Decimal(0), Decimal(0))
