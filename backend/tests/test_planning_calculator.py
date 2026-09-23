from copy import deepcopy
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal, Inexact, localcontext

import pytest
from pydantic import ValidationError

from replenishment.planning.calculator import calculate
from replenishment.planning.demo import demo_cases
from replenishment.planning.models import PlanningRequest

DAY = date(2026, 9, 23)


def request(**changes):
    payload = demo_cases()[0]["input"]
    row_changes = changes.pop("row", {})
    payload.update(changes)
    payload["rows"][0].update(row_changes)
    return PlanningRequest.model_validate(payload)


def result(**changes):
    return calculate(request(**changes)).rows[0]


def shipment(quantity="70", offset=0, **changes):
    return {
        "id": "shipment",
        "quantity": quantity,
        "expected_on": DAY + timedelta(days=offset),
        "warehouse": "Алматы",
        "stock_unit": "шт",
        **changes,
    }


@pytest.mark.parametrize(("incoming", "expected"), [("70", "100"), ("100", "70"), ("300", "0")])
def test_q1_q2_q3_transit_reduces_need_and_zero_is_known(incoming, expected):
    row = result(row={"incoming": [shipment(incoming)]})
    assert row.raw_need == row.recommended_quantity == Decimal(expected)
    assert row.eligible_incoming == Decimal(incoming)
    assert incoming in row.explanation
    assert row.status == "scenario_only"


def test_q4_free_stock_already_accounts_for_reservations():
    row = result(
        review_days=3, buffer_days="0", row={"daily_demand": "10", "free_stock": "23", "incoming": []}
    )
    assert row.raw_need == row.recommended_quantity == 77


@pytest.mark.parametrize(("demand", "expected", "surplus"), [("13", "24", "11"), ("0", "0", "0")])
def test_q5_minimum_multiple_and_zero_need(demand, expected, surplus):
    row = result(
        lead_time_days=0,
        review_days=1,
        buffer_days="0",
        row={
            "daily_demand": demand,
            "free_stock": "0",
            "incoming": [],
            "minimum_order": "20",
            "order_multiple": "6",
        },
    )
    assert row.recommended_quantity == Decimal(expected)
    assert row.rounding_surplus == Decimal(surplus)


def test_q6_stock_to_purchase_conversion_precedes_rounding():
    changes = {
        "daily_demand": "130",
        "free_stock": "0",
        "incoming": [],
        "stock_unit": "м",
        "purchase_unit": "бухта",
        "stock_per_purchase_unit": "100",
    }
    row = result(lead_time_days=0, review_days=1, buffer_days="0", row=changes)
    assert (row.recommended_quantity, row.stock_equivalent, row.rounding_surplus) == (2, 200, 70)
    blocked = result(row={**changes, "stock_per_purchase_unit": None})
    assert blocked.status == "needs_input" and blocked.recommended_quantity is None


@pytest.mark.parametrize("field", ["free_stock", "warehouse", "stock_as_of", "purchase_unit"])
def test_q7_missing_is_not_zero_and_override_is_scenario(field):
    blocked = result(row={field: None})
    assert blocked.status == "needs_input" and blocked.recommended_quantity is None
    assert any(field in item for item in blocked.missing_inputs)
    assert blocked.daily_balances == []
    assert result().status == "scenario_only"


@pytest.mark.parametrize(("arrival_offset", "need", "prearrival"), [(5, 0, 30), (10, 80, 50)])
def test_q8_q9_aggregate_need_does_not_hide_prearrival_shortage(arrival_offset, need, prearrival):
    row = result(
        review_days=3,
        buffer_days="0",
        row={"daily_demand": "10", "free_stock": "20", "incoming": [shipment("80", arrival_offset)]},
    )
    assert row.raw_need == need
    assert row.first_shortage_date == DAY + timedelta(days=2)
    assert row.maximum_prearrival_shortfall == prearrival
    assert row.coverage_end == DAY + timedelta(days=10)
    assert len(row.daily_balances) == 10
    assert row.daily_balances[4].balance == -30
    assert any("ускорения" in warning for warning in row.warnings)


def test_q10_duplicate_incoming_is_rejected():
    with pytest.raises(ValidationError, match="Duplicate incoming"):
        request(row={"incoming": [shipment(), shipment()]})


@pytest.mark.parametrize(
    "changes",
    [
        {"free_stock": "-1"},
        {"order_multiple": "0"},
        {"daily_demand": "NaN"},
        {"stock_per_purchase_unit": "Infinity"},
    ],
)
def test_q11_invalid_quantities_are_rejected(changes):
    with pytest.raises(ValidationError):
        request(row=changes)


