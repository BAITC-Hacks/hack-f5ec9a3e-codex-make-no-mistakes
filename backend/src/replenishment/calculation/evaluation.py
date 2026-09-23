"""Leakage-safe temporal evaluation for the monthly calculation candidates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from time import perf_counter
from typing import Any

from .contracts import month_date, planning_date
from .forecasting import (
    _add_months,
    _adjust_outliers,
    _factors,
    _valid_history,
    candidate_forecasts,
    group_seasonal_factors,
)

MODEL_NAMES = (
    "recent_level",
    "ewma",
    "seasonal_damped",
    "recent_level_adjusted",
    "ewma_adjusted",
    "seasonal_damped_adjusted",
)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:  # source adapters may hand us nonnumeric cached cells
        return None
    return parsed if parsed.is_finite() else None


def _month_stamp(value: Any) -> str | None:
    """Normalize a monthly source key while keeping the public batch strict."""

    if not isinstance(value, str):
        return None
    candidate = value if len(value) == 10 else f"{value}-01" if len(value) == 7 else value
    try:
        return month_date(candidate).isoformat()
    except ValueError:
        return None


def _planning(value: str | date) -> date:
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    stamp = value if len(value) == 10 else f"{value}-01" if len(value) == 7 else value
    return planning_date(stamp)


def _actuals(series: dict[str, Any]) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    for item in series.get("history", []):
        stamp = _month_stamp(item.get("month"))
        quantity = _decimal(item.get("quantity"))
        if stamp is not None and quantity is not None and quantity >= 0:
            values[stamp] = quantity
    return values


def _as_of(series: dict[str, Any], planning: date) -> dict[str, Any]:
    cutoff = planning.year * 12 + planning.month
    history = []
    for item in series.get("history", []):
        stamp = _month_stamp(item.get("month"))
        try:
            current = month_date(stamp)
        except (TypeError, ValueError):
            continue
        if current.year * 12 + current.month < cutoff:
            history.append({**item, "month": stamp})
    available = series.get("parameters", {}).get("category_available_from")
    category = series.get("category") if not available or available < planning.isoformat() else None
    return {**series, "history": history, "category": category}


def _candidate_values(
    series: dict[str, Any],
    planning: date,
    group_factors: dict[tuple[str, str], dict[int, Decimal]] | None = None,
) -> tuple[dict[str, list[Decimal]], int]:
    history = _as_of(series, planning)
    values = _valid_history(history, planning)
    adjusted, _ = _adjust_outliers(values, _factors(history, values, group_factors or {}))
    adjusted_history = {
        **history,
        "history": [
            {"month": stamp.isoformat(), "quantity": format(quantity, "f"), "evidence": []}
            for stamp, quantity in adjusted
        ],
    }
    target_months = [_add_months(planning, offset) for offset in (1, 2, 3)]
    raw = candidate_forecasts(history, planning, target_months, group_factors)
    corrected = candidate_forecasts(adjusted_history, planning, target_months, group_factors)
    all_values = {name: raw[name] for name in ("recent_level", "ewma", "seasonal_damped")}
    all_values.update(
        {f"{name}_adjusted": corrected[name] for name in ("recent_level", "ewma", "seasonal_damped")}
    )
    return all_values, len(values)


def _scale(values: Iterable[Decimal]) -> Decimal:
    values = list(values)
    return sum(values, Decimal(0)) / len(values) if values else Decimal(0)


def _metric(rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    eligible = [
        row for row in rows if row["actual"] is not None and row["predictions"].get(model) is not None
    ]
    series_errors: dict[tuple[str, str, int], list[Decimal]] = defaultdict(list)
    series_bias: dict[tuple[str, str, int], list[Decimal]] = defaultdict(list)
    comparable: dict[tuple[str, str], list[tuple[Decimal, Decimal]]] = defaultdict(list)
    normalized_under: dict[tuple[str, str, int], list[Decimal]] = defaultdict(list)
    for row in eligible:
        actual = Decimal(str(row["actual"]))
        prediction = Decimal(str(row["predictions"][model]))
        scale = Decimal(str(row["training_scale"]))
        error = prediction - actual
        normalized_error = error / scale if scale else None
        if row.get("unit") is not None:
            comparable[(row["supplier"], row["unit"])].append((actual, abs(error)))
        if normalized_error is not None:
            key = (row["supplier"], row["series_id"], row["horizon"])
            series_errors[key].append(abs(normalized_error))
            series_bias[key].append(normalized_error)
            normalized_under[key].append(max(actual - prediction, Decimal(0)) / scale)

    def balanced(values):
        by_series = defaultdict(list)
        by_supplier = defaultdict(list)
        for (supplier, series, _horizon), observations in values.items():
            by_series[(supplier, series)].append(_scale(observations))
        for (supplier, _series), horizons in by_series.items():
            by_supplier[supplier].append(_scale(horizons))
        return by_supplier

    supplier_scores = balanced(series_errors)
    supplier_bias = balanced(series_bias)
    supplier_horizon = defaultdict(list)
    for (supplier, _series, horizon), errors in series_errors.items():
        supplier_horizon[(supplier, horizon)].append(_scale(errors))
    primary_by_supplier = {supplier: float(_scale(scores)) for supplier, scores in supplier_scores.items()}
    bias_by_supplier = {supplier: float(abs(_scale(scores))) for supplier, scores in supplier_bias.items()}
    primary = _scale(_scale(scores) for scores in supplier_scores.values()) if supplier_scores else None
    normalized_bias = (
        _scale(abs(_scale(scores)) for scores in supplier_bias.values()) if supplier_bias else None
    )
    horizon_scores = {
        f"{supplier}:{horizon}": float(_scale(scores))
        for (supplier, horizon), scores in supplier_horizon.items()
    }
    wape_by_unit = {
        f"{supplier}:{unit}": float(sum(errors, Decimal(0)) / sum(actuals, Decimal(0)))
        for (supplier, unit), pairs in comparable.items()
        if (actuals := [actual for actual, _ in pairs]) and sum(actuals, Decimal(0))
        for errors in [[error for _, error in pairs]]
    }
    under_by_supplier = balanced(normalized_under)
    return {
        "model": model,
        "primary_error": float(primary) if primary is not None else None,
        "absolute_normalized_bias": float(normalized_bias) if normalized_bias is not None else None,
        "supplier_error": primary_by_supplier,
        "supplier_bias": bias_by_supplier,
        "supplier_horizon_error": horizon_scores,
        "wape": float(_scale(Decimal(value) for value in wape_by_unit.values())) if wape_by_unit else None,
        "wape_by_unit": wape_by_unit,
        "underforecast": float(_scale(_scale(v) for v in under_by_supplier.values()))
        if under_by_supplier
        else None,
        "evaluated": len(eligible),
        "normalized_evaluated": sum(bool(row["training_scale"]) for row in eligible),
        "coverage": len(eligible) / len(rows) if rows else 0.0,
        "zero_scale": sum(row["training_scale"] == 0 for row in eligible),
        "zero_scale_series": sorted(
            {f"{row['supplier']}:{row['series_id']}" for row in eligible if row["training_scale"] == 0}
        ),
    }


def evaluate_origins(
    series_batch: Iterable[dict[str, Any]],
    origins: Iterable[str | date],
    *,
    phase: str | None = None,
) -> dict[str, Any]:
    """Evaluate all candidates using only observations before each origin."""

    series_batch = list(series_batch)
    origins = list(origins)
    started = perf_counter()
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for raw_origin in origins:
        planning = _planning(raw_origin)
        targets = [_add_months(planning, offset) for offset in (1, 2, 3)]
        as_of_series = [_as_of(series, planning) for series in series_batch]
        group_factors = group_seasonal_factors(as_of_series, planning)
        for series in series_batch:
            as_of = _as_of(series, planning)
            history = _valid_history(as_of, planning)
            actuals = _actuals(series)
            if not history:
                excluded.append(
                    {
                        "series_id": series["series_id"],
                        "origin": planning.isoformat(),
                        "reason": "no_training_history",
                    }
                )
                continue
            predictions, _ = _candidate_values(series, planning, group_factors)
            scale = _scale(quantity for _, quantity in history)
            for horizon, target in enumerate(targets, 1):
                stamp = target.isoformat()
                actual = actuals.get(stamp)
                if actual is None:
                    excluded.append(
                        {
                            "series_id": series["series_id"],
                            "origin": planning.isoformat(),
                            "target_month": stamp,
                            "reason": "missing_actual",
                        }
                    )
                rows.append(
                    {
                        "series_id": series["series_id"],
                        "supplier": series["supplier"],
                        "sku": series["sku"],
                        "unit": series.get("unit"),
                        "origin": planning.isoformat(),
                        "target_month": stamp,
                        "horizon": horizon,
                        "actual": actual,
                        "training_scale": scale,
                        "predictions": {model: values[horizon - 1] for model, values in predictions.items()},
                    }
                )
    models = list(MODEL_NAMES)
    metrics = {model: _metric(rows, model) for model in models}
    selected = select_champion(metrics)
    return {
        "rows": rows,
        "excluded": excluded,
        "metrics": metrics,
        "selected_model": selected,
        "runtime_seconds": perf_counter() - started,
        "origins": [origin.isoformat() if isinstance(origin, date) else origin for origin in origins],
        "phase": phase,
    }


def promotion_gate(
    champion: dict[str, Any], challenger: dict[str, Any], *, minimum_improvement: float = 0.03
) -> dict[str, Any]:
    """Apply the fixed engineering gate before an expensive candidate can ship."""

    base = champion.get("primary_error")
    candidate = challenger.get("primary_error")
    reasons: list[str] = []
    if base is None or candidate is None or base <= 0:
        reasons.append("missing_or_zero_development_error")
        improvement = None
    else:
        improvement = (base - candidate) / base
        if improvement < minimum_improvement:
            reasons.append("development_improvement_below_3_percent")
    if challenger.get("absolute_normalized_bias") is None or champion.get("absolute_normalized_bias") is None:
        reasons.append("missing_bias")
    elif challenger["absolute_normalized_bias"] > champion["absolute_normalized_bias"]:
        reasons.append("absolute_normalized_bias_worse")
    if challenger.get("coverage", 0) < champion.get("coverage", 0):
        reasons.append("coverage_reduced")
    base_breakdown = champion.get("supplier_horizon_error", {})
    candidate_breakdown = challenger.get("supplier_horizon_error", {})
    for key, old in base_breakdown.items():
        new = candidate_breakdown.get(key)
        if new is None:
            reasons.append(f"supplier_horizon_coverage_reduced:{key}")
        elif new > old * 1.05:
            reasons.append(f"supplier_horizon_degradation:{key}")
    if challenger.get("evaluated", 0) < champion.get("evaluated", 0):
        reasons.append("evaluated_coverage_reduced")
    return {"promote": not reasons, "improvement": improvement, "reasons": reasons}


def select_champion(metrics: dict[str, dict[str, Any]]) -> str | None:
    """Select the cheapest candidate satisfying the fixed gate over the level baseline."""

    available = [name for name, value in metrics.items() if value.get("primary_error") is not None]
    if not available:
        return None
    baseline = metrics.get("recent_level") or metrics[available[0]]
    # Statistical candidates are inexpensive; use the gate to avoid selecting a
    # noisier seasonal model merely because of one pooled aggregate score.
    for name in sorted(available, key=lambda n: (metrics[n]["primary_error"], MODEL_NAMES.index(n))):
        if name in metrics and name in available and promotion_gate(baseline, metrics[name])["promote"]:
            return name
    return "recent_level" if "recent_level" in available else available[0]


def evaluate(
    series_batch: Iterable[dict[str, Any]],
    development_origins: Iterable[str | date],
    retrospective_origins: Iterable[str | date] | None = None,
) -> dict[str, Any]:
    series_batch = list(series_batch)
    development = evaluate_origins(series_batch, development_origins, phase="development")
    selected = development["selected_model"]
    retrospective = (
        evaluate_origins(series_batch, retrospective_origins, phase="retrospective")
        if retrospective_origins is not None
        else None
    )
    retrospective_selected = (
        retrospective["metrics"].get(selected) if retrospective is not None and selected else None
    )
    return {
        "development": development,
        "retrospective": retrospective,
        "selection_frozen": selected,
        "retrospective_selected": retrospective_selected,
        "comparison_is_retrospective": retrospective is not None,
        "llm_cost": None,
    }
