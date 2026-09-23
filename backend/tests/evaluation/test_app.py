"""V2 calculation boundary acceptance checks."""

from copy import deepcopy

import pytest

from replenishment.calculation import calculate
from replenishment.calculation.contracts import validate_batch, validate_results
from replenishment.calculation.evaluation import evaluate_origins


def batch():
    return {
        "contract_version": "2",
        "planning_date": "2025-06-22",
        "series": [
            {
                "series_id": "supplier:sku:scope:none",
                "supplier": "supplier",
                "sku": "sku",
                "scope": "warehouse:unknown",
                "unit": None,
                "history": [
                    {"month": f"2025-{month:02}-01", "quantity": str(10 + month), "evidence": []}
                    for month in range(1, 6)
                ],
                "category": None,
                "inventory": None,
                "shipments": [],
                "quantity_rules": [],
                "assumptions": [],
            }
        ],
        "parameters": {},
        "source_selection": [],
    }


def test_v2_result_has_three_targets_and_supplier_draft():
    payload = batch()
    result = calculate(payload)
    validate_results(payload, result)
    assert result["target_months"] == ["2025-07-01", "2025-08-01", "2025-09-01"]
    assert len(result["forecasts"]) == 3
    assert result["drafts"][0]["state"] == "blocked"
    assert result["drafts"][0]["blocking_reason"]


def test_future_rows_do_not_change_earlier_calculation():
    original = batch()
    baseline = evaluate_origins(original["series"], ["2025-02-01"])
    changed = deepcopy(original)
    changed["series"][0]["history"].append({"month": "2025-12-01", "quantity": "999999", "evidence": []})
    changed_result = evaluate_origins(changed["series"], ["2025-02-01"])
    assert changed_result["rows"] == baseline["rows"]
    assert changed_result["metrics"] == baseline["metrics"]


def test_invalid_draft_identity_or_state_is_rejected():
    payload = batch()
    result = calculate(payload)
    result["drafts"][0]["supplier"] = "other"
    with pytest.raises(ValueError):
        validate_results(payload, result)

    result = calculate(payload)
    result["drafts"][0]["state"] = "ready"
    with pytest.raises(ValueError):
        validate_results(payload, result)


def test_batch_rejects_duplicate_natural_identity():
    payload = batch()
    duplicate = deepcopy(payload["series"][0])
    duplicate["series_id"] = "different"
    payload["series"].append(duplicate)
    with pytest.raises(ValueError):
        validate_batch(payload)
