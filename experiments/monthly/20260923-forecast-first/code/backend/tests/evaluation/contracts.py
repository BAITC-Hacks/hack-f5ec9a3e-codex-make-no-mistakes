"""Strict JSON-compatible boundary for replenishment.calculation.calculate(batch)."""

import importlib
import re
from decimal import Decimal

VERSION = "inventory-evaluation-v1"
IDENTITY = {"contract_version", "case_id", "supplier", "sku", "unit", "target_month"}


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - set(optional):
        raise ValueError("Missing or unexpected fields")


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty string")


def month(value):
    if not isinstance(value, str) or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value):
        raise ValueError("Expected YYYY-MM")
    return int(value[:4]) * 12 + int(value[5:])


def quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError("Expected nonnegative finite decimal string")
    return Decimal(value)


def references(value):
    if not isinstance(value, list) or not value:
        raise ValueError("Source references required")
    for ref in value:
        fields(ref, {"path", "sha256", "sheet", "cell"})
        for item in ref.values():
            text(item)
        if not re.fullmatch(r"[a-f0-9]{64}", ref["sha256"]):
            raise ValueError("Invalid source hash")
        if not re.fullmatch(r"[A-Z]+[1-9]\d*", ref["cell"]):
            raise ValueError("Invalid source cell")


def identity(item):
    for key in IDENTITY:
        text(item[key])
    if item["contract_version"] != VERSION:
        raise ValueError("Unsupported contract version")
    month(item["target_month"])


def validate_requests(batch):
    if not isinstance(batch, list):
        raise ValueError("Expected batch list")
    ids = set()
    for item in batch:
        fields(item, IDENTITY | {"origin", "history", "stock", "receipts", "constraints"})
        identity(item)
        if item["case_id"] in ids:
            raise ValueError("Duplicate case ID")
        ids.add(item["case_id"])
        origin = month(item["origin"])
        if month(item["target_month"]) != origin + 1:
            raise ValueError("Target must immediately follow origin")
        history = item["history"]
        if not isinstance(history, list) or not history:
            raise ValueError("Completed history required")
        previous = 0
        for observation in history:
            fields(observation, {"month", "quantity", "sources"})
            current = month(observation["month"])
            if not previous < current <= origin:
                raise ValueError("History must be unique, ordered and precede target")
            previous = current
            quantity(observation["quantity"])
            references(observation["sources"])
        if previous != origin:
            raise ValueError("Origin observation required")
        stock = item["stock"]
        if stock is not None:
            fields(stock, {"free", "as_of", "scope", "sources"})
            quantity(stock["free"])
            text(stock["scope"])
            if month(stock["as_of"]) != origin:
                raise ValueError("Stock timing must match origin")
            references(stock["sources"])
        receipts = item["receipts"]
        if receipts is not None:
            if not isinstance(receipts, list):
                raise ValueError("Receipts must be list or null")
            receipt_ids = set()
            for receipt in receipts:
                fields(receipt, {"id", "quantity", "due", "known_at", "scope", "sources"})
                text(receipt["id"])
                if receipt["id"] in receipt_ids:
                    raise ValueError("Duplicate receipt")
                receipt_ids.add(receipt["id"])
                quantity(receipt["quantity"])
                if month(receipt["known_at"]) > origin or month(receipt["due"]) <= origin:
                    raise ValueError("Receipt timing invalid")
                if stock is None or receipt["scope"] != stock["scope"]:
                    raise ValueError("Receipt scope unconfirmed")
                references(receipt["sources"])
        constraints = item["constraints"]
        if constraints is not None:
            fields(constraints, {"minimum", "multiple", "coverage_months", "confirmed_at", "sources"})
            for key in ("minimum", "multiple", "coverage_months"):
                number = quantity(constraints[key])
                if key != "minimum" and number == 0:
                    raise ValueError("Positive multiple/coverage required")
            if month(constraints["confirmed_at"]) > origin:
                raise ValueError("Future constraints")
            references(constraints["sources"])
    return batch


def validate_results(batch, results):
    validate_requests(batch)
    if not isinstance(results, list) or len(results) != len(batch):
        raise ValueError("One result per input required")
    requests = {item["case_id"]: item for item in batch}
    seen = set()
    for result in results:
        fields(
            result,
            IDENTITY | {"status", "forecast", "reason"},
            {"recommended_quantity", "components", "evidence"},
        )
        identity(result)
        key = result["case_id"]
        if key in seen or key not in requests:
            raise ValueError("Duplicate or unexpected result")
        seen.add(key)
        request = requests[key]
        if any(result[field] != request[field] for field in IDENTITY):
            raise ValueError("Result identity changed")
        if result["status"] not in {"ok", "insufficient_data", "unsupported"}:
            raise ValueError("Invalid status")
        if result["status"] == "ok":
            quantity(result["forecast"])
        elif result["forecast"] is not None:
            raise ValueError("Unsuccessful result must not contain forecast")
        if result["reason"] is not None:
            text(result["reason"])
        order = result.get("recommended_quantity")
        if result["status"] != "ok" or order is None:
            text(result["reason"])
        if order is not None:
            quantity(order)
            if result["status"] != "ok" or any(
                request[k] is None for k in ("stock", "receipts", "constraints")
            ):
                raise ValueError("Ordering evidence missing")
            components = result.get("components")
            fields(components, {"coverage_demand", "free_stock", "eligible_transit", "minimum", "multiple"})
            for value in components.values():
                quantity(value)
            references(result.get("evidence"))
        elif result.get("components") is not None:
            raise ValueError("Components without an order")
        if result.get("evidence") is not None:
            references(result["evidence"])
    return results


def load_app():
    """Only absence of this exact module is pending; all other import failures propagate."""
    try:
        module = importlib.import_module("replenishment.calculation")
    except ModuleNotFoundError as exc:
        if exc.name == "replenishment.calculation":
            return None
        raise
    return module.calculate
