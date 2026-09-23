"""Historical evidence check only; purchasing replay awaits verified policy and timing."""

from collections import Counter, defaultdict
from datetime import date

from replenishment.calculation.evaluation import _decimal
from replenishment.calculation.forecasting import _add_months

PERIODS = (("2026-01-01", "2026-04-01"), ("2026-05-01", "2026-08-01"))
PURCHASING_INPUTS = [
    "historical_purchasing_inputs_and_policy",
    "historical_open_orders_and_deliveries_including_verified_zero",
    "supported_recommendation_arrival_timing",
]


def _observation(series, month):
    rows = [row for row in series.get("history", []) if row["month"] == month]
    values = [_decimal(row.get("quantity")) for row in rows]
    quantity = values[0] if values and all(v == values[0] for v in values) else None
    if quantity is not None and quantity < 0:
        quantity = None
    return {"month": month, "quantity": quantity, "evidence": [e for r in rows for e in r["evidence"]]}


def coverage_case(sales, stocks, start, end, interpretation):
    """Align boundaries without treating an unknown cell as a zero balance."""
    opening = date.fromisoformat(start)
    ending = date.fromisoformat(end)
    first = opening if interpretation == "opening" else _add_months(opening, -1)
    last = _add_months(ending, 1) if interpretation == "opening" else ending
    missing = []
    if len(stocks) != 1:
        missing.append("unique_stock_match_by_supplier_and_exact_sku")
    stock = stocks[0] if len(stocks) == 1 else {}
    if not sales.get("unit") or sales["unit"] != stock.get("unit"):
        missing.append("compatible_verified_units")
    # These workbook labels identify tables, not a verified warehouse/availability scope.
    missing.extend(["verified_common_stock_and_sales_scope", "starting_available_stock_basis"])
    begin = _observation(stock, first.isoformat())
    finish = _observation(stock, last.isoformat())
    actuals = [_observation(sales, _add_months(opening, offset).isoformat()) for offset in range(4)]
    for name, observation in [("starting_stock", begin), ("ending_stock", finish)]:
        if observation["quantity"] is None:
            missing.append(f"{name}:{observation['month']}")
    missing.extend(f"recorded_sales:{r['month']}" for r in actuals if r["quantity"] is None)
    if sales["supplier"] == "systeme":
        missing.append("verified_stock_balance_timing")
    missing.extend(PURCHASING_INPUTS)
    return {
        "series_id": sales["series_id"],
        "supplier": sales["supplier"],
        "sku": sales["sku"],
        "unit": sales.get("unit"),
        "period_start": start,
        "period_end_month": end,
        "interpretation": interpretation,
        "starting_stock": begin,
        "ending_stock": finish,
        "recorded_sales": actuals,
        "missing_inputs": missing,
        "eligible": False,
        "leftover_reduction_percent": None,
        "unmet_recorded_sales": None,
    }


def leftovers_comparison(batch, stock_batch=None):
    """No verified purchasing inputs exist in the current workbook/batch contract."""
    index = defaultdict(list)
    for stock in (stock_batch or {}).get("series", []):
        index[(stock["supplier"], stock["sku"])].append(stock)
    excluded, exploratory = [], []
    for sales in batch["series"]:
        stocks = index[(sales["supplier"], sales["sku"])]
        for start, end in PERIODS:
            case = coverage_case(sales, stocks, start, end, "opening")
            excluded.append(case)
            if sales["supplier"] == "systeme":
                # Keep the primary exclusion neutral about Systeme's unknown timing.
                excluded[-1] = {
                    **case,
                    "interpretation": "unverified",
                    "starting_stock": None,
                    "ending_stock": None,
                    "missing_inputs": [
                        m
                        for m in case["missing_inputs"]
                        if not m.startswith(("starting_stock:", "ending_stock:"))
                    ],
                }
                exploratory.extend(
                    [
                        {**case, "exploratory_only": True},
                        {**coverage_case(sales, stocks, start, end, "closing"), "exploratory_only": True},
                    ]
                )
    counts = Counter(reason for case in excluded for reason in case["missing_inputs"])
    return {
        "status": "not_measured",
        "message": "Leftover reduction: not measured.",
        "evidence_mode": "verified_only",
        "periods": [{"start": start, "end_month": end} for start, end in PERIODS],
        "source_selection": batch["source_selection"] + (stock_batch or {}).get("source_selection", []),
        "eligible_cases": [],
        "eligible_count": 0,
        "excluded_cases": excluded,
        "excluded_count": len(excluded),
        "missing_input_counts": dict(sorted(counts.items())),
        "exploratory_data_coverage": exploratory,
        "measurement_contract": {
            "remaining_stock": "starting available stock + supported arrivals - same recorded sales",
            "per_product_reduction_percent": (
                "100 * (company ending stock - remaining stock) / company ending stock"
            ),
            "requirements": [
                "Verified matching supplier, exact SKU, units and scope; both stock boundaries.",
                "Historical purchasing inputs, confirmed policy and supported arrival timing before scoring.",
                "Report unmet recorded sales alongside each product; any unmet sales forbids improvement.",
                "Zero company ending stock has undefined percentage; never pool incompatible units.",
            ],
        },
        "limitations": [
            "Monthly stock cannot establish exact stockout duration or lost demand.",
            "Systeme opening and closing interpretations are exploratory only.",
            "Purchases are never inferred from stock changes; missing deliveries are not zero.",
            "Purchasing replay remains blocked pending verified inputs and confirmed historical policy.",
        ],
    }
