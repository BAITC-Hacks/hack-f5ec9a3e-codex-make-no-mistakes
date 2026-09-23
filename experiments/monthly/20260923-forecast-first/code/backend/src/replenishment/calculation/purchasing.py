"""Deterministic supplier draft arithmetic for canonical calculation inputs."""

from __future__ import annotations

import calendar
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
QUANTUM = Decimal("0.000000000001")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None


def _number(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _month(value: Any) -> date | None:
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:7] + "-01")
        except ValueError:
            return None
    return None


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _forecast_rows(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if "series_id" in value:
            return [dict(value)]
        result = []
        for series_id, forecasts in value.items():
            if isinstance(forecasts, Mapping):
                item = dict(forecasts)
                item.setdefault("series_id", series_id)
                result.append(item)
            elif isinstance(forecasts, Sequence) and not isinstance(forecasts, (str, bytes)):
                for item in forecasts:
                    item = dict(item)
                    item.setdefault("series_id", series_id)
                    result.append(item)
            else:
                result.append({"series_id": series_id, "quantity": forecasts})
        return result
    return [dict(item) for item in value]


def _series_forecasts(rows: Sequence[Mapping[str, Any]], series_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if row.get("series_id") == series_id]


def _identity_matches(row: Mapping[str, Any], series: Mapping[str, Any]) -> bool:
    return all(row.get(key) == series.get(key) for key in ("supplier", "sku", "scope", "unit"))


def _rules(
    series: Mapping[str, Any], purchase_unit: str | None, blockers: list[str]
) -> tuple[Decimal | None, Decimal | None, list[dict[str, Any]]]:
    minimum = multiple = None
    evidence = []
    if series.get("quantity_rules") is None:
        blockers.append("unknown_quantity_rules")
    for rule in series.get("quantity_rules") or []:
        value = _decimal(rule.get("value"))
        evidence.extend(rule.get("evidence") or [])
        kind = rule.get("kind")
        if value is None:
            if rule.get("interpretation_confirmed") and kind in {"minimum_shipment", "order_multiple"}:
                blockers.append("invalid_quantity_rule")
            continue
        if value < ZERO or (kind == "order_multiple" and value == ZERO):
            blockers.append("invalid_quantity_rule")
            continue
        if not rule.get("interpretation_confirmed"):
            blockers.append("quantity_rule_unconfirmed")
            continue
        rule_unit = rule.get("unit")
        if rule_unit is None or rule_unit != purchase_unit:
            blockers.append("quantity_rule_unit_mismatch")
            continue
        if kind == "minimum_shipment":
            if minimum is not None and minimum != value:
                blockers.append("conflicting_minimum")
            minimum = value
        elif kind == "order_multiple":
            if multiple is not None and multiple != value:
                blockers.append("conflicting_multiple")
            multiple = value
    return minimum, multiple, evidence


def _dedupe_shipments(
    series: Mapping[str, Any], coverage_end: date, blockers: list[str]
) -> tuple[Decimal, list[dict[str, Any]], list[dict[str, Any]]]:
    incoming = ZERO
    arrivals: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    shipments = series.get("shipments")
    if shipments is None:
        blockers.append("unknown_shipments")
        return incoming, arrivals, evidence
    for shipment in shipments:
        identity = str(shipment.get("id", shipment.get("shipment_id", "")))
        identity = identity or repr(sorted(shipment.items()))
        if identity in seen:
            if {k: shipment.get(k) for k in ("quantity", "expected_on", "scope", "unit")} != {
                k: seen[identity].get(k) for k in ("quantity", "expected_on", "scope", "unit")
            }:
                blockers.append("conflicting_duplicate_shipment")
            continue
        seen[identity] = dict(shipment)
        qty = _decimal(shipment.get("quantity"))
        due = _parse_date(shipment.get("expected_on", shipment.get("due")))
        evidence.extend(shipment.get("evidence") or [])
        if qty is None:
            blockers.append("unknown_transit_quantity")
            continue
        if qty < ZERO:
            blockers.append("negative_transit_quantity")
            continue
        if shipment.get("scope") != series.get("scope"):
            arrivals.append(
                {
                    "id": identity,
                    "quantity": _number(qty),
                    "expected_on": due.isoformat() if due else None,
                    "included": False,
                    "reason": "scope_mismatch",
                }
            )
            continue
        if shipment.get("unit") is None or shipment.get("unit") != series.get("unit"):
            blockers.append("transit_unit_mismatch")
            continue
        if qty == ZERO:
            continue
        if due is None:
            blockers.append("undated_transit")
            arrivals.append(
                {
                    "id": identity,
                    "quantity": _number(qty),
                    "expected_on": None,
                    "included": False,
                    "reason": "missing_arrival_date",
                }
            )
        elif due < _parse_date(series.get("planning_date")):
            blockers.append("overdue_transit_receipt_unverified")
            arrivals.append(
                {
                    "id": identity,
                    "quantity": _number(qty),
                    "expected_on": due.isoformat(),
                    "included": False,
                    "reason": "receipt_unverified",
                }
            )
        elif due >= coverage_end:
            arrivals.append(
                {
                    "id": identity,
                    "quantity": _number(qty),
                    "expected_on": due.isoformat(),
                    "included": False,
                    "reason": "outside_coverage",
                }
            )
        else:
            incoming += qty
            arrivals.append(
                {"id": identity, "quantity": _number(qty), "expected_on": due.isoformat(), "included": True}
            )
    return incoming, arrivals, evidence


def _demand_schedule(
    planning: date, coverage_end: date, bridge: Decimal, forecasts: Mapping[date, Decimal]
) -> dict[date, Decimal]:
    result: dict[date, Decimal] = {}
    current_end = date(planning.year, planning.month, calendar.monthrange(planning.year, planning.month)[1])
    if bridge != ZERO and planning <= current_end:
        days = (current_end - planning).days + 1
        for offset in range(days):
            result[planning + timedelta(days=offset)] = bridge / Decimal(days)
    for month, quantity in forecasts.items():
        end = _next_month(month)
        days = (end - month).days
        for offset in range(days):
            day = month + timedelta(days=offset)
            if planning <= day < coverage_end:
                result[day] = result.get(day, ZERO) + quantity / Decimal(days)
    return result


def _line_for_series(
    series: Mapping[str, Any],
    forecasts: Sequence[Mapping[str, Any]],
    bridge_rows: Sequence[Mapping[str, Any]],
    planning: date,
) -> dict[str, Any]:
    series_id = str(series.get("series_id"))
    target_start = _next_month(date(planning.year, planning.month, 1))
    targets = [target_start]
    for _ in range(2):
        targets.append(_next_month(targets[-1]))
    coverage_end = _next_month(targets[-1])
    working_series = dict(series)
    working_series["planning_date"] = planning.isoformat()
    blockers: list[str] = []
    assumptions = [
        item
        for item in series.get("assumptions", [])
        if isinstance(item, dict)
        and item.get("kind")
        in {
            "unit_inferred_from_consistent_sources",
            "report_scope_assumption",
            "quantity_rule_unit_inferred",
            "shipment_year_assumed_from_snapshot",
        }
    ]
    evidence: list[Any] = []
    matching = [
        row for row in forecasts if row.get("series_id") == series_id and _identity_matches(row, series)
    ]
    by_month: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in matching:
        month = _month(row.get("target_month"))
        if month in targets:
            by_month[month].append(row)
    forecast_values: dict[date, Decimal] = {}
    for month in targets:
        rows = by_month.get(month, [])
        if len(rows) != 1:
            blockers.append(f"missing_or_duplicate_forecast:{month:%Y-%m}")
            continue
        row = rows[0]
        evidence.extend(row.get("explanation", {}).get("evidence") or row.get("evidence") or [])
        if row.get("status", "ok") not in {"ok", "ready", "estimated"}:
            blockers.append(f"forecast_status:{month:%Y-%m}")
            continue
        quantity = _decimal(row.get("quantity"))
        if quantity is None:
            blockers.append(f"unknown_forecast:{month:%Y-%m}")
        elif quantity < ZERO:
            blockers.append(f"negative_forecast:{month:%Y-%m}")
        else:
            forecast_values[month] = quantity

    bridge = ZERO
    bridge_full_month = ZERO
    rows = [
        row for row in bridge_rows if row.get("series_id") == series_id and _identity_matches(row, series)
    ]
    rows = [row for row in rows if _month(row.get("target_month")) == date(planning.year, planning.month, 1)]
    if len(rows) != 1:
        blockers.append("missing_current_month_bridge")
    else:
        row = rows[0]
        bridge_full_month = _decimal(row.get("quantity"))
        evidence.extend(row.get("explanation", {}).get("evidence") or row.get("evidence") or [])
        if bridge_full_month is None or bridge_full_month < ZERO:
            blockers.append("invalid_current_month_bridge")
        elif row.get("basis") == "remaining_month":
            bridge = bridge_full_month
        elif row.get("basis") in (None, "full_month"):
            month_days = calendar.monthrange(planning.year, planning.month)[1]
            remaining_days = month_days - planning.day + 1
            bridge = bridge_full_month * Decimal(remaining_days) / Decimal(month_days)
            assumptions.append("current_month_bridge_scaled_remaining_fraction")
        else:
            blockers.append("unsupported_current_month_bridge_basis")

    inventory = series.get("inventory")
    if not isinstance(inventory, Mapping):
        blockers.append("missing_inventory")
        inventory = {}
    if inventory.get("scope") != series.get("scope"):
        blockers.append("inventory_scope_mismatch")
    if inventory.get("unit") is None or inventory.get("unit") != series.get("unit"):
        blockers.append("inventory_unit_mismatch")
    stock_date = _parse_date(inventory.get("as_of"))
    if stock_date is None or inventory.get("date_basis") in (None, "unknown"):
        blockers.append("undated_current_stock")
    elif stock_date > planning:
        blockers.append("future_current_stock")
    elif stock_date != planning:
        blockers.append("stale_current_stock")
    free = _decimal(inventory.get("free"))
    on_hand = _decimal(inventory.get("on_hand"))
    reserved = _decimal(inventory.get("reserved"))
    if on_hand is not None and reserved is not None:
        reconciled_free = on_hand - reserved
        if free is None:
            free = reconciled_free
            assumptions.append("free_derived_from_on_hand_minus_reserved")
        elif free != reconciled_free:
            blockers.append("inventory_reconciliation_conflict")
    if free is None:
        blockers.append("unknown_free_stock")
    elif free < ZERO:
        blockers.append("negative_free_stock")
    evidence.extend(inventory.get("evidence") or [])

    demand = bridge + sum(forecast_values.values(), ZERO)
    params = series.get("parameters") if isinstance(series.get("parameters"), Mapping) else {}
    buffer = _decimal(params.get("buffer", series.get("buffer", ZERO)))
    if buffer is None or buffer < ZERO:
        blockers.append("invalid_buffer")
        buffer = ZERO
    elif "buffer" not in params and "buffer" not in series:
        assumptions.append("coverage_gap_excludes_safety_stock")

    purchase_unit = series.get("purchase_unit") or params.get("purchase_unit") or series.get("unit")
    conversion = _decimal(
        series.get(
            "stock_units_per_purchase_unit",
            params.get(
                "stock_units_per_purchase_unit",
                series.get(
                    "conversion",
                    params.get(
                        "conversion", "1" if series.get("unit") and purchase_unit == series["unit"] else None
                    ),
                ),
            ),
        )
    )
    if purchase_unit is None or conversion is None or conversion <= ZERO:
        blockers.append("missing_purchase_unit_conversion")
    minimum, multiple, rule_evidence = _rules(series, purchase_unit, blockers)
    evidence.extend(rule_evidence)

    incoming, arrivals, shipment_evidence = _dedupe_shipments(working_series, coverage_end, blockers)
    evidence.extend(shipment_evidence)
    arithmetic_blockers = {
        "missing_inventory",
        "unknown_free_stock",
        "inventory_scope_mismatch",
        "inventory_unit_mismatch",
        "undated_current_stock",
        "future_current_stock",
        "stale_current_stock",
        "inventory_reconciliation_conflict",
        "negative_free_stock",
        "unknown_shipments",
        "unknown_transit_quantity",
        "negative_transit_quantity",
        "undated_transit",
        "transit_unit_mismatch",
        "conflicting_duplicate_shipment",
        "overdue_transit_receipt_unverified",
        "missing_current_month_bridge",
        "invalid_current_month_bridge",
        "unsupported_current_month_bridge_basis",
    }
    forecast_prefixes = (
        "missing_or_duplicate_forecast:",
        "unknown_forecast:",
        "forecast_status:",
        "negative_forecast:",
    )
    quantities_known = free is not None and not any(
        reason in arithmetic_blockers or reason.startswith(forecast_prefixes) for reason in blockers
    )
    raw_need = max(demand + buffer - free - incoming, ZERO) if quantities_known else None
    purchase_need = (
        raw_need / conversion if raw_need is not None and conversion and conversion > ZERO else None
    )
    order = None
    rounding_surplus = None
    if purchase_need is not None and not blockers:
        order = ZERO if purchase_need == ZERO else max(purchase_need, minimum or ZERO)
        if multiple:
            order = (order / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple
        order = order.quantize(QUANTUM, rounding=ROUND_CEILING)
        rounding_surplus = order * conversion - raw_need

    arrival_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for arrival in arrivals:
        if arrival.get("included"):
            arrival_by_day[_parse_date(arrival["expected_on"])] += _decimal(arrival["quantity"]) or ZERO
    can_project_shortage = quantities_known
    first_shortage = None
    max_shortfall = ZERO if can_project_shortage else None
    earliest_arrival = min(arrival_by_day) if arrival_by_day else None
    if can_project_shortage:
        assumptions.append("monthly_demand_allocated_uniformly_by_day")
        schedule = _demand_schedule(planning, coverage_end, bridge, forecast_values)
        balance = free
        for day in sorted(set(schedule) | set(arrival_by_day)):
            balance += arrival_by_day.get(day, ZERO)
            balance -= schedule.get(day, ZERO)
            if balance < ZERO:
                first_shortage = first_shortage or day
                if earliest_arrival is None or day < earliest_arrival:
                    max_shortfall = max(max_shortfall or ZERO, -balance)
    assumptions.append("timely_replenishment_unverified_without_lead_time")
    lead_time = series.get("lead_time_days", params.get("lead_time_days"))
    if not can_project_shortage:
        urgency = "unknown"
    elif first_shortage and lead_time is None:
        urgency = "unknown"
        assumptions.append("lead_time_unknown")
    else:
        urgency = (
            "urgent"
            if first_shortage and (earliest_arrival is None or first_shortage < earliest_arrival)
            else "review"
            if first_shortage
            else "normal"
        )
    state = "blocked" if blockers else "estimated" if assumptions else "ready"
    components = {
        "forecast_demand": _number(sum(forecast_values.values(), ZERO)),
        "bridge_demand": _number(bridge),
        "bridge_full_month": _number(bridge_full_month) if bridge_full_month else None,
        "coverage_demand": _number(demand),
        "buffer": _number(buffer),
        "free_stock": _number(free),
        "eligible_incoming": _number(incoming),
        "raw_need": _number(raw_need),
        "conversion": _number(conversion),
        "minimum": _number(minimum),
        "multiple": _number(multiple),
        "purchase_need": _number(purchase_need),
        "stock_equivalent": _number(order * conversion if order is not None and conversion else None),
        "rounding_surplus": _number(rounding_surplus),
        "first_shortage_date": first_shortage.isoformat() if first_shortage else None,
        "maximum_pre_arrival_shortfall": _number(max_shortfall),
        "arrivals": arrivals,
    }
    return {
        "series_id": series_id,
        "supplier": series.get("supplier"),
        "sku": series.get("sku"),
        "scope": series.get("scope"),
        "unit": series.get("unit"),
        "quantity": _number(order),
        "state": state,
        "status": state,
        "purchase_unit": purchase_unit,
        "coverage_start": planning.isoformat(),
        "coverage_end": coverage_end.isoformat(),
        "urgency": urgency,
        "components": components,
        "evidence": list({json.dumps(item, sort_keys=True): item for item in evidence}.values()),
        "blocking_reason": "; ".join(dict.fromkeys(blockers)) or None,
        "blocking_reasons": list(dict.fromkeys(blockers)),
        "assumptions": list({json.dumps(item, sort_keys=True): item for item in assumptions}.values()),
    }


def build_drafts(
    batch: Mapping[str, Any], forecasts: Any, bridge_forecasts: Any = None
) -> list[dict[str, Any]]:
    """Build one deterministic supplier draft line for every canonical series."""

    if not isinstance(batch, Mapping) or batch.get("contract_version") != "2":
        raise ValueError("Expected calculation contract version 2 batch")
    planning = _parse_date(batch.get("planning_date"))
    if planning is None:
        raise ValueError("Batch planning_date must be ISO date")
    forecast_rows = _forecast_rows(forecasts)
    bridge_rows = _forecast_rows(bridge_forecasts)
    return [
        _line_for_series(series, forecast_rows, bridge_rows, planning) for series in batch.get("series", [])
    ]
