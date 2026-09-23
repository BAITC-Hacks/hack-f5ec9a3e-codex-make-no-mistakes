"""Fixed synthetic business acceptance cases through the public planning boundary.

These demonstrate mechanisms, not forecast accuracy or actual customer intent.
Exact arithmetic is asserted where possible; estimated demand permits 1e-9 error.
The bulk tolerance is fixed at 10% above the otherwise identical regular order.
"""

import json
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from replenishment.planning.calculator import calculate
from replenishment.planning.models import PlanningRequest

DAY = date(2026, 9, 23)
TOLERANCE = Decimal("0.000000001")


def scenario(**row_changes: object) -> dict:
    row = {
        "row_id": "synthetic-systeme",
        "supplier": "Systeme Electric",
        "sku": "SYNTHETIC-001",
        "name": "Synthetic acceptance product",
        "warehouse": "Almaty",
        "stock_unit": "piece",
        "purchase_unit": "piece",
        "free_stock": "0",
        "stock_as_of": DAY.isoformat(),
        "stock_scope_confirmed": True,
        "incoming_complete": True,
        "constraints_confirmed": True,
        "stock_per_purchase_unit": "1",
        "minimum_order": "0",
        "order_multiple": "1",
        "daily_demand": "10",
        "basis": "synthetic",
        "notes": ["Invented acceptance data; not a supplier order."],
    }
    row.update(row_changes)
    return {
        "planning_date": DAY.isoformat(),
        "lead_time_days": 0,
        "review_days": 7,
        "rows": [row],
    }


def result(payload: dict):
    return calculate(PlanningRequest.model_validate(payload)).rows[0]


def shipment(quantity: str, *, day: int = 1) -> dict:
    return {
        "id": "synthetic-shipment",
        "quantity": quantity,
        "expected_on": (DAY + timedelta(days=day)).isoformat(),
        "warehouse": "Almaty",
        "stock_unit": "piece",
    }


def history_scenario() -> dict:
    start = DAY - timedelta(days=84)
    return scenario(
        daily_demand=None,
        history_start=start.isoformat(),
        history_end=(DAY - timedelta(days=1)).isoformat(),
        sales=[
            {
                "day": (start + timedelta(days=index)).isoformat(),
                "quantity": "10",
                "document": f"synthetic-sale-{index}",
                "customer_id": "anonymous-regular",
            }
            for index in range(84)
        ],
    )


@pytest.mark.parametrize(("incoming", "expected"), [("70", "100"), ("100", "70"), ("300", "0")])
def test_timely_incoming_changes_regular_order(incoming: str, expected: str) -> None:
    payload = scenario(free_stock="50", daily_demand="20", incoming=[shipment(incoming)])
    payload.update(lead_time_days=3, review_days=7, buffer_days="1")
    row = result(payload)

    assert row.forecast_demand == Decimal("200")
    assert row.buffer == Decimal("20")
    assert row.eligible_incoming == Decimal(incoming)
    assert row.recommended_quantity == Decimal(expected)
    assert row.explanation
    assert row.status == "scenario_only"


def test_seasonal_factors_follow_forecast_dates_and_growth_is_applied_once() -> None:
    payload = scenario()
    payload.update(planning_date="2026-09-29", review_days=4, seasonality={"10": "2"}, growth_pct="20")
    payload["rows"][0]["stock_as_of"] = "2026-09-29"
    row = result(payload)

    # Two September days at 12, followed by two October days at 24.
    assert [day.demand for day in row.daily_balances] == list(map(Decimal, ["12", "12", "24", "24"]))
    assert row.forecast_demand == Decimal("72")
    assert row.recommended_quantity == Decimal("72")


def test_explicit_category_buffer_policy_changes_need_and_row_override_takes_precedence() -> None:
    payload = scenario(category="A")
    payload.update(buffer_days="1", category_buffer_days={"A": "2", "B": "5"})
    category_a = result(payload)
    payload["rows"][0]["category"] = "B"
    category_b = result(payload)

    assert category_a.buffer == Decimal("20")
    assert category_b.buffer == Decimal("50")
    assert category_b.recommended_quantity - category_a.recommended_quantity == Decimal("30")
    payload["rows"][0]["buffer_days"] = "3"
    overridden_b = result(payload)
    payload["rows"][0]["category"] = "A"
    overridden_a = result(payload)
    assert overridden_b.buffer == overridden_a.buffer == Decimal("30")
    assert overridden_b.recommended_quantity == overridden_a.recommended_quantity


def test_sustained_increase_is_preserved_when_bulk_exclusion_is_enabled() -> None:
    baseline = history_scenario()
    elevated = deepcopy(baseline)
    for sale in elevated["rows"][0]["sales"][-21:]:
        sale["quantity"] = "60"
    baseline["exclude_bulk"] = elevated["exclude_bulk"] = True
    ordinary, growing = result(baseline), result(elevated)

    assert growing.excluded_bulk_quantity == 0
    assert growing.forecast_demand >= ordinary.forecast_demand * 2
    assert growing.recommended_quantity >= ordinary.recommended_quantity * 2


@pytest.mark.parametrize("split_customer_documents", [False, True])
def test_one_off_bulk_does_not_inflate_regular_order(split_customer_documents: bool) -> None:
    baseline = history_scenario()
    contaminated = deepcopy(baseline)
    sales = contaminated["rows"][0]["sales"]
    original = sales.pop(70)
    if split_customer_documents:
        # Each 30-unit document is below the 40-unit document threshold. The
        # same-day anonymized customer total is the evidence for this candidate.
        sales.extend(
            dict(original, document=f"synthetic-burst-{index}", quantity="30", customer_id="anonymous-bulk")
            for index in range(5)
        )
    else:
        sales.append(dict(original, quantity="1010", customer_id="anonymous-bulk"))
    baseline["exclude_bulk"] = contaminated["exclude_bulk"] = True
    ordinary, cleaned = result(baseline), result(contaminated)

    assert cleaned.raw_daily_demand > ordinary.raw_daily_demand
    assert cleaned.excluded_bulk_quantity > 0
    assert cleaned.recommended_quantity <= ordinary.recommended_quantity * Decimal("1.1")
    assert cleaned.recommended_quantity >= ordinary.recommended_quantity * Decimal("0.9")
    assert cleaned.demand_adjustments


