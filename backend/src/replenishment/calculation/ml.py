"""Research-only monthly LightGBM challenger.

The feature builder is dependency-free so temporal isolation can be tested in
the backend environment. LightGBM is imported only by the fitting function;
the production calculation path therefore has no research dependency.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from math import cos, isfinite, pi, sin, sqrt
from typing import Any

from .contracts import month_date, planning_date
from .forecasting import _add_months, _valid_history

MODEL_CONFIG: dict[str, Any] = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.5,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 10,
    "lambda_l2": 1.0,
    "max_bin": 63,
    "num_threads": 2,
    "verbosity": -1,
    "seed": 20260923,
    "deterministic": True,
    "force_col_wise": True,
}
BOOSTING_ROUNDS = 150


def feature_names() -> list[str]:
    names = ["age_months", "missing_count", "scale", "month_sin", "month_cos"]
    names += [f"lag_{lag}" for lag in range(1, 13)]
    names += [f"lag_{lag}_missing" for lag in range(1, 13)]
    names += [f"level_{window}" for window in (3, 6, 12)]
    names += [f"variability_{window}" for window in (3, 6, 12)]
    names += [f"active_fraction_{window}" for window in (3, 6, 12)]
    names += ["recent_change_3", "recent_change_6"]
    return names


def _cutoff(value: str | date) -> date:
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    return planning_date(value if len(value) == 10 else f"{value}-01")


def _history_map(series: dict[str, Any], cutoff: date) -> dict[str, float | None]:
    """Return source values keyed by canonical month, preserving missing cells."""

    values: dict[str, float | None] = {}
    cutoff_index = cutoff.year * 12 + cutoff.month
    for observation in series.get("history", []):
        stamp = observation.get("month")
        if not isinstance(stamp, str):
            continue
        normalized = stamp if len(stamp) == 10 else f"{stamp}-01"
        try:
            parsed = month_date(normalized)
        except (TypeError, ValueError):
            continue
        if parsed.year * 12 + parsed.month >= cutoff_index:
            continue
        quantity = observation.get("quantity")
        try:
            parsed_quantity = float(quantity) if quantity is not None else None
        except (TypeError, ValueError):
            parsed_quantity = None
        values[parsed.isoformat()] = (
            parsed_quantity
            if parsed_quantity is not None and isfinite(parsed_quantity) and parsed_quantity >= 0
            else None
        )
    return values


def feature_row(
    series: dict[str, Any], cutoff: str | date, target_month: str | date | None = None
) -> dict[str, float]:
    """Build as-of features; observations at or after cutoff are never read."""

    cutoff_month = _cutoff(cutoff)
    target = _add_months(cutoff_month, 1) if target_month is None else _cutoff(target_month)
    values = _history_map(series, cutoff_month)
    history = _valid_history(series, cutoff_month)
    last = history[-1][0] if history else cutoff_month
    age = max(
        (cutoff_month.year - last.year) * 12 + cutoff_month.month - last.month,
        0,
    )
    lags: list[float | None] = [
        values.get(_add_months(cutoff_month, -lag).isoformat()) for lag in range(1, 13)
    ]
    row: dict[str, float] = {
        "age_months": float(age),
        "missing_count": float(sum(value is None for value in lags)),
        "scale": float(sum(quantity for _, quantity in history) / len(history)) if history else 0.0,
        # Target calendar month is known at prediction time and avoids using the
        # origin month as a proxy for the actual target period.
        "month_sin": sin(2 * pi * target.month / 12),
        "month_cos": cos(2 * pi * target.month / 12),
    }
    row.update({f"lag_{lag}": value if value is not None else 0.0 for lag, value in enumerate(lags, 1)})
    row.update({f"lag_{lag}_missing": float(value is None) for lag, value in enumerate(lags, 1)})
    for window in (3, 6, 12):
        window_values = [value for value in lags[:window] if value is not None]
        row[f"level_{window}"] = sum(window_values) / len(window_values) if window_values else 0.0
        if len(window_values) > 1:
            mean = row[f"level_{window}"]
            row[f"variability_{window}"] = sqrt(
                sum((value - mean) ** 2 for value in window_values) / len(window_values)
            )
        else:
            row[f"variability_{window}"] = 0.0
        row[f"active_fraction_{window}"] = (
            sum(value is not None and value > 0 for value in lags[:window]) / window
        )
    for window in (3, 6):
        values_window = [value for value in lags[:window] if value is not None]
        older_window = [value for value in lags[window : 2 * window] if value is not None]
        recent = sum(values_window) / len(values_window) if values_window else 0.0
        older = sum(older_window) / len(older_window) if older_window else recent
        row[f"recent_change_{window}"] = recent - older
    return row


def _actuals(series: dict[str, Any]) -> dict[str, float]:
    actuals: dict[str, float] = {}
    for item in series.get("history", []):
        stamp = item.get("month")
        if not isinstance(stamp, str) or item.get("quantity") is None:
            continue
        normalized = stamp if len(stamp) == 10 else f"{stamp}-01"
        try:
            month = month_date(normalized).isoformat()
            quantity = float(item["quantity"])
        except (TypeError, ValueError):
            continue
        if isfinite(quantity) and quantity >= 0:
            actuals[month] = quantity
    return actuals


def build_training_examples(
    series_batch: Iterable[dict[str, Any]], origins: Iterable[str | date], horizon: int | None = None
) -> list[dict[str, Any]]:
    """Create scale-normalized labels from complete target months only.

    A zero target is valid when the historical scale is positive. Missing or
    invalid targets are skipped, never converted into zero labels.
    """

    if horizon is not None and (horizon < 1 or horizon > 3):
        raise ValueError("Monthly challenger horizon must be between 1 and 3")
    examples: list[dict[str, Any]] = []
    for series in series_batch:
        actuals = _actuals(series)
        for raw_origin in origins:
            cutoff = _cutoff(raw_origin)
            history = _valid_history(series, cutoff)
            scale = sum(quantity for _, quantity in history) / len(history) if history else 0.0
            if not history or scale <= 0:
                continue
            horizons = (horizon,) if horizon is not None else (1, 2, 3)
            for current_horizon in horizons:
                target = _add_months(cutoff, current_horizon).isoformat()
                actual = actuals.get(target)
                if actual is None:
                    continue
                examples.append(
                    {
                        "supplier": series["supplier"],
                        "series_id": series["series_id"],
                        "origin": cutoff.isoformat(),
                        "target_month": target,
                        "horizon": current_horizon,
                        "features": feature_row(series, cutoff, target),
                        "target": actual / float(scale),
                        "scale": float(scale),
                    }
                )
    return examples


def _fit_predictions(
    examples: list[dict[str, Any]], prediction_rows: list[dict[str, Any]]
) -> list[float | None]:
    try:
        import lightgbm as lgb
        import numpy as np
    except ImportError as exc:  # pragma: no cover - research environment only
        raise RuntimeError("LightGBM research dependencies are not installed") from exc
    if not examples:
        return [None] * len(prediction_rows)
    names = feature_names()
    models: dict[tuple[str, int], Any] = {}
    for supplier, horizon in sorted({(item["supplier"], int(item["horizon"])) for item in examples}):
        selected = [
            item for item in examples if item["supplier"] == supplier and int(item["horizon"]) == horizon
        ]
        features = np.asarray([[item["features"][name] for name in names] for item in selected], dtype=float)
        labels = np.asarray([item["target"] for item in selected], dtype=float)
        models[(supplier, horizon)] = lgb.train(
            MODEL_CONFIG,
            lgb.Dataset(features, label=labels, feature_name=names),
            num_boost_round=BOOSTING_ROUNDS,
        )
    predictions = [0.0 if item.get("scale") == 0 else None for item in prediction_rows]
    for key, model in models.items():
        indexes = [
            i
            for i, row in enumerate(prediction_rows)
            if (row["supplier"], int(row["horizon"])) == key and row.get("scale", 0) > 0
        ]
        if not indexes:
            continue
        matrix = np.asarray(
            [[prediction_rows[i]["features"][name] for name in names] for i in indexes], dtype=float
        )
        values = model.predict(matrix, num_threads=2)
        for i, value in zip(indexes, values, strict=True):
            predictions[i] = max(float(value) * float(prediction_rows[i]["scale"]), 0.0)
    return predictions


def fit_lightgbm_challenger(
    examples: Iterable[dict[str, Any]], prediction_rows: Iterable[dict[str, Any]]
) -> list[float | None]:
    """Fit one fixed Tweedie model per supplier and forecast horizon."""

    return _fit_predictions(list(examples), list(prediction_rows))


def _training_origins(series_batch: list[dict[str, Any]], end: date) -> list[date]:
    months = []
    for series in series_batch:
        valid = _valid_history(series, end)
        months.extend(when for when, _ in valid)
    if not months:
        return []
    first = date(min(months).year, min(months).month, 1)
    origins: list[date] = []
    origin = _add_months(first, 1)
    while origin < end:
        origins.append(origin)
        origin = _add_months(origin, 1)
    return origins


def evaluate_lightgbm_origins(
    series_batch: Iterable[dict[str, Any]], origins: Iterable[str | date], *, phase: str | None = None
) -> dict[str, Any]:
    """Evaluate leakage-safe ML predictions on the same target keys as stats."""

    from time import perf_counter

    series_batch = list(series_batch)
    origins = [_cutoff(origin) for origin in origins]
    started = perf_counter()
    examples = (
        build_training_examples(series_batch, _training_origins(series_batch, max(origins)))
        if origins
        else []
    )
    rows: list[dict[str, Any]] = []
    training_summary: list[dict[str, Any]] = []
    for planning in origins:
        cutoff = planning.isoformat()
        eligible = [series for series in series_batch if _valid_history(series, planning)]
        training = [item for item in examples if item["target_month"] < cutoff]
        prediction_rows: list[dict[str, Any]] = []
        row_keys: list[tuple[dict[str, Any], int, str]] = []
        for series in eligible:
            for horizon in (1, 2, 3):
                target = _add_months(planning, horizon).isoformat()
                features = feature_row(series, planning, target)
                prediction_rows.append(
                    {
                        "supplier": series["supplier"],
                        "horizon": horizon,
                        "features": features,
                        "scale": features["scale"],
                    }
                )
                row_keys.append((series, horizon, target))
        predictions = _fit_predictions(training, prediction_rows)
        for prediction_row, (series, horizon, target), prediction in zip(
            prediction_rows, row_keys, predictions, strict=True
        ):
            rows.append(
                {
                    "series_id": series["series_id"],
                    "supplier": series["supplier"],
                    "sku": series["sku"],
                    "unit": series.get("unit"),
                    "origin": cutoff,
                    "target_month": target,
                    "horizon": horizon,
                    "actual": _actuals(series).get(target),
                    "training_scale": prediction_row["scale"],
                    "predictions": {"lightgbm": prediction},
                }
            )
        training_summary.append(
            {
                "origin": cutoff,
                "training_examples": len(training),
                "prediction_rows": len(prediction_rows),
            }
        )
    from .evaluation import _metric

    return {
        "rows": rows,
        "metrics": {"lightgbm": _metric(rows, "lightgbm")},
        "training": training_summary,
        "runtime_seconds": perf_counter() - started,
        "origins": [origin.isoformat() for origin in origins],
        "phase": phase,
    }
