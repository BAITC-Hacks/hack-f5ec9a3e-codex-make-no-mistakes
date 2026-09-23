"""Run focused V2 forecast/evaluation contract checks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "backend/tests"))

from evaluation.leftovers import leftovers_comparison  # noqa: E402
from replenishment.calculation import calculate  # noqa: E402
from replenishment.calculation.contracts import validate_batch, validate_results  # noqa: E402
from replenishment.calculation.evaluation import evaluate_origins  # noqa: E402


def _batch():
    return {
        "contract_version": "2",
        "planning_date": "2025-06-01",
        "series": [
            {
                "series_id": "s1",
                "supplier": "supplier",
                "sku": "sku",
                "scope": "warehouse:unknown",
                "unit": None,
                "history": [
                    {"month": f"2025-{month:02}-01", "quantity": str(month), "evidence": []}
                    for month in range(1, 6)
                ],
                "category": None,
                "inventory": None,
                "shipments": [],
                "quantity_rules": [],
                "assumptions": [],
            }
        ],
        "parameters": {"missing_months_preserved": True},
        "source_selection": [],
    }


def check() -> None:
    batch = _batch()
    coverage = leftovers_comparison(batch)
    assert coverage["message"] == "Leftover reduction: not measured."
    assert coverage["eligible_count"] == 0
    assert all(c["leftover_reduction_percent"] is None for c in coverage["excluded_cases"])
    validate_batch(batch)
    result = calculate(batch)
    validate_results(batch, result)
    assert len(result["forecasts"]) == 3
    assert len(result["drafts"]) == 1 and result["drafts"][0]["state"] == "blocked"
    series = batch["series"]
    earlier = evaluate_origins(series, ["2025-02-01"])
    poisoned = {
        **series[0],
        "history": [
            *series[0]["history"],
            {"month": "2025-12-01", "quantity": "999999", "evidence": []},
        ],
    }
    assert earlier["rows"] == evaluate_origins([poisoned], ["2025-02-01"])["rows"]


if __name__ == "__main__":
    check()
    print("V2 forecast/evaluation contracts: OK")
