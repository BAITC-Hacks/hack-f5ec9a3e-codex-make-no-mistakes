"""Independent synthetic evaluation acceptance: fixed targets, dates, and arithmetic.

No workbook import, database, training, or prior experiment artifact is needed.
Forecast comparisons use 1e-12 absolute tolerance only for float serialization.
"""

import importlib
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest

from replenishment.evaluation import runner
from replenishment.planning import calculator

ORIGIN = date(2025, 7, 1)
MODELS = ("backend_raw", "backend_bulk", "mean28", "weekly_naive")


def series(
    *, supplier: str = "Synthetic supplier", unit: str = "piece", warehouse: str = "Almaty",
    sku: str = "SYNTHETIC", quantity: int = 10,
) -> dict:
    start = ORIGIN - timedelta(days=140)
    end = ORIGIN + timedelta(days=27)
    return {
        "supplier": supplier,
        "warehouse": warehouse,
        "unit": unit,
        "sku": sku,
        "name": "Synthetic evaluation product",
        "start": start,
        "end": end,
        "sales": [
            {"day": start + timedelta(days=index), "quantity": Decimal(quantity), "document": f"sale-{index}"}
            for index in range((end - start).days + 1)
        ],
    }


def target_key(row: dict) -> tuple:
    return tuple(row[field] for field in ("supplier", "warehouse", "unit", "sku", "origin", "horizon"))


def without_actual(predictions: list[dict]) -> list[dict]:
    rows = [{key: value for key, value in row.items() if key != "actual"} for row in predictions]
    return sorted(rows, key=lambda row: (*target_key(row), row["model_id"]))


def test_every_model_forecasts_same_constant_history_and_identical_targets() -> None:
    predictions = runner.evaluate_series([series()], origins=[ORIGIN], models=MODELS, horizons=(7, 28))

    assert len(predictions) == 8
    cohorts = {}
    for model in MODELS:
        rows = [row for row in predictions if row["model_id"] == model]
        assert len(rows) == 2
        cohorts[model] = {target_key(row): row["actual"] for row in rows}
        for row in rows:
            assert row["actual"] == row["horizon"] * 10
            assert row["forecast"] == pytest.approx(row["actual"], abs=1e-12)
            assert row["origin"] == ORIGIN.isoformat()
            assert row["phase"] == "development_2025"
            assert row["segment"] == "regular"
    assert all(cohort == cohorts[MODELS[0]] for cohort in cohorts.values())


def test_future_sales_cannot_change_predictions_segments_eligibility_or_scales() -> None:
    original = series()
    changed = deepcopy(original)
    for sale in changed["sales"]:
        if sale["day"] >= ORIGIN:
            sale["quantity"] = Decimal(1000000 if sale["day"].day % 2 else 0)
            sale["document"] = "future-document-must-not-reach-training"
    untouched = deepcopy(original)
    before = runner.evaluate_series([original], origins=[ORIGIN], models=MODELS)
    after = runner.evaluate_series([changed], origins=[ORIGIN], models=MODELS)

    assert before and after
    assert without_actual(before) == without_actual(after)
    assert [row["actual"] for row in before] != [row["actual"] for row in after]
    assert original == untouched


def test_first_positive_sale_requires_ninety_prior_calendar_days() -> None:
    eligible = series(sku="eligible")
    recent = series(sku="recent")
    future_only = series(sku="future-only")
    eligible["sales"] = [
        {"day": ORIGIN - timedelta(days=90), "quantity": Decimal(1), "document": "first-positive"}
    ]
    recent["sales"] = [
        {"day": ORIGIN - timedelta(days=89), "quantity": Decimal(1), "document": "too-recent"}
    ]
    future_only["sales"] = [{"day": ORIGIN, "quantity": Decimal(10000), "document": "future"}]
    predictions = runner.evaluate_series(
        [eligible, recent, future_only], origins=[ORIGIN], min_history_days=90, models=MODELS
    )

    assert predictions
    assert {row["sku"] for row in predictions} == {"eligible"}
    assert {row["segment"] for row in predictions} == {"intermittent"}


def test_zero_history_threshold_still_cannot_admit_a_product_based_on_future_sales() -> None:
    item = series()
    item["sales"] = [{"day": ORIGIN, "quantity": Decimal(10000), "document": "future-only"}]
    assert runner.evaluate_series(
        [item], origins=[ORIGIN], horizons=(7,), models=MODELS, min_history_days=0
    ) == []