def test_q11_unknown_incoming_coverage_blocks():
    row = result(row={"incoming_complete": False})
    assert row.status == "needs_input" and row.recommended_quantity is None
    assert "incoming_complete" in row.missing_inputs


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_on": None},
        {"expected_on": DAY - timedelta(days=1)},
        {"quantity": None},
        {"warehouse": "Other"},
        {"stock_unit": "м"},
    ],
)
def test_uncertain_incoming_is_not_silently_ignored(changes):
    row = result(row={"incoming": [shipment(**changes)]})
    assert row.status == "needs_input" and row.recommended_quantity is None
    assert not row.incoming_decisions[0].credited


def test_today_arrivals_precede_demand_and_end_boundary_is_exclusive():
    row = result(
        lead_time_days=0,
        review_days=1,
        buffer_days="0",
        row={"free_stock": "0", "daily_demand": "10", "incoming": [shipment("10")]},
    )
    assert row.first_shortage_date is None and row.daily_balances[0].balance == 0
    outside = result(
        lead_time_days=0,
        review_days=1,
        buffer_days="0",
        row={"free_stock": "0", "daily_demand": "10", "incoming": [shipment("10", 1)]},
    )
    assert outside.raw_need == 10 and "outside_coverage" in outside.incoming_decisions[0].reason


def test_decimal_purchase_rounding_and_deterministic_context():
    payload = request(
        lead_time_days=0,
        review_days=1,
        buffer_days="0",
        row={
            "free_stock": "0",
            "daily_demand": "1.31",
            "incoming": [],
            "stock_per_purchase_unit": "0.1",
            "order_multiple": "0.5",
        },
    )
    snapshot = payload.model_dump_json()
    with localcontext() as context:
        context.prec = 5
        computed = calculate(payload)
    assert computed.rows[0].recommended_quantity == Decimal("13.5")
    assert computed.model_dump(mode="json")["rows"][0]["recommended_quantity"] == "13.5"
    assert payload.model_dump_json() == snapshot


@pytest.mark.parametrize("days", [7, 18, 24, 26, 29, 35, 365])
@pytest.mark.parametrize("rounding", [ROUND_UP, ROUND_DOWN])
def test_recurring_average_cannot_create_extra_purchase_unit(days, rounding):
    payload = history_payload([0] * (days - 1) + [1])
    payload["review_days"] = days
    with localcontext() as context:
        context.prec = 6
        context.rounding = rounding
        context.traps[Inexact] = True
        row = computed(payload)
    assert row.forecast_demand == row.raw_need == row.recommended_quantity == 1
    assert row.daily_balances[-1].balance == -1


@pytest.mark.parametrize("quantity", ["1e999999", "1e-999999", "9999999999999999999"])
def test_extreme_decimal_magnitudes_rejected_at_boundary(quantity):
    with pytest.raises(ValidationError):
        request(row={"daily_demand": quantity})


def history_payload(values):
    payload = demo_cases()[0]["input"]
    payload.update(buffer_days="0", lead_time_days=0, review_days=7)
    row = payload["rows"][0]
    row.update(
        free_stock="0",
        incoming=[],
        daily_demand=None,
        history_start=DAY - timedelta(days=len(values)),
        history_end=DAY - timedelta(days=1),
    )
    row["sales"] = [
        {
            "day": DAY - timedelta(days=len(values) - index),
            "quantity": str(quantity),
            "document": f"doc-{index}",
        }
        for index, quantity in enumerate(values)
    ]
    return payload


def computed(payload):
    return calculate(PlanningRequest.model_validate(payload)).rows[0]


def test_bulk_policy_is_explicit_and_does_not_erase_sustained_growth():
    payload = history_payload([10] * 76 + [1010] + [10] * 7)
    untouched = computed(payload)
    payload["exclude_bulk"] = True
    cleaned = computed(payload)
    assert cleaned.excluded_bulk_quantity == 1000
    assert cleaned.daily_demand == 10 and untouched.daily_demand > 20
    growth = history_payload([10] * 63 + [60] * 21)
    growth["exclude_bulk"] = True
    sustained = computed(growth)
    assert sustained.excluded_bulk_quantity == 0
    assert sustained.daily_demand == Decimal("22.5")
    assert any("Повторяющееся" in item for item in sustained.demand_adjustments)


def test_customer_concentration_uses_only_supplied_customer_ids():
    payload = history_payload([10] * 84)
    payload["exclude_bulk"] = True
    row = payload["rows"][0]
    row["sales"] = row["sales"][:-1] + [
        {
            "day": DAY - timedelta(days=1),
            "quantity": "30",
            "document": f"bulk-{index}",
            "customer_id": "anonymous-1",
        }
        for index in range(5)
    ]
    concentration = computed(payload)
    assert concentration.excluded_bulk_quantity == 140 and concentration.daily_demand == 10
    for sale in row["sales"]:
        sale.pop("customer_id", None)
    unlinked = computed(payload)
    assert unlinked.excluded_bulk_quantity == 0
    assert any("Нет ID" in warning for warning in unlinked.warnings)


