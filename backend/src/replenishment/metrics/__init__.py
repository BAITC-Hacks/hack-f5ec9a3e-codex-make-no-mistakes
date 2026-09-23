"""Reusable forecast metrics and internal promotion gates (stdlib, Python 3.10+).

MASE is the mean absolute error divided by each row's training MAE scale.
RMSSE is the square root of the mean squared error divided by each row's
training MSE scale. Missing, zero or nonfinite scales are excluded from the
respective scaled score; negative/malformed scales are invalid input.
"""

from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from math import isfinite

__all__ = ["forecast_metrics", "compare_metrics"]


def _number(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError(f"{label} must be a finite nonnegative number") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    _output(number, label)
    return number


def _output(value, label):
    """Keep metrics JSON-safe; never silently emit Infinity or underflow to zero."""
    result = float(value)
    if not isfinite(result) or (value != 0 and result == 0):
        raise ValueError(f"{label} is outside the finite representable output range")
    return result


def _scales(values, length, label):
    if values is None:
        return [None] * length
    values = list(values)
    if len(values) != length:
        raise ValueError(f"{label} must have the same length as actual and predicted")
    result = []
    for index, value in enumerate(values):
        if value is None:
            result.append(None)
            continue
        if isinstance(value, bool):
            raise ValueError(f"{label}[{index}] must be a nonnegative scale or None")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise ValueError(f"{label}[{index}] must be a nonnegative scale or None") from error
        if not number.is_finite() or number == 0:
            result.append(None)
        elif number < 0:
            raise ValueError(f"{label}[{index}] cannot be negative")
        else:
            _output(number, f"{label}[{index}]")
            result.append(number)
    return result


def forecast_metrics(actual, predicted, *, mae_scales=None, mse_scales=None) -> dict:
    """Score identical nonempty target cohorts; positive bias means overforecast.

    WAPE, signed bias and under/over quantities are percentages of total actual.
    They are undefined (None) when that total is zero. Scaled scores average
    only rows with defined positive training scales and report their row counts.
    Numerical output overflow or underflow raises ValueError instead of emitting
    nonfinite JSON or fabricated zeros. Inputs and caller Decimal settings are
    never mutated.
    """
    actual, predicted = list(actual), list(predicted)
    if not actual or len(actual) != len(predicted):
        raise ValueError("actual and predicted must have identical nonempty lengths")
    n = len(actual)
    # Decimal avoids overflow of representable errors when squaring (e.g. 1e200).
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        observed = [_number(value, f"actual[{index}]") for index, value in enumerate(actual)]
        forecast = [_number(value, f"predicted[{index}]") for index, value in enumerate(predicted)]
        mae_denominators = _scales(mae_scales, n, "mae_scales")
        mse_denominators = _scales(mse_scales, n, "mse_scales")
        errors = [forecast[index] - observed[index] for index in range(n)]
        absolute = [abs(error) for error in errors]
        actual_total, predicted_total = sum(observed), sum(forecast)
        absolute_total = sum(absolute)
        under = sum(-error for error in errors if error < 0)
        over = sum(error for error in errors if error > 0)
        scaled_absolute = [
            absolute[index] / scale for index, scale in enumerate(mae_denominators) if scale is not None
        ]
        scaled_squared = [
            errors[index] ** 2 / scale for index, scale in enumerate(mse_denominators) if scale is not None
        ]

        def percentage(value):
            return _output(100 * value / actual_total, "percentage") if actual_total else None

        return {
            "n": n,
            "actual_qty": _output(actual_total, "actual_qty"),
            "predicted_qty": _output(predicted_total, "predicted_qty"),
            "wape_pct": percentage(absolute_total),
            "bias_pct": percentage(sum(errors)),
            "underforecast_pct": percentage(under),
            "overforecast_pct": percentage(over),
            "mae": _output(absolute_total / n, "mae"),
            "rmse": _output((sum(error**2 for error in errors) / n).sqrt(), "rmse"),
            "zero_actual_pct": _output(Decimal(100) * observed.count(0) / n, "zero_actual_pct"),
            "mase": _output(sum(scaled_absolute) / len(scaled_absolute), "mase") if scaled_absolute else None,
            "rmsse": _output((sum(scaled_squared) / len(scaled_squared)).sqrt(), "rmsse")
            if scaled_squared
            else None,
            "mase_n": len(scaled_absolute),
            "rmsse_n": len(scaled_squared),
        }


def compare_metrics(candidate, baseline, *, min_improvement_pct=10, max_abs_bias_pct=5) -> dict:
    """Apply configurable internal proposals, not industry-standard thresholds.

    Mismatched cohorts or malformed metrics raise ValueError (integrity failure).
    Undefined metrics produce not_evaluable. A valid model missing a threshold
    produces fail. Matching counts/totals do not prove identical individual
    targets; the evaluation pipeline must check those keys independently.
    """
    improvement_limit = _number(min_improvement_pct, "min_improvement_pct")
    bias_limit = _number(max_abs_bias_pct, "max_abs_bias_pct")
    for label, metrics in (("candidate", candidate), ("baseline", baseline)):
        if not isinstance(metrics.get("n"), int) or isinstance(metrics["n"], bool) or metrics["n"] < 1:
            raise ValueError(f"{label}.n must be a positive integer")
        if "actual_qty" not in metrics:
            raise ValueError(f"{label}.actual_qty is required")
        _number(metrics["actual_qty"], f"{label}.actual_qty")
        for field in ("wape_pct", "bias_pct"):
            if field not in metrics:
                raise ValueError(f"{label}.{field} is required")
            if metrics[field] is not None:
                if field == "bias_pct":
                    try:
                        value = Decimal(str(metrics[field]))
                    except (InvalidOperation, ValueError, TypeError) as error:
                        raise ValueError(f"{label}.{field} must be finite") from error
                    if not value.is_finite() or isinstance(metrics[field], bool):
                        raise ValueError(f"{label}.{field} must be finite")
                    _output(value, f"{label}.{field}")
                else:
                    _number(metrics[field], f"{label}.{field}")
    if candidate["n"] != baseline["n"] or Decimal(str(candidate["actual_qty"])) != Decimal(
        str(baseline["actual_qty"])
    ):
        raise ValueError("Candidate and baseline must have identical n and actual_qty cohorts")
    if any(metrics[field] is None for metrics in (candidate, baseline) for field in ("wape_pct", "bias_pct")):
        return {
            "status": "not_evaluable",
            "wape_improvement_pct": None,
            "reasons": ["WAPE or bias is undefined; no promotion decision is available."],
        }
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        baseline_wape = Decimal(str(baseline["wape_pct"]))
        candidate_wape = Decimal(str(candidate["wape_pct"]))
        if baseline_wape == 0 and candidate_wape != 0:
            return {
                "status": "not_evaluable",
                "wape_improvement_pct": None,
                "reasons": ["Baseline WAPE is zero; relative improvement has a zero denominator."],
            }
        improvement = 100 * (baseline_wape - candidate_wape) / baseline_wape if baseline_wape else Decimal(0)
        reasons = []
        if improvement < improvement_limit:
            reasons.append(
                f"WAPE improvement {_output(improvement, 'improvement'):g}% is below "
                f"the internal gate of {improvement_limit}%."
            )
        bias = abs(Decimal(str(candidate["bias_pct"])))
        if bias > bias_limit:
            reasons.append(f"Absolute candidate bias {bias}% exceeds the internal gate of {bias_limit}%.")
        return {
            "status": "fail" if reasons else "pass",
            "wape_improvement_pct": _output(improvement, "wape_improvement_pct"),
            "reasons": reasons,
        }