def test_known_stockout_compensation_restores_unobserved_regular_demand() -> None:
    payload = history_scenario()
    row = payload["rows"][0]
    unavailable = {sale["day"] for sale in row["sales"][::6]}
    row["sales"] = [sale for sale in row["sales"] if sale["day"] not in unavailable]
    row["stockout_days"] = sorted(unavailable)
    raw = result(payload)
    payload["compensate_stockouts"] = True
    compensated = result(payload)

    assert abs(compensated.daily_demand - Decimal("10")) <= TOLERANCE
    assert abs(compensated.lost_demand_quantity - Decimal("140")) <= TOLERANCE
    assert compensated.recommended_quantity > raw.recommended_quantity
    assert compensated.demand_adjustments


@pytest.mark.parametrize("field", ["warehouse", "free_stock", "stock_per_purchase_unit"])
def test_unknown_critical_input_never_becomes_zero_order(field: str) -> None:
    payload = scenario(**{field: None})
    blocked = result(payload)

    assert blocked.status == "needs_input"
    assert blocked.recommended_quantity is None
    assert blocked.missing_inputs


def test_unknown_incoming_completeness_blocks_recommendation() -> None:
    row = result(scenario(incoming_complete=False))
    assert row.status == "needs_input"
    assert row.recommended_quantity is None


def test_stock_units_are_converted_before_purchase_rounding() -> None:
    payload = scenario(
        stock_unit="metre", purchase_unit="coil", stock_per_purchase_unit="100", daily_demand="130"
    )
    payload["review_days"] = 1
    row = result(payload)

    assert row.raw_need == Decimal("130")
    assert row.recommended_quantity == Decimal("2")
    assert row.stock_equivalent == Decimal("200")
    assert row.rounding_surplus == Decimal("70")


def test_repeating_daily_average_does_not_add_a_spurious_purchase_unit() -> None:
    payload = history_scenario()
    payload["review_days"] = 18
    payload["rows"][0]["history_start"] = (DAY - timedelta(days=18)).isoformat()
    payload["rows"][0]["sales"] = [dict(payload["rows"][0]["sales"][-1], quantity="1")]
    row = result(payload)

    # One unit observed over 18 days implies exactly one over another 18 days.
    assert row.forecast_demand == Decimal("1")
    assert row.recommended_quantity == Decimal("1")


def test_zero_aggregate_order_still_reports_prearrival_shortage() -> None:
    payload = scenario(free_stock="20", incoming=[shipment("80", day=5)])
    payload.update(lead_time_days=7, review_days=3)
    row = result(payload)

    assert row.recommended_quantity == 0
    assert row.first_shortage_date == DAY + timedelta(days=2)
    assert row.maximum_prearrival_shortfall == Decimal("30")
    assert row.warnings


def test_arrival_at_exclusive_coverage_end_is_not_credited() -> None:
    payload = scenario(free_stock="20", incoming=[shipment("80", day=10)])
    payload.update(lead_time_days=7, review_days=3)
    row = result(payload)

    assert row.eligible_incoming == 0
    assert row.recommended_quantity == Decimal("80")
    assert row.first_shortage_date == DAY + timedelta(days=2)
    assert not row.incoming_decisions[0].credited
    assert row.incoming_decisions[0].reason


def test_planning_date_sales_are_rejected_instead_of_training_on_future_data() -> None:
    payload = history_scenario()
    payload["rows"][0]["sales"].append({"day": DAY.isoformat(), "quantity": "100", "document": "future"})
    with pytest.raises(ValidationError):
        PlanningRequest.model_validate(payload)


def test_both_suppliers_keep_explanations_and_unknown_rows_visible() -> None:
    payload = scenario()
    payload["rows"].append(
        dict(payload["rows"][0], row_id="synthetic-iek", supplier="IEK", sku="SYNTHETIC-002", free_stock=None)
    )
    rows = calculate(PlanningRequest.model_validate(payload)).rows

    assert [row.supplier for row in rows] == ["Systeme Electric", "IEK"]
    assert all(row.explanation for row in rows)
    assert rows[1].status == "needs_input"


def test_cli_json_contains_production_calculator_results(capsys: pytest.CaptureFixture) -> None:
    from replenishment.cli.planning_demo import main

    main(["--json"])
    reports = json.loads(capsys.readouterr().out)
    assert reports
    for report in reports:
        assert report["synthetic"] is True
        expected = calculate(PlanningRequest.model_validate(report["input"]))
        assert report["result"] == expected.model_dump(mode="json")
    main(["--case", reports[0]["id"], "--json"])
    assert len(json.loads(capsys.readouterr().out)) == 1
    with pytest.raises(SystemExit) as exit_info:
        main(["--case", "nonexistent-case"])
    assert exit_info.value.code == 2


def test_cli_human_output_labels_synthetic_supplier_groups(capsys: pytest.CaptureFixture) -> None:
    from replenishment.cli.planning_demo import main

    main([])
    output = capsys.readouterr().out
    assert "SYNTHETIC DEMO" in output
    assert "Supplier / Поставщик:" in output
    assert "NEEDS INPUT / НУЖНЫ ДАННЫЕ" in output
