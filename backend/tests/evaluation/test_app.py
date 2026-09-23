"""Future boundary acceptance; synthetic mechanics, never report business impact."""

from copy import deepcopy
from decimal import Decimal

from evaluation.checks import example, ordering_case
from evaluation.contracts import validate_requests, validate_results
from evaluation.metrics import order_oracle


def calculate(app, batch):
    validate_requests(batch)
    pristine = deepcopy(batch)
    result = app(batch)
    assert batch == pristine
    return validate_results(batch, result)


def test_response_and_one_result_per_input(app):
    first = example()
    second = {**deepcopy(first), "case_id": "second", "sku": "0002_"}
    results = calculate(app, [first, second])
    assert {r["case_id"] for r in results} == {first["case_id"], second["case_id"]}


def test_missing_stock_allows_forecast_prevents_order(app):
    result = calculate(app, [example()])[0]
    assert result["status"] == "ok"
    assert result.get("recommended_quantity") is None
    assert result["reason"]


def test_no_future_batch_leakage_including_fitting(app):
    earlier = example()
    later = deepcopy(earlier)
    later.update(case_id="later", origin="2024-02", target_month="2024-03")
    later["history"].append({**deepcopy(later["history"][0]), "month": "2024-02", "quantity": "999999"})
    alone = calculate(app, [earlier])[0]
    mixed = {r["case_id"]: r for r in calculate(app, [later, earlier])}
    assert mixed[earlier["case_id"]] == alone
    later["history"][-1]["quantity"] = "0"
    poisoned = {r["case_id"]: r for r in calculate(app, [earlier, later])}
    assert poisoned[earlier["case_id"]] == alone


def test_constraints_and_explanations_reconcile(app):
    request = ordering_case()
    result = calculate(app, [request])[0]
    assert result["status"] == "ok"
    order = Decimal(result["recommended_quantity"])
    components = result["components"]
    assert Decimal(components["free_stock"]) == Decimal(request["stock"]["free"])
    assert Decimal(components["eligible_transit"]) == 120
    for key in ("minimum", "multiple"):
        assert Decimal(components[key]) == Decimal(request["constraints"][key])
    assert Decimal(components["coverage_demand"]) == Decimal(result["forecast"])
    assert order % 6 == 0 and (order == 0 or order >= 12)
    assert order == order_oracle(
        components["coverage_demand"],
        components["free_stock"],
        components["eligible_transit"],
        components["multiple"],
        components["minimum"],
    )


def test_more_eligible_stock_or_transit_cannot_increase_order(app):
    request = ordering_case()
    base = calculate(app, [request])[0]
    for field in ("stock", "receipts"):
        changed = deepcopy(request)
        if field == "stock":
            changed["stock"]["free"] = "100"
        else:
            changed["receipts"][0]["quantity"] = "200"
        result = calculate(app, [changed])[0]
        assert Decimal(result["forecast"]) == Decimal(base["forecast"])
        assert Decimal(result["recommended_quantity"]) <= Decimal(base["recommended_quantity"])
