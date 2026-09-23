"""Rolling-origin evaluation of the real calculator on identical historical targets."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from replenishment.metrics import forecast_metrics
from replenishment.planning import calculator
from replenishment.planning.models import PlanningRequest

MODELS = ("backend_raw", "backend_bulk", "mean28", "weekly_naive")
START = date(2025, 1, 1)
END = date(2026, 8, 31)
ORIGINS = tuple(date(2025, month, 1) for month in range(7, 13)) + tuple(
    date(2026, month, 1) for month in range(1, 9)
)


def _scales(history, horizon):
    # Consecutive non-overlapping horizon totals, ending immediately before origin.
    # Daily denominators would not match an aggregated 7/28-day forecast error.
    blocks = [sum(history[end - horizon:end], Decimal(0))
              for end in range(len(history), horizon - 1, -horizon)][::-1]
    errors = [float(right - left) for left, right in pairwise(blocks)]
    if not errors or not any(errors):
        return None, None
    return sum(abs(error) for error in errors) / len(errors), sum(e * e for e in errors) / len(errors)


def evaluate_series(series, *, origins, horizons=(7, 28), models=MODELS,
                    min_history_days=90, lookback_days=56):
    """Evaluate fixed policies; future targets are never supplied to a forecast call."""
    origins, horizons, models = tuple(origins), tuple(horizons), tuple(models)
    if (not origins or len(set(origins)) != len(origins) or not horizons
            or len(set(horizons)) != len(horizons) or not models or len(set(models)) != len(models)):
        raise ValueError("Origins, horizons and models must be nonempty and unique")
    if any(model not in MODELS for model in models):
        raise ValueError("Unknown model")
    if any(type(h) is not int or not 1 <= h <= 365 for h in horizons):
        raise ValueError("Horizons must be integers between 1 and 365")
    if type(min_history_days) is not int or min_history_days < 0 or not 1 <= lookback_days <= 3660:
        raise ValueError("Invalid history configuration")
    if any(origin.year not in (2025, 2026) for origin in origins):
        raise ValueError("This protocol labels 2025 development and 2026 retrospective only")
    predictions, seen = [], set()
    for item in series:
        identity = tuple(item[key] for key in ("supplier", "warehouse", "unit", "sku"))
        if identity in seen:
            raise ValueError("Duplicate supplier/warehouse/unit/SKU series")
        seen.add(identity)
        start, end = item["start"], item["end"]
        if start > end:
            raise ValueError("Invalid extraction coverage")
        for origin in origins:
            if origin <= start or origin + timedelta(days=max(horizons) - 1) > end:
                raise ValueError("Forecast horizon is outside complete extract coverage")
        daily = [Decimal(0)] * ((end - start).days + 1)
        sales = sorted(item["sales"], key=lambda sale: (sale["day"], sale["document"]))
        first = None
        for sale in sales:
            quantity = Decimal(str(sale["quantity"]))
            if not quantity.is_finite() or quantity < 0 or not start <= sale["day"] <= end:
                raise ValueError("Invalid eligible sales quantity or date")
            daily[(sale["day"] - start).days] += quantity
            if quantity > 0 and first is None:
                first = sale["day"]
        for origin in sorted(origins):
            if first is None or first >= origin or first > origin - timedelta(days=min_history_days):
                continue
            offset = (origin - start).days
            history = daily[:offset]
            if len(history) < 7:
                raise ValueError("At least seven historical days are required for weekly comparisons")
            active_weeks = sum(sum(history[max(0, offset - 7 * (week + 1)):offset - 7 * week]) > 0
                               for week in range(min(8, offset // 7)))
            segment = "regular" if active_weeks >= 4 else "intermittent"
            history_start = max(start, origin - timedelta(days=lookback_days))
            prior_sales = [sale for sale in sales if history_start <= sale["day"] < origin]
            for horizon in horizons:
                actual = float(sum(daily[offset:offset + horizon], Decimal(0)))
                mae_scale, mse_scale = _scales(history, horizon)
                for model in models:
                    if model == "mean28":
                        recent = history[-28:]
                        forecast = float(sum(recent, Decimal(0)) / len(recent) * horizon)
                    elif model == "weekly_naive":
                        weekly = (history[-7 + index % 7] for index in range(horizon))
                        forecast = float(sum(weekly, Decimal(0)))
                    else:
                        request = PlanningRequest.model_validate({
                            "planning_date": origin, "lead_time_days": 0, "review_days": horizon,
                            "exclude_bulk": model == "backend_bulk", "rows": [{
                                "row_id": "evaluation", "supplier": item["supplier"], "sku": item["sku"],
                                "name": item.get("name", ""), "stock_unit": item["unit"],
                                "warehouse": item["warehouse"], "purchase_unit": item["unit"],
                                "free_stock": "0", "stock_as_of": origin, "stock_scope_confirmed": True,
                                "incoming_complete": True, "constraints_confirmed": True,
                                "stock_per_purchase_unit": "1", "minimum_order": "0", "order_multiple": "1",
                                "history_start": history_start, "history_end": origin - timedelta(days=1),
                                "sales": prior_sales, "basis": "synthetic",
                                "notes": ["Synthetic stock/lead inputs isolate forecast quantity."],
                            }],
                        })
                        result = calculator.calculate(request).rows[0]
                        if result.forecast_demand is None or result.status == "needs_input":
                            raise ValueError(f"Calculator failed for {identity}: {result.missing_inputs}")
                        forecast = float(result.forecast_demand)
                    predictions.append({
                        "supplier": item["supplier"], "warehouse": item["warehouse"], "unit": item["unit"],
                        "sku": item["sku"], "origin": origin.isoformat(), "horizon": horizon,
                        "phase": "development_2025" if origin.year == 2025 else "retrospective_2026",
                        "segment": segment, "model_id": model, "actual": actual, "forecast": forecast,
                        "mae_scale": mae_scale, "mse_scale": mse_scale,
                    })
    return predictions


def summarize(predictions, *, monthly=False):
    groups = defaultdict(list)
    for row in predictions:
        base = tuple(row[key] for key in ("phase", "supplier", "warehouse", "unit", "horizon", "model_id"))
        if monthly:
            base += (row["origin"],)
        for segment in ("all", row["segment"]):
            groups[(*base, segment)].append(row)
    metrics = []
    fields = ("phase", "supplier", "warehouse", "unit", "horizon", "model")
    if monthly:
        fields += ("origin",)
    fields += ("segment",)
    for key, rows in sorted(groups.items()):
        metric = dict(zip(fields, key, strict=True))
        metric.update(forecast_metrics(
            [row["actual"] for row in rows], [row["forecast"] for row in rows],
            mae_scales=[row["mae_scale"] for row in rows], mse_scales=[row["mse_scale"] for row in rows],
        ))
        metric.update(sku_count=len({row["sku"] for row in rows}),
                      origin_count=len({row["origin"] for row in rows}))
        metrics.append(metric)
    return metrics
