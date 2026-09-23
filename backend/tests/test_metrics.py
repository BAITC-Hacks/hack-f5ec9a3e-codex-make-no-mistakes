import ast
import inspect
import json
import math
from decimal import ROUND_UP, Decimal, Inexact, localcontext

import pytest

import replenishment.metrics as module
from replenishment.metrics import compare_metrics, forecast_metrics


def test_hand_calculated_errors_and_scaled_scores():
    # Absolute errors [2, 4, 1]; signed total -1. Distinct row scales matter.
    result = forecast_metrics([10, 20, 0], [12, 16, 1], mae_scales=[2, 2, 1], mse_scales=[4, 16, 1])
    assert result == {
        "n": 3,
        "actual_qty": 30.0,
        "predicted_qty": 29.0,
        "wape_pct": pytest.approx(100 * 7 / 30),
        "bias_pct": pytest.approx(-100 / 30),
        "underforecast_pct": pytest.approx(100 * 4 / 30),
        "overforecast_pct": 10.0,
        "mae": pytest.approx(7 / 3),
        "rmse": pytest.approx(math.sqrt(7)),
        "zero_actual_pct": pytest.approx(100 / 3),
        "mase": pytest.approx(4 / 3),
        "rmsse": 1.0,
        "mase_n": 3,
        "rmsse_n": 3,
    }
    assert result["wape_pct"] == pytest.approx(result["underforecast_pct"] + result["overforecast_pct"])
    assert result["bias_pct"] == pytest.approx(result["overforecast_pct"] - result["underforecast_pct"])


def test_zero_total_is_undefined_not_a_perfect_forecast():
    result = forecast_metrics([0, 0], [2, 0])
    assert all(
        result[key] is None for key in ("wape_pct", "bias_pct", "underforecast_pct", "overforecast_pct")
    )
    assert result["mae"] == 1 and result["rmse"] == pytest.approx(math.sqrt(2))
    assert result["zero_actual_pct"] == 100
    assert result["mase"] is result["rmsse"] is None
    assert result["mase_n"] == result["rmsse_n"] == 0
    json.dumps(result, allow_nan=False)


def test_undefined_scales_have_independent_coverage_counts():
    result = forecast_metrics(
        [1] * 5, [3] * 5, mae_scales=[None, 0, float("nan"), 1, 2], mse_scales=[4, float("inf"), 0, None, 0]
    )
    assert result["mase_n"] == 2 and result["mase"] == 1.5
    assert result["rmsse_n"] == 1 and result["rmsse"] == 1


@pytest.mark.parametrize(("actual", "predicted"), [([], []), ([1], []), ([1, 2], [1]), ([1], [1, 2])])
def test_cohorts_must_have_identical_nonempty_lengths(actual, predicted):
    with pytest.raises(ValueError, match="identical nonempty lengths"):
        forecast_metrics(actual, predicted)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), float("-inf"), None, "bad", True])
@pytest.mark.parametrize("side", ["actual", "predicted"])
def test_invalid_observations_and_predictions_are_rejected(value, side):
    inputs = {"actual": [1], "predicted": [1], side: [value]}
    with pytest.raises(ValueError, match="finite nonnegative"):
        forecast_metrics(**inputs)


@pytest.mark.parametrize("field", ["mae_scales", "mse_scales"])
def test_scale_length_and_malformed_negative_values_rejected(field):
    for values in ([1, 2], [-1], ["bad"], [True]):
        with pytest.raises(ValueError):
            forecast_metrics([1], [2], **{field: values})


def test_extreme_squared_errors_are_computed_without_float_overflow():
    result = forecast_metrics([1e200, 1e200], [0, 0], mae_scales=[1e200] * 2, mse_scales=[1e300] * 2)
    assert result["mae"] == result["rmse"] == 1e200
    assert result["wape_pct"] == 100 and result["bias_pct"] == -100
    assert result["mase"] == 1 and result["rmsse"] == pytest.approx(1e50)
    json.dumps(result, allow_nan=False)


def test_extreme_error_sum_can_overflow_float_while_metrics_stay_representable():
    result = forecast_metrics([1e308, 0], [0, 1e308])
    assert result["actual_qty"] == result["predicted_qty"] == 1e308
    assert result["mae"] == result["rmse"] == 1e308
    assert result["wape_pct"] == 200 and result["bias_pct"] == 0