def test_regular_segment_requires_four_active_weeks_inside_previous_eight_weeks() -> None:
    sparse = series(sku="three-active-weeks")
    sparse["sales"] = [
        {"day": ORIGIN - timedelta(days=offset), "quantity": Decimal(1), "document": f"sale-{offset}"}
        for offset in (140, 63, 1, 8, 15)
    ]
    regular = deepcopy(sparse)
    regular["sku"] = "four-active-weeks"
    regular["sales"].append(
        {"day": ORIGIN - timedelta(days=22), "quantity": Decimal(1), "document": "fourth"}
    )
    predictions = runner.evaluate_series(
        [sparse, regular], origins=[ORIGIN], models=("mean28",), horizons=(7,)
    )

    assert {row["sku"]: row["segment"] for row in predictions} == {
        "three-active-weeks": "intermittent", "four-active-weeks": "regular"
    }


def test_complete_coverage_includes_its_last_day_but_never_extends_past_it() -> None:
    complete = series()
    accepted = runner.evaluate_series([complete], origins=[ORIGIN], horizons=(28,), models=("mean28",))
    assert accepted[0]["actual"] == 280
    incomplete = deepcopy(complete)
    incomplete["end"] = ORIGIN + timedelta(days=26)
    incomplete["sales"] = [sale for sale in incomplete["sales"] if sale["day"] <= incomplete["end"]]
    with pytest.raises(ValueError):
        runner.evaluate_series([incomplete], origins=[ORIGIN], horizons=(28,), models=MODELS)


def test_coverage_validation_does_not_silently_drop_only_the_incomplete_supplier() -> None:
    complete = series(supplier="A")
    incomplete = series(supplier="B")
    incomplete["end"] = ORIGIN + timedelta(days=5)
    incomplete["sales"] = [sale for sale in incomplete["sales"] if sale["day"] <= incomplete["end"]]
    with pytest.raises(ValueError):
        runner.evaluate_series([complete, incomplete], origins=[ORIGIN], horizons=(7,), models=MODELS)


