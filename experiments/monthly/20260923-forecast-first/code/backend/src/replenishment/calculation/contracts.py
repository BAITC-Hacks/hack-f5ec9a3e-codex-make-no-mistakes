"""Version 2 calculation boundary.

The calculation layer deliberately accepts ordinary dictionaries.  This keeps
the boundary usable from the CLI, tests and a future database adapter without
making any of those callers depend on a serialization library.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CONTRACT_VERSION = "2"
VERSION = CONTRACT_VERSION
_MONTH_RE = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])-01$")
_DATE_RE = re.compile(r"^20\d{2}-(0[1-9]|1[0-2])-\d{2}$")
_DECIMAL_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")


def month(value: str) -> int:
    """Return a sortable month number after validating a first-of-month date."""

    if not isinstance(value, str) or not _MONTH_RE.fullmatch(value):
        raise ValueError("Expected an ISO first-of-month date (YYYY-MM-01)")
    parsed = date.fromisoformat(value)
    return parsed.year * 12 + parsed.month


def planning_date(value: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError("Expected an ISO planning date (YYYY-MM-DD)")
    return date.fromisoformat(value)


def month_date(value: str) -> date:
    month(value)
    return date.fromisoformat(value)


def decimal_string(value: str, *, nonnegative: bool = True) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
        raise ValueError("Expected a finite decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex already guards this
        raise ValueError("Expected a finite decimal string") from exc
    if not parsed.is_finite() or (nonnegative and parsed < 0):
        raise ValueError("Expected a finite nonnegative decimal string")
    return parsed


def _text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")


def _list(value: Any, field: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")


def _dict(value: Any, field: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")


def _keys(value: dict[str, Any], required: set[str], optional: set[str] | None = None) -> None:
    optional = optional or set()
    missing = required - value.keys()
    unexpected = value.keys() - required - optional
    if missing or unexpected:
        raise ValueError(f"Invalid fields; missing={sorted(missing)}, unexpected={sorted(unexpected)}")


def _validate_history(history: Any, planning_month: int) -> None:
    _list(history, "history")
    seen: set[str] = set()
    for observation in history:
        _dict(observation, "history item")
        _keys(observation, {"month", "quantity", "evidence"})
        stamp = observation["month"]
        current = month(stamp)
        if stamp in seen:
            raise ValueError("History months must be unique")
        seen.add(stamp)
        if current >= planning_month:
            raise ValueError("History must precede the planning month")
        quantity = observation["quantity"]
        if quantity is not None:
            # Negative values are retained as an explicit source finding.  The
            # forecaster excludes them from fitting instead of turning them into zero.
            decimal_string(quantity, nonnegative=False)
        _list(observation["evidence"], "history evidence")


def _validate_series(series: Any, planning_month: int) -> None:
    _dict(series, "series")
    required = {
        "series_id",
        "supplier",
        "sku",
        "scope",
        "unit",
        "history",
        "category",
        "inventory",
        "shipments",
        "quantity_rules",
        "assumptions",
    }
    optional = {
        "purchase_unit",
        "stock_units_per_purchase_unit",
        "parameters",
        "buffer",
        "conversion",
    }
    _keys(series, required, optional)
    for field in ("series_id", "supplier", "sku", "scope"):
        _text(series[field], field)
    if series["unit"] is not None:
        _text(series["unit"], "unit")
    if series["category"] is not None:
        _text(series["category"], "category")
    _validate_history(series["history"], planning_month)
    if series["inventory"] is not None:
        _dict(series["inventory"], "inventory")
    for field in ("shipments", "quantity_rules"):
        if series[field] is not None:
            _list(series[field], field)
    _list(series["assumptions"], "assumptions")
    # The core input contract stays explicit while allowing the small set of
    # purchasing facts that may be present in a database snapshot.
    unexpected = series.keys() - required - optional
    if unexpected:
        raise ValueError(f"Invalid series fields: {sorted(unexpected)}")
    for field in ("purchase_unit",):
        if series.get(field) is not None:
            _text(series[field], field)
    for field in ("stock_units_per_purchase_unit", "buffer", "conversion"):
        if field in series and series[field] is not None:
            decimal_string(series[field])
    if "parameters" in series:
        _dict(series["parameters"], "parameters")


def validate_batch(batch: Any) -> dict[str, Any]:
    """Validate and return *batch* without copying or changing its values."""

    _dict(batch, "batch")
    _keys(
        batch,
        {"contract_version", "planning_date", "series", "parameters", "source_selection"},
        {"llm_accounting"},
    )
    if batch["contract_version"] != CONTRACT_VERSION:
        raise ValueError(f"Unsupported contract version: {batch['contract_version']!r}")
    planning = planning_date(batch["planning_date"])
    _list(batch["series"], "series")
    _dict(batch["parameters"], "parameters")
    _list(batch["source_selection"], "source_selection")
    if "llm_accounting" in batch:
        _dict(batch["llm_accounting"], "llm_accounting")
    ids: set[str] = set()
    natural_ids: set[tuple[Any, ...]] = set()
    planning_month = planning.year * 12 + planning.month
    for series in batch["series"]:
        _validate_series(series, planning_month)
        if series["series_id"] in ids:
            raise ValueError("series_id values must be unique")
        ids.add(series["series_id"])
        natural = tuple(series[field] for field in ("supplier", "sku", "scope", "unit"))
        if natural in natural_ids:
            raise ValueError("Supplier/SKU/scope/unit identities must be unique")
        natural_ids.add(natural)
    return batch


def validate_results(batch: dict[str, Any], result: Any) -> dict[str, Any]:
    """Validate the result shape emitted by :func:`calculate`."""

    validate_batch(batch)
    _dict(result, "result")
    _keys(
        result,
        {"contract_version", "planning_date", "target_months", "forecasts", "drafts", "quality"},
        {"llm_accounting"},
    )
    if result["contract_version"] != CONTRACT_VERSION:
        raise ValueError("Result contract version mismatch")
    if result["planning_date"] != batch["planning_date"]:
        raise ValueError("Planning date changed")
    _list(result["target_months"], "target_months")
    if len(result["target_months"]) != 3:
        raise ValueError("Exactly three target months are required")
    targets = [month(value) for value in result["target_months"]]
    if targets != sorted(set(targets)):
        raise ValueError("Target months must be ordered and unique")
    plan = planning_date(batch["planning_date"])
    expected_targets = [plan.year * 12 + plan.month + offset for offset in (1, 2, 3)]
    if targets != expected_targets:
        raise ValueError("Target months must immediately follow the planning month")
    _list(result["forecasts"], "forecasts")
    expected = len(batch["series"]) * 3
    if len(result["forecasts"]) != expected:
        raise ValueError("Exactly three forecasts per series are required")
    known = {series["series_id"] for series in batch["series"]}
    series_by_id = {series["series_id"]: series for series in batch["series"]}
    seen: set[tuple[str, str]] = set()
    for forecast in result["forecasts"]:
        _dict(forecast, "forecast")
        _keys(
            forecast,
            {
                "series_id",
                "supplier",
                "sku",
                "scope",
                "unit",
                "target_month",
                "quantity",
                "model",
                "status",
                "explanation",
            },
        )
        _text(forecast["series_id"], "series_id")
        if forecast["series_id"] not in known:
            raise ValueError("Unknown forecast series")
        source = series_by_id[forecast["series_id"]]
        for field in ("supplier", "sku", "scope", "unit"):
            if forecast[field] != source[field]:
                raise ValueError("Forecast identity changed")
        _text(forecast["supplier"], "supplier")
        _text(forecast["sku"], "sku")
        _text(forecast["scope"], "scope")
        if forecast["unit"] is not None:
            _text(forecast["unit"], "unit")
        if forecast["target_month"] not in result["target_months"]:
            raise ValueError("Forecast target is not in target_months")
        key = (forecast["series_id"], forecast["target_month"])
        if key in seen:
            raise ValueError("Duplicate forecast target")
        seen.add(key)
        if forecast["quantity"] is not None:
            parsed = decimal_string(forecast["quantity"])
            if parsed >= Decimal("1e18") or -parsed.as_tuple().exponent > 12:
                raise ValueError("Forecast quantity exceeds Numeric(30,12)")
        _text(forecast["model"], "model")
        if forecast["status"] not in {"ok", "insufficient_data", "unsupported"}:
            raise ValueError("Invalid forecast status")
        if forecast["status"] == "ok" and forecast["quantity"] is None:
            raise ValueError("Successful forecast requires a quantity")
        if forecast["status"] != "ok" and forecast["quantity"] is not None:
            raise ValueError("Unsuccessful forecast cannot contain a quantity")
        _dict(forecast["explanation"], "explanation")
    _list(result["drafts"], "drafts")
    if len(result["drafts"]) != len(batch["series"]):
        raise ValueError("Exactly one draft is required per series")
    draft_keys: set[str] = set()
    for draft in result["drafts"]:
        _dict(draft, "draft")
        _keys(
            draft,
            {
                "series_id",
                "supplier",
                "sku",
                "scope",
                "unit",
                "quantity",
                "state",
                "purchase_unit",
                "coverage_start",
                "coverage_end",
                "urgency",
                "components",
                "evidence",
                "blocking_reason",
                "assumptions",
            },
            {"status", "blocking_reasons"},
        )
        series_id = draft["series_id"]
        if series_id in draft_keys or series_id not in known:
            raise ValueError("Draft series identities must be unique and known")
        draft_keys.add(series_id)
        source = series_by_id[series_id]
        for field in ("supplier", "sku", "scope", "unit"):
            if draft[field] != source[field]:
                raise ValueError("Draft identity changed")
        for field in ("supplier", "sku", "scope"):
            _text(draft[field], field)
        if draft["unit"] is not None:
            _text(draft["unit"], "unit")
        if draft["purchase_unit"] is not None:
            _text(draft["purchase_unit"], "purchase_unit")
        start = planning_date(draft["coverage_start"])
        end = planning_date(draft["coverage_end"])
        if end < start:
            raise ValueError("Draft coverage_end must not precede coverage_start")
        if draft["quantity"] is not None:
            parsed = decimal_string(draft["quantity"])
            if parsed >= Decimal("1e18") or -parsed.as_tuple().exponent > 12:
                raise ValueError("Draft quantity exceeds Numeric(30,12)")
        state = draft["state"]
        if state not in {"ready", "estimated", "blocked"}:
            raise ValueError("Invalid draft state")
        if (state == "blocked") != (draft["quantity"] is None):
            raise ValueError("Draft state disagrees with quantity")
        if state == "blocked" and (
            not isinstance(draft["blocking_reason"], str) or not draft["blocking_reason"].strip()
        ):
            raise ValueError("Blocked draft requires a reason")
        if state != "blocked" and draft["blocking_reason"] is not None:
            raise ValueError("Ready or estimated draft cannot have a blocking reason")
        _text(draft["urgency"], "urgency")
        _dict(draft["components"], "components")
        _list(draft["evidence"], "evidence")
        _list(draft["assumptions"], "assumptions")
        if "status" in draft and draft["status"] != state:
            raise ValueError("Draft status disagrees with state")
        if "blocking_reasons" in draft:
            _list(draft["blocking_reasons"], "blocking_reasons")
    if draft_keys != known:
        raise ValueError("Exactly one draft is required per series")
    _dict(result["quality"], "quality")
    if "llm_accounting" in result:
        _dict(result["llm_accounting"], "llm_accounting")
    return result


def to_jsonable(value: Any) -> Any:
    """Reject accidental Decimal/date values at the public boundary."""

    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite float in calculation output")
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