def test_bias_preserves_small_error_beside_large_correct_forecast():
    result = forecast_metrics([Decimal("1e100"), Decimal("1")], [Decimal("1e100"), Decimal("0")])
    assert result["bias_pct"] == -1e-98
    assert result["underforecast_pct"] == 1e-98
    assert result["bias_pct"] == result["overforecast_pct"] - result["underforecast_pct"]


@pytest.mark.parametrize(
    ("actual", "predicted"),
    [
        ([1e308, 1e308], [0, 0]),
        ([1e-308], [1e308]),
        ([Decimal("1e-999999")], [0]),
        ([Decimal("1e999999")], [0]),
    ],
)
def test_unrepresentable_outputs_fail_without_nonfinite_json(actual, predicted):
    with pytest.raises(ValueError, match="representable"):
        forecast_metrics(actual, predicted)


def test_metrics_ignore_caller_decimal_context_and_do_not_mutate_inputs():
    actual, predicted = [Decimal("1"), Decimal("2"), Decimal("4")], [Decimal("0"), Decimal("1"), Decimal("3")]
    snapshot = actual[:], predicted[:]
    expected = forecast_metrics(actual, predicted)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        assert forecast_metrics(actual, predicted) == expected
    assert (actual, predicted) == snapshot


def metrics(wape, bias=0, n=2, actual=100):
    return {"n": n, "actual_qty": actual, "wape_pct": wape, "bias_pct": bias}


def test_promotion_gates_pass_exact_boundaries_and_report_both_failures():
    passed = compare_metrics(metrics(18, 5), metrics(20))
    assert passed == {"status": "pass", "wape_improvement_pct": 10.0, "reasons": []}
    failed = compare_metrics(metrics(19, -6), metrics(20))
    assert failed["status"] == "fail" and failed["wape_improvement_pct"] == 5
    assert len(failed["reasons"]) == 2
    assert all("internal gate" in reason for reason in failed["reasons"])
    assert (
        compare_metrics(metrics(19, -6), metrics(20), min_improvement_pct=5, max_abs_bias_pct=6)["status"]
        == "pass"
    )


def test_zero_actual_or_zero_baseline_has_explicit_evaluability():
    undefined = forecast_metrics([0], [0])
    assert compare_metrics(undefined, undefined)["status"] == "not_evaluable"
    assert compare_metrics(metrics(1), metrics(0))["status"] == "not_evaluable"
    equal = compare_metrics(metrics(0), metrics(0))
    assert equal["status"] == "fail" and equal["wape_improvement_pct"] == 0
    assert compare_metrics(metrics(0), metrics(0), min_improvement_pct=0)["status"] == "pass"


@pytest.mark.parametrize("candidate", [metrics(10, n=3), metrics(10, actual=99)])
def test_incomparable_cohorts_are_integrity_errors_not_promotion_failures(candidate):
    with pytest.raises(ValueError, match="identical n and actual_qty"):
        compare_metrics(candidate, metrics(20))


@pytest.mark.parametrize(
    "changes",
    [
        {"n": 0},
        {"n": True},
        {"actual_qty": -1},
        {"wape_pct": -1},
        {"wape_pct": float("inf")},
        {"bias_pct": float("nan")},
        {"bias_pct": "bad"},
        {"bias_pct": True},
    ],
)
def test_invalid_metric_summaries_are_rejected(changes):
    with pytest.raises(ValueError):
        compare_metrics({**metrics(10), **changes}, metrics(20))


@pytest.mark.parametrize("field", ["n", "actual_qty", "wape_pct", "bias_pct"])
def test_missing_metric_summary_fields_are_rejected(field):
    candidate = metrics(10)
    candidate.pop(field)
    with pytest.raises(ValueError):
        compare_metrics(candidate, metrics(20))


@pytest.mark.parametrize(
    "settings",
    [
        {"min_improvement_pct": -1},
        {"max_abs_bias_pct": -1},
        {"max_abs_bias_pct": float("nan")},
        {"min_improvement_pct": True},
    ],
)
def test_invalid_internal_gate_settings_rejected(settings):
    with pytest.raises(ValueError):
        compare_metrics(metrics(10), metrics(20), **settings)


def test_stdlib_module_is_python310_syntax_compatible():
    tree = ast.parse(inspect.getsource(module), feature_version=(3, 10))
    imports = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports <= {"decimal", "math"}
