"""Evaluator arithmetic and mechanical oracles; not an application policy."""

from decimal import ROUND_CEILING, Decimal

from evaluation.contracts import month, quantity


def forecast_metrics(pairs):
    pairs = [(quantity(a), quantity(p)) for a, p in pairs]
    total = sum((a for a, _ in pairs), Decimal(0))
    absolute = sum((abs(p - a) for a, p in pairs), Decimal(0))
    signed = sum((p - a for a, p in pairs), Decimal(0))
    return {
        "count": len(pairs),
        "actual_total": str(total),
        "wape_pct": str(absolute / total * 100) if total else None,
        "bias_pct": str(signed / total * 100) if total else None,
        "mae": str(absolute / len(pairs)) if pairs else None,
        "underforecast": str(sum((max(a - p, 0) for a, p in pairs), Decimal(0))) if pairs else None,
    }


def order_oracle(coverage, stock, transit, multiple, minimum="0"):
    """Hand-example oracle used only by checks, never to generate predictions."""
    coverage, stock, transit, multiple, minimum = map(quantity, (coverage, stock, transit, multiple, minimum))
    if not multiple:
        raise ValueError("Positive multiple required")
    need = max(coverage - stock - transit, Decimal(0))
    return (
        (max(need, minimum) / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple
        if need
        else Decimal(0)
    )


def replay(initial_stock, periods, receipts):
    """Recorded-condition mechanics: initialize once; stop at the first missing month.

    Callers must establish common scope, stock timing and observed deliveries before use.
    No ordering policy is inferred and receipts are applied exactly once by unique ID.
    """
    stock = quantity(initial_stock)
    pending = {}
    for receipt in receipts:
        if receipt["id"] in pending:
            raise ValueError("Duplicate receipt")
        pending[receipt["id"]] = (month(receipt["month"]), quantity(receipt["quantity"]))
    stocks, used = [], set()
    demand_total = fulfilled_total = Decimal(0)
    previous = None
    for period in periods:
        current = month(period["month"])
        if period["demand"] is None or (previous is not None and current != previous + 1):
            break
        if previous is None and any(due < current for due, _ in pending.values()):
            raise ValueError("Receipt predates initial stock")
        previous = current
        demand = quantity(period["demand"])
        arrivals = sum(
            (q for key, (due, q) in pending.items() if due == current and key not in used), Decimal(0)
        )
        used.update(key for key, (due, _) in pending.items() if due == current)
        fulfilled = min(stock + arrivals, demand)
        stock += arrivals - fulfilled
        stocks.append(stock)
        demand_total += demand
        fulfilled_total += fulfilled
    return {
        "evaluated": len(stocks),
        "skipped": len(periods) - len(stocks),
        "mean_month_end_stock": str(sum(stocks) / len(stocks)) if stocks else None,
        "final_stock": str(stock) if stocks else None,
        "unmet_recorded_demand": str(demand_total - fulfilled_total) if stocks else None,
        "fulfilled_recorded_ratio": str(fulfilled_total / demand_total) if demand_total else None,
        "pending_receipts": sorted(set(pending) - used),
    }