def test_scale_uses_horizon_aggregates_instead_of_daily_naive_errors() -> None:
    item = series()
    for sale in item["sales"]:
        if sale["day"] < ORIGIN:
            sale["quantity"] = Decimal((sale["day"] - item["start"]).days // 7 + 1)
    predictions = runner.evaluate_series([item], origins=[ORIGIN], horizons=(7, 28), models=MODELS)

    # Twenty historical weeks have daily levels 1,2,...,20. Successive weekly
    # totals differ by 7; successive four-week totals differ by 4 * 4 * 7 = 112.
    for row in predictions:
        expected_mae = 7 if row["horizon"] == 7 else 112
        assert row["mae_scale"] == pytest.approx(expected_mae, abs=1e-12)
        assert row["mse_scale"] == pytest.approx(expected_mae**2, abs=1e-12)


def test_zero_training_scale_is_undefined_and_counts_remain_visible() -> None:
    predictions = runner.evaluate_series([series()], origins=[ORIGIN], models=("mean28",), horizons=(7,))
    assert predictions[0]["mae_scale"] is None
    assert predictions[0]["mse_scale"] is None
    summary = runner.summarize(predictions)
    group = next(row for row in summary if row["segment"] == "all")
    assert group["mase"] is None and group["rmsse"] is None
    assert group["mase_n"] == group["rmsse_n"] == 0


def test_same_sku_across_suppliers_units_and_warehouses_is_never_combined() -> None:
    inputs = [
        series(supplier="A", unit="piece", warehouse="Almaty", quantity=10),
        series(supplier="B", unit="piece", warehouse="Almaty", quantity=20),
        series(supplier="A", unit="metre", warehouse="Almaty", quantity=30),
        series(supplier="A", unit="piece", warehouse="Astana", quantity=40),
    ]
    predictions = runner.evaluate_series(inputs, origins=[ORIGIN], models=("mean28",), horizons=(7,))
    expected = {
        ("A", "piece", "Almaty"): 70,
        ("B", "piece", "Almaty"): 140,
        ("A", "metre", "Almaty"): 210,
        ("A", "piece", "Astana"): 280,
    }
    assert len(predictions) == 4
    for row in predictions:
        assert row["actual"] == row["forecast"] == expected[row["supplier"], row["unit"], row["warehouse"]]
    summary = [row for row in runner.summarize(predictions) if row["segment"] == "all"]
    assert len(summary) == 4
    for row in summary:
        assert row["actual_qty"] == expected[row["supplier"], row["unit"], row["warehouse"]]
        assert row["sku_count"] == row["origin_count"] == 1


def test_raw_and_bulk_models_share_actual_targets_even_when_both_periods_contain_spikes() -> None:
    item = series()
    for sale in item["sales"]:
        if sale["day"] in (ORIGIN - timedelta(days=14), ORIGIN + timedelta(days=3)):
            sale["quantity"] = Decimal(1010)
    predictions = runner.evaluate_series(
        [item], origins=[ORIGIN], horizons=(7,), models=("backend_raw", "backend_bulk")
    )
    rows = {row["model_id"]: row for row in predictions}

    assert rows["backend_raw"]["forecast"] == pytest.approx(195, abs=1e-12)
    assert rows["backend_bulk"]["forecast"] == pytest.approx(70, abs=1e-12)
    assert rows["backend_raw"]["actual"] == rows["backend_bulk"]["actual"] == 1070
    assert target_key(rows["backend_raw"]) == target_key(rows["backend_bulk"])


def test_backend_models_use_public_calculator_forecast_and_only_historical_sales(monkeypatch) -> None:
    calls = []
    actual_calculate = calculator.calculate

    def watched_calculate(request):
        calls.append(request)
        output = actual_calculate(request)
        for row in output.rows:
            row.forecast_demand = Decimal("123.25")
        return output

    # Reload only within the patch so a normal `from ... import calculate`
    # reference is observed too; restore the runner's binding after the check.
    try:
        with monkeypatch.context() as patch:
            patch.setattr(calculator, "calculate", watched_calculate)
            importlib.reload(runner)
            predictions = runner.evaluate_series(
                [series()], origins=[ORIGIN], horizons=(7,), models=("backend_raw", "backend_bulk")
            )
    finally:
        importlib.reload(runner)

    assert {request.exclude_bulk for request in calls} == {False, True}
    assert all(request.planning_date == ORIGIN for request in calls)
    assert all(sale.day < ORIGIN for request in calls for row in request.rows for sale in row.sales)
    assert {row["forecast"] for row in predictions} == {123.25}
    assert {row["actual"] for row in predictions} == {70}


def test_summary_uses_fixed_target_arithmetic_and_unique_sku_origin_counts() -> None:
    common = {
        "supplier": "A", "warehouse": "Almaty", "unit": "piece", "horizon": 7,
        "phase": "development_2025", "segment": "regular", "model_id": "mean28",
        "mae_scale": 5.0, "mse_scale": 25.0,
    }
    predictions = [
        dict(common, sku="one", origin="2025-07-01", actual=10.0, forecast=5.0),
        dict(common, sku="one", origin="2025-08-01", actual=20.0, forecast=25.0),
        dict(common, sku="two", origin="2025-08-01", actual=0.0, forecast=0.0),
    ]
    summary = runner.summarize(predictions)
    group = next(row for row in summary if row["segment"] == "all")

    assert group["n"] == 3
    assert group["sku_count"] == group["origin_count"] == 2
    assert group["actual_qty"] == group["predicted_qty"] == 30
    assert group["wape_pct"] == pytest.approx(100 / 3)
    assert group["bias_pct"] == 0
    assert group["underforecast_pct"] == group["overforecast_pct"] == pytest.approx(100 / 6)
    assert group["mae"] == pytest.approx(10 / 3)
    assert group["rmse"] == pytest.approx((50 / 3) ** 0.5)
    assert group["mase"] == pytest.approx(2 / 3)
    assert group["rmsse"] == pytest.approx((2 / 3) ** 0.5)


def test_phase_and_segment_are_kept_separate_in_summary() -> None:
    common = {
        "supplier": "A", "warehouse": "Almaty", "unit": "piece", "sku": "same", "horizon": 7,
        "model_id": "mean28", "mae_scale": None, "mse_scale": None,
    }
    predictions = [
        dict(
            common, origin="2025-07-01", phase="development_2025", segment="regular", actual=10, forecast=10
        ),
        dict(
            common, origin="2026-07-01", phase="retrospective_2026", segment="intermittent",
            actual=0, forecast=5,
        ),
    ]
    summary = runner.summarize(predictions)
    groups = {(row["phase"], row["segment"]): row for row in summary}

    assert groups["development_2025", "all"]["actual_qty"] == 10
    assert groups["retrospective_2026", "all"]["actual_qty"] == 0
    assert groups["development_2025", "regular"]["n"] == 1
    assert groups["retrospective_2026", "intermittent"]["n"] == 1