def test_known_stockout_restores_equivalent_daily_history_only():
    payload = history_payload([10] * 84)
    row = payload["rows"][0]
    row["stockout_days"] = [sale["day"] for sale in row["sales"][-7:]]
    row["sales"] = row["sales"][:-7]
    assert computed(payload).daily_demand < 10
    payload["compensate_stockouts"] = True
    restored = computed(payload)
    assert restored.daily_demand == 10 and restored.lost_demand_quantity == 70
    insufficient = history_payload([10] * 7)
    insufficient["compensate_stockouts"] = True
    insufficient["rows"][0]["stockout_days"] = [insufficient["rows"][0]["sales"].pop()["day"]]
    assert computed(insufficient).status == "needs_input"


def test_seasonality_and_growth_are_applied_once_and_category_is_not_multiplier():
    row = result(
        review_days=7,
        growth_pct="20",
        seasonality={"9": "1.5", "10": "2"},
        row={"daily_demand": "10", "category": "9.9", "incoming": []},
    )
    assert row.forecast_demand == 288
    assert row.daily_balances[0].demand == 18
    assert row.daily_balances[-1].demand == 24
    assert any("Категория" in warning for warning in row.warnings)


def test_row_overrides_replace_global_policy_and_explicit_demand_is_not_cleaned_twice():
    row = result(
        growth_pct="100",
        seasonality={"9": "8"},
        buffer_days="5",
        row={
            "daily_demand": "10",
            "growth_pct": "0",
            "buffer_days": "0",
            "seasonality": {},
            "sales": [{"day": DAY - timedelta(days=1), "quantity": "500", "document": "ignored"}],
        },
    )
    assert row.forecast_demand == 90 and row.buffer == 0
    assert any("повторно" in warning for warning in row.warnings)


def test_category_buffer_is_explicit_and_row_override_takes_precedence():
    policies = {"A": "2", "B": "5"}
    first = result(category_buffer_days=policies, row={"category": "A"})
    second = result(category_buffer_days=policies, row={"category": "B"})
    assert second.raw_need - first.raw_need == 3 * first.daily_demand
    overridden = result(category_buffer_days=policies, row={"category": "B", "buffer_days": "1"})
    assert overridden.buffer == overridden.daily_demand
    assert not any("числовая политика" in warning for warning in second.warnings)


@pytest.mark.parametrize("field", ["sales", "history_end", "stockout_days"])
def test_future_evidence_is_rejected(field):
    payload = history_payload([10] * 84)
    if field == "sales":
        payload["rows"][0][field].append({"day": DAY, "quantity": "10", "document": "future"})
    elif field == "history_end":
        payload["rows"][0][field] = DAY
    else:
        payload["rows"][0][field] = [DAY]
    with pytest.raises(ValidationError):
        PlanningRequest.model_validate(payload)


def test_demo_cases_are_labelled_independent_and_calculable_except_missing_input_case():
    cases = demo_cases()
    for case in cases:
        output = calculate(PlanningRequest.model_validate(case["input"]))
        assert all(row.basis == "synthetic" for row in output.rows)
        assert "Синтетика" in case["name"]
        assert all(row.status == "scenario_only" for row in output.rows if case["id"] != "missing-inputs")
    missing = computed(cases[-1]["input"])
    assert missing.status == "scenario_only"
    cases[0]["input"]["rows"][0]["free_stock"] = "9999"
    assert demo_cases()[0]["input"]["rows"][0]["free_stock"] == "50"


def test_unknown_lead_time_and_stale_stock_block_without_changing_observed_provenance():
    payload = request(lead_time_days=None, row={"stock_as_of": DAY - timedelta(days=1), "basis": "observed"})
    row = calculate(payload).rows[0]
    assert row.status == "needs_input" and row.basis == "observed"
    assert "lead_time_days" in row.missing_inputs
    assert any("stock_as_of" in item for item in row.missing_inputs)


def test_invalid_identities_history_and_horizon_rejected():
    payload = history_payload([10] * 7)
    for mutation in (
        {"rows": [payload["rows"][0], deepcopy(payload["rows"][0])]},
        {"review_days": 0},
        {"lead_time_days": 366},
        {"seasonality": {"13": "1"}},
        {"growth_pct": "-100"},
    ):
        with pytest.raises(ValidationError):
            PlanningRequest.model_validate({**payload, **mutation})
