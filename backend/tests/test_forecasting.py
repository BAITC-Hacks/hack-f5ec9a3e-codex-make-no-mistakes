from decimal import Decimal

from replenishment.calculation.evaluation import evaluate_origins, promotion_gate
from replenishment.calculation.forecasting import candidate_forecasts, group_seasonal_factors


def series(series_id="s1", supplier="s", category=None, values=None, unit=None):
    values = values or {
        "2024-01-01": "10",
        "2024-02-01": "12",
        "2024-03-01": "14",
        "2024-04-01": "16",
    }
    return {
        "series_id": series_id,
        "supplier": supplier,
        "sku": series_id,
        "scope": "warehouse:1",
        "unit": unit,
        "history": [
            {"month": stamp, "quantity": quantity, "evidence": []} for stamp, quantity in values.items()
        ],
        "category": category,
        "inventory": None,
        "shipments": [],
        "quantity_rules": [],
        "assumptions": [],
    }


def test_group_seasonality_is_scale_independent():
    small = series("small", values={"2024-01-01": "1", "2024-02-01": "2", "2024-03-01": "1"})
    large = series("large", values={"2024-01-01": "100", "2024-02-01": "200", "2024-03-01": "100"})
    factors = group_seasonal_factors([small, large], "2024-04-01")[("supplier", "s")]
    assert factors[2] > factors[1]
    assert factors[1] == factors[3]


def test_anomaly_variants_share_targets_and_repeated_growth_survives():
    history = {
        "2024-01-01": "10",
        "2024-02-01": "10",
        "2024-03-01": "100",
        "2024-04-01": "10",
        "2024-05-01": "10",
    }
    result = evaluate_origins([series(values=history)], ["2024-05-01"])
    row = next(item for item in result["rows"] if item["target_month"] == "2024-06-01")
    assert set(row["predictions"]) >= {"seasonal_damped", "seasonal_damped_adjusted"}
    assert row["predictions"]["seasonal_damped"] != row["predictions"]["seasonal_damped_adjusted"]

    growth = series(values={f"2024-{month:02}-01": str(month * 10) for month in range(1, 6)})
    candidates = candidate_forecasts(growth, "2024-06-01")
    assert candidates["seasonal_damped"][0] > Decimal("30")


def test_temporal_evaluation_ignores_future_rows_and_reports_zero_scale():
    base = series(values={"2024-01-01": "0", "2024-02-01": "0", "2024-03-01": "0", "2024-04-01": "0"})
    poisoned = {
        **base,
        "history": [
            *base["history"],
            {"month": "2024-12-01", "quantity": "999", "evidence": []},
        ],
    }
    first = evaluate_origins([base], ["2024-03-01"])
    second = evaluate_origins([poisoned], ["2024-03-01"])
    assert first["rows"] == second["rows"]
    assert first["metrics"]["recent_level"]["zero_scale"] == 1


def test_promotion_gate_requires_improvement_bias_coverage_and_horizon_safety():
    champion = {
        "primary_error": 1.0,
        "absolute_normalized_bias": 0.1,
        "coverage": 1.0,
        "evaluated": 10,
        "supplier_horizon_error": {"s:1": 1.0},
    }
    challenger = {**champion, "primary_error": 0.98}
    assert not promotion_gate(champion, challenger)["promote"]
    challenger = {**champion, "primary_error": 0.96, "supplier_horizon_error": {"s:1": 1.06}}
    assert not promotion_gate(champion, challenger)["promote"]
