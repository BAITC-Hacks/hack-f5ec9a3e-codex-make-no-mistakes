"""Small, deterministic monthly forecasting core.

All model state is derived from the supplied history.  There is no clock,
database, network or random seed hidden in this module, which makes the same
calculation usable in a replay and in the production boundary.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from statistics import median
from typing import Any

from .contracts import month_date, planning_date

ALPHA = Decimal("0.3")
TREND_DAMPING = Decimal("0.8")
ZERO = Decimal(0)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _number(value: Decimal) -> str:
    """Stable decimal-string representation for JSON and SQL Numeric values."""

    if not value.is_finite() or value < 0:
        raise ValueError("Forecast quantity must be finite and nonnegative")
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + 16)
        value = value.quantize(Decimal("0.000000000001"))
    rendered = format(value, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _mean(values: Iterable[Decimal]) -> Decimal:
    values = list(values)
    return sum(values, ZERO) / len(values) if values else ZERO


def _month_number(stamp: str) -> int:
    return month_date(stamp).year * 12 + month_date(stamp).month


def _add_months(stamp: date, months: int) -> date:
    index = stamp.year * 12 + stamp.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _valid_history(series: dict[str, Any], planning: date) -> list[tuple[date, Decimal]]:
    planning_index = planning.year * 12 + planning.month
    values: list[tuple[date, Decimal]] = []
    for item in series.get("history", []):
        stamp = item.get("month")
        if not isinstance(stamp, str):
            continue
        try:
            when = month_date(stamp)
        except ValueError:
            continue
        if when.year * 12 + when.month >= planning_index:
            continue
        quantity = _decimal(item.get("quantity"))
        if quantity is not None and quantity >= ZERO:
            values.append((when, quantity))
    return sorted(values)


def _group_key(series: dict[str, Any]) -> tuple[str, str]:
    category = series.get("category")
    return (
        ("category", f"{series['supplier']}:{category}")
        if isinstance(category, str) and category.strip()
        else ("supplier", series["supplier"])
    )


def group_seasonal_factors(
    series_batch: Iterable[dict[str, Any]], planning: date | str
) -> dict[tuple[str, str], dict[int, Decimal]]:
    """Build normalized comparable month patterns without pooling quantities.

    Each SKU contributes a unitless pattern first; raw quantities from a large
    SKU therefore cannot dominate the supplier/category pattern.
    """

    if isinstance(planning, str):
        planning = planning_date(planning)
    grouped: dict[tuple[str, str], dict[int, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    for series in series_batch:
        values = _valid_history(series, planning)
        level = _mean(quantity for _, quantity in values)
        if not values or not level:
            continue
        own = {month: _mean(items) / level for month, items in _months(values).items()}
        average = _mean(own.values()) or Decimal(1)
        for month, factor in own.items():
            grouped[_group_key(series)][month].append(factor / average)
    result: dict[tuple[str, str], dict[int, Decimal]] = {}
    for key, months in grouped.items():
        factors = {month: _mean(values) for month, values in months.items()}
        average = _mean(factors.values()) if factors else Decimal(1)
        result[key] = {
            month: (factors.get(month, Decimal(1)) / average if average else Decimal(1))
            for month in range(1, 13)
        }
    return result


def _months(values: list[tuple[date, Decimal]]) -> dict[int, list[Decimal]]:
    grouped: dict[int, list[Decimal]] = defaultdict(list)
    for when, quantity in values:
        grouped[when.month].append(quantity)
    return grouped


def _factors(
    series: dict[str, Any],
    values: list[tuple[date, Decimal]],
    group_factors: dict[tuple[str, str], dict[int, Decimal]],
) -> dict[int, Decimal]:
    own = _months(values)
    level = _mean(quantity for _, quantity in values)
    group = group_factors.get(_group_key(series), {})
    if not level:
        return {month: Decimal(1) for month in range(1, 13)}
    own_factors = {month: _mean(items) / level for month, items in own.items()}
    raw = {
        month: (
            (
                own_factors.get(month, group.get(month, Decimal(1))) * len(own.get(month, ()))
                + group.get(month, Decimal(1)) * 4
            )
            / (len(own.get(month, ())) + 4)
            if month in own_factors
            else group.get(month, Decimal(1))
        )
        for month in range(1, 13)
    }
    average = _mean(raw.values()) or Decimal(1)
    return {month: factor / average for month, factor in raw.items()}


def _adjust_outliers(
    values: list[tuple[date, Decimal]], factors: dict[int, Decimal] | None = None
) -> tuple[list[tuple[date, Decimal]], list[str]]:
    """Flag isolated positive residuals; retain repeated seasonal peaks and growth.

    Local interpolation removes trend before the robust residual check. Missing
    neighbors and the latest observation cannot establish an isolated event.
    """
    if len(values) < 4:
        return values, []
    counts = _months(values)
    factors = {m: factor for m, factor in (factors or {}).items() if len(counts.get(m, [])) >= 2}
    normalized = [q / (factors.get(d.month) or Decimal(1)) for d, q in values]
    residuals = [
        normalized[i] - (normalized[i - 1] + normalized[i + 1]) / 2 for i in range(1, len(values) - 1)
    ]
    center = median(residuals)
    # Few monthly residuals make MAD unstable; cap the candidate threshold at
    # three historical median levels. Promotion still requires a backtest win.
    level = median(normalized)
    threshold = max(level * 2, min(level * 3, median(abs(r - center) for r in residuals) * 5))
    adjusted, flags = list(values), []
    for i in range(1, len(values) - 1):
        when, quantity = values[i]
        if values[i - 1][0] != _add_months(when, -1) or values[i + 1][0] != _add_months(when, 1):
            continue
        expected = (normalized[i - 1] + normalized[i + 1]) / 2
        repeated = any(d.month == when.month and d.year != when.year and q >= quantity / 2 for d, q in values)
        if (
            not repeated
            and normalized[i] - expected > threshold
            and normalized[i] > 3 * max(normalized[i - 1], normalized[i + 1])
        ):
            adjusted[i] = (when, max(expected, ZERO) * (factors.get(when.month) or Decimal(1)))
            flags.append(when.isoformat())
    return adjusted, flags


def _history_findings(series: dict[str, Any], planning: date) -> dict[str, Any]:
    """Preserve source evidence and explain observations excluded from fitting."""

    missing: list[str] = []
    negative: list[str] = []
    invalid: list[str] = []
    evidence: list[Any] = []
    cutoff = planning.year * 12 + planning.month
    for item in series.get("history", []):
        stamp = item.get("month")
        normalized = (
            stamp
            if isinstance(stamp, str) and len(stamp) == 10
            else (f"{stamp}-01" if isinstance(stamp, str) and len(stamp) == 7 else stamp)
        )
        try:
            when = month_date(normalized)
        except (TypeError, ValueError):
            if stamp is not None:
                invalid.append(str(stamp))
            continue
        if when.year * 12 + when.month >= cutoff:
            continue
        evidence.extend(item.get("evidence") or [])
        quantity = _decimal(item.get("quantity"))
        if item.get("quantity") is None:
            missing.append(normalized)
        elif quantity is None:
            invalid.append(normalized)
        elif quantity < ZERO:
            negative.append(normalized)
    return {
        "evidence": evidence,
        "assumptions": list(series.get("assumptions") or []),
        "excluded": {"missing_months": missing, "negative_months": negative, "invalid": invalid},
        "availability_warning": "stockout_duration_unverified",
        "customer_concentration": "unverified_customer_ids_absent",
    }


def _ewma(values: Iterable[Decimal]) -> Decimal:
    result: Decimal | None = None
    for quantity in values:
        result = quantity if result is None else ALPHA * quantity + (Decimal(1) - ALPHA) * result
    return result or ZERO


def _trend(values: list[tuple[date, Decimal]], factors: dict[int, Decimal]) -> Decimal:
    adjusted: list[tuple[date, Decimal]] = [
        (when, quantity / (factors.get(when.month) or Decimal(1))) for when, quantity in values
    ]
    tail: list[tuple[date, Decimal]] = []
    for item in reversed(adjusted):
        if tail and _month_number(item[0].isoformat()) + 1 != _month_number(tail[-1][0].isoformat()):
            break
        tail.append(item)
        if len(tail) == 4:
            break
    tail.reverse()
    if len(tail) < 2:
        return ZERO
    changes = [tail[index][1] - tail[index - 1][1] for index in range(1, len(tail))]
    return _mean(changes)


def candidate_forecasts(
    series: dict[str, Any],
    planning: date | str,
    target_months: Iterable[date] | None = None,
    group_factors: dict[tuple[str, str], dict[int, Decimal]] | None = None,
) -> dict[str, list[Decimal]]:
    """Return all fixed statistical candidates for the requested target months."""

    if isinstance(planning, str):
        planning = planning_date(planning)
    target_months = list(target_months or (_add_months(planning, offset) for offset in (1, 2, 3)))
    target_months = [
        month_date(item) if isinstance(item, str) else date(item.year, item.month, 1)
        for item in target_months
    ]
    values = _valid_history(series, planning)
    if not values:
        return {name: [] for name in ("recent_level", "ewma", "seasonal_damped")}
    group_factors = group_factors or {}
    factors = _factors(series, values, group_factors)
    de_seasonalized = [quantity / (factors.get(when.month) or Decimal(1)) for when, quantity in values]
    recent = _mean(quantity for _, quantity in values[-3:])
    ewma = _ewma(quantity for _, quantity in values)
    base = _ewma(de_seasonalized)
    trend = _trend(values, factors)
    seasonal: list[Decimal] = []
    for target in target_months:
        growth = ZERO
        damping = Decimal(1)
        for _ in range((target.year * 12 + target.month) - (values[-1][0].year * 12 + values[-1][0].month)):
            growth += damping * trend
            damping *= TREND_DAMPING
        seasonal.append(max(base + growth, ZERO) * (factors.get(target.month) or Decimal(1)))
    return {
        "recent_level": [recent for _ in target_months],
        "ewma": [ewma if len(values) >= 4 else recent for _ in target_months],
        "seasonal_damped": seasonal if len(values) >= 4 else [recent for _ in target_months],
    }


def _forecast_rows(
    series: dict[str, Any],
    planning: date,
    targets: list[date],
    group_factors: dict[tuple[str, str], dict[int, Decimal]],
    model: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values = _valid_history(series, planning)
    adjusted, anomalies = _adjust_outliers(values, _factors(series, values, group_factors))
    raw_candidates = candidate_forecasts(series, planning, targets, group_factors)
    adjusted_series = {
        **series,
        "history": [
            {"month": when.isoformat(), "quantity": _number(quantity), "evidence": []}
            for when, quantity in adjusted
        ],
    }
    adjusted_candidates = candidate_forecasts(adjusted_series, planning, targets, group_factors)
    usable = len(values)
    findings = _history_findings(series, planning)
    if not values:
        rows = [
            {
                "series_id": series["series_id"],
                "supplier": series["supplier"],
                "sku": series["sku"],
                "scope": series["scope"],
                "unit": series.get("unit"),
                "target_month": target.isoformat(),
                "quantity": None,
                "model": "none",
                "status": "insufficient_data",
                "explanation": {
                    "valid_observations": 0,
                    "reason": "no_usable_history",
                    **findings,
                },
            }
            for target in targets
        ]
        return rows, {"anomalies": [], "valid_observations": 0}
    selected_model = model.removesuffix("_adjusted") if usable >= 4 else "recent_level"
    adjusted_variant = model.endswith("_adjusted") and usable >= 4
    selected = adjusted_candidates if adjusted_variant else raw_candidates
    factors = _factors(series, values, group_factors)
    rows = []
    for index, target in enumerate(targets):
        raw = raw_candidates[selected_model][index]
        adjusted_quantity = adjusted_candidates[selected_model][index]
        quantity = selected[selected_model][index]
        rows.append(
            {
                "series_id": series["series_id"],
                "supplier": series["supplier"],
                "sku": series["sku"],
                "scope": series["scope"],
                "unit": series.get("unit"),
                "target_month": target.isoformat(),
                "quantity": _number(max(quantity, ZERO)),
                "model": f"{selected_model}_adjusted" if adjusted_variant else selected_model,
                "status": "ok",
                "explanation": {
                    "valid_observations": usable,
                    "history_through": values[-1][0].isoformat(),
                    "candidates": {name: _number(chosen[index]) for name, chosen in raw_candidates.items()},
                    "adjusted_candidates": {
                        name: _number(chosen[index]) for name, chosen in adjusted_candidates.items()
                    },
                    "raw_quantity": _number(max(raw, ZERO)),
                    "adjusted_quantity": _number(max(adjusted_quantity, ZERO)),
                    "seasonal_factor": _number(factors.get(target.month, Decimal(1))),
                    "anomalies": anomalies,
                    "limitations": (["short_history_level_fallback"] if usable < 4 else []),
                    **findings,
                },
            }
        )
    return rows, {"anomalies": anomalies, "valid_observations": usable}


def forecast_series(
    series: dict[str, Any],
    planning: date | str,
    *,
    group_factors: dict[tuple[str, str], dict[int, Decimal]] | None = None,
    include_bridge: bool = False,
    model: str = "recent_level",
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if isinstance(planning, str):
        planning = planning_date(planning)
    targets = [_add_months(planning, offset) for offset in (1, 2, 3)]
    if model.removesuffix("_adjusted") not in {"recent_level", "ewma", "seasonal_damped"}:
        raise ValueError("Unsupported statistical model")
    rows, _ = _forecast_rows(series, planning, targets, group_factors or {}, model)
    bridge = None
    if include_bridge:
        bridge_targets = [date(planning.year, planning.month, 1)]
        bridge, _ = _forecast_rows(series, planning, bridge_targets, group_factors or {}, model)
        bridge = {**bridge[0], "basis": "full_month"}
    return rows, bridge


def forecast_batch(
    series_batch: Iterable[dict[str, Any]],
    planning: date | str,
    *,
    include_bridge: bool = False,
    model: str = "recent_level",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    series_batch = list(series_batch)
    if isinstance(planning, str):
        planning = planning_date(planning)
    factors = group_seasonal_factors(series_batch, planning)
    forecasts: list[dict[str, Any]] = []
    bridges: list[dict[str, Any]] = []
    for series in series_batch:
        rows, bridge = forecast_series(
            series, planning, group_factors=factors, include_bridge=include_bridge, model=model
        )
        forecasts.extend(rows)
        if bridge is not None:
            bridges.append(bridge)
    return forecasts, bridges
