"""End-to-end regressions using slices of the supplied monthly documents."""

from copy import deepcopy
from decimal import Decimal

import pytest
from evaluation.cases import read_batch

from replenishment.calculation import calculate
from replenishment.calculation.forecasting import forecast_batch
from replenishment.calculation.purchasing import build_drafts


@pytest.fixture(scope="module")
def source_batch():
    batch = read_batch()
    series = next(
        s for s in batch["series"] if sum(Decimal(h["quantity"] or "0") > 0 for h in s["history"]) >= 24
    )
    return {**batch, "series": [series]}


def test_bridge_is_full_month_then_prorated_once(source_batch):
    forecasts, bridges = forecast_batch(source_batch["series"], "2026-09-22", include_bridge=True)
    assert bridges[0]["basis"] == "full_month"
    draft = build_drafts(source_batch, forecasts, bridges)[0]
    assert Decimal(draft["components"]["bridge_demand"]) == Decimal(bridges[0]["quantity"]) * 9 / 30
    first_day = {**source_batch, "planning_date": "2026-09-01"}
    forecasts, bridges = forecast_batch(first_day["series"], first_day["planning_date"], include_bridge=True)
    draft = build_drafts(first_day, forecasts, bridges)[0]
    assert Decimal(draft["components"]["bridge_demand"]) == Decimal(bridges[0]["quantity"])


def test_runtime_uses_frozen_development_champion(source_batch):
    result = calculate(source_batch)
    selected = result["quality"]["evaluation"]["selection_frozen"]
    assert all(row["model"] == selected for row in result["forecasts"])
    changed = deepcopy(source_batch)
    for observation in changed["series"][0]["history"]:
        if observation["month"].startswith("2026") and observation["quantity"] is not None:
            observation["quantity"] = str(Decimal(observation["quantity"]) * 10)
    assert calculate(changed)["quality"]["evaluation"]["selection_frozen"] == selected


def test_unknown_purchase_conversion_and_missing_stock_do_not_become_one_or_zero(source_batch):
    batch = deepcopy(source_batch)
    series = batch["series"][0]
    series["purchase_unit"] = "pack"
    draft = calculate(batch)["drafts"][0]
    assert draft["quantity"] is None
    assert draft["components"]["raw_need"] is None
    assert draft["components"]["conversion"] is None


def test_ml_features_and_fitting_only_use_completed_training_targets(source_batch, monkeypatch):
    from replenishment.calculation import ml

    series = source_batch["series"][0]
    before = ml.feature_row(series, "2025-06-01")
    changed = deepcopy(series)
    for row in changed["history"]:
        if row["month"] >= "2025-06-01" and row["quantity"] is not None:
            row["quantity"] = str(Decimal(row["quantity"]) * 100)
    assert ml.feature_row(changed, "2025-06-01") == before
    fitting = []

    def inspect_fit(examples, prediction_rows):
        fitting.append(max(item["target_month"] for item in examples))
        return [row["features"]["level_3"] for row in prediction_rows]

    monkeypatch.setattr(ml, "_fit_predictions", inspect_fit)
    ml.evaluate_lightgbm_origins([series], ["2025-06-01", "2025-07-01"])
    assert fitting[0] < "2025-06-01" and fitting[1] < "2025-07-01"
