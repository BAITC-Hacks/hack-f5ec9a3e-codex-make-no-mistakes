"""Small direct checks, shared by the standalone command and pytest."""

import json
from copy import deepcopy
from decimal import Decimal

from evaluation.contracts import IDENTITY, VERSION, validate_requests, validate_results
from evaluation.metrics import forecast_metrics, order_oracle, replay


def example():
    source = {"path": "mechanics-only", "sha256": "0" * 64, "sheet": "example", "cell": "A1"}
    return {
        "contract_version": VERSION,
        "case_id": "mechanics-only",
        "supplier": "example",
        "sku": "0001_",
        "unit": "шт",
        "origin": "2024-01",
        "target_month": "2024-02",
        "history": [{"month": "2024-01", "quantity": "10", "sources": [source]}],
        "stock": None,
        "receipts": None,
        "constraints": None,
    }


def response(request, forecast="8"):
    return {
        **{key: request[key] for key in IDENTITY},
        "status": "ok",
        "forecast": forecast,
        "reason": "ordering_evidence_missing",
    }


def ordering_case():
    request = example()
    refs = request["history"][0]["sources"]
    request["history"][0]["quantity"] = "200"
    request["stock"] = {"free": "23", "as_of": "2024-01", "scope": "example", "sources": refs}
    request["receipts"] = [
        {
            "id": "r1",
            "quantity": "120",
            "due": "2024-02",
            "known_at": "2024-01",
            "scope": "example",
            "sources": refs,
        }
    ]
    request["constraints"] = {
        "minimum": "12",
        "multiple": "6",
        "coverage_months": "1",
        "confirmed_at": "2024-01",
        "sources": refs,
    }
    return request


def rejected(fn, *args):
    try:
        fn(*args)
    except (ValueError, TypeError):
        return
    raise AssertionError("Invalid payload accepted")


def check():
    request = example()
    assert validate_requests(json.loads(json.dumps([request]))) == [request]
    result = response(request)
    assert validate_results([request], json.loads(json.dumps([result]))) == [result]
    ordered = ordering_case()
    ordered_result = {
        **response(ordered, "200"),
        "recommended_quantity": "60",
        "reason": None,
        "components": {
            "coverage_demand": "200",
            "free_stock": "23",
            "eligible_transit": "120",
            "minimum": "12",
            "multiple": "6",
        },
        "evidence": ordered["history"][0]["sources"],
    }
    assert validate_results([ordered], json.loads(json.dumps([ordered_result]))) == [ordered_result]
    for field, key, value in (
        ("stock", "as_of", "2024-02"),
        ("constraints", "multiple", "0"),
        ("constraints", "confirmed_at", "2026-01"),
    ):
        bad = deepcopy(ordered)
        bad[field][key] = value
        rejected(validate_requests, [bad])
    bad = deepcopy(ordered)
    bad["receipts"][0]["scope"] = "different warehouse"
    rejected(validate_requests, [bad])
    for key in request:
        bad = deepcopy(request)
        del bad[key]
        rejected(validate_requests, [bad])
    for key, value in (("target_month", "2024-13"), ("actual", "10"), ("sku", 1)):
        bad = {**request, key: value}
        rejected(validate_requests, [bad])
    for value in ("NaN", "Infinity", "-1", 10, "", None):
        rejected(validate_results, [request], [{**result, "forecast": value}])
    for bad_results in ([], [result, result], [{**result, "unit": "м"}], [{**result, "extra": 0}]):
        rejected(validate_results, [request], bad_results)
    leaked = deepcopy(request)
    leaked["history"][0]["month"] = "2024-02"
    rejected(validate_requests, [leaked])
    metrics = forecast_metrics([("10", "8"), ("20", "24")])
    assert Decimal(metrics["wape_pct"]) == 20
    assert abs(Decimal(metrics["bias_pct"]) - Decimal(20) / 3) < Decimal("1e-24")
    assert Decimal(metrics["mae"]) == 3 and Decimal(metrics["underforecast"]) == 2
    assert forecast_metrics([("0", "4")])["wape_pct"] is None
    assert forecast_metrics([("0", "0")])["bias_pct"] is None
    assert order_oracle("200", "23", "120", "6") == 60
    assert order_oracle("200", "23", "0", "6") == 180
    rejected(order_oracle, "200", None, "120", "6")
    periods = [{"month": "2024-02", "demand": "10"}, {"month": "2024-03", "demand": "8"}]
    receipts = [{"id": "r1", "month": "2024-02", "quantity": "12"}]
    replayed = replay("5", periods, receipts)
    assert replayed["final_stock"] == "0" and replayed["unmet_recorded_demand"] == "1"
    assert replayed["mean_month_end_stock"] == "3.5" and replayed["pending_receipts"] == []
    rejected(replay, None, periods, receipts)
    rejected(replay, "5", periods, receipts * 2)
    assert replay("5", [periods[0], {"month": "2024-04", "demand": "8"}], receipts)["evaluated"] == 1
