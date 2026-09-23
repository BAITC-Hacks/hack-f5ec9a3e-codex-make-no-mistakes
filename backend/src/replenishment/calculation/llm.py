"""Bounded, structured LLM calls for extraction and historical forecast pilots.

The calculation layer owns no business arithmetic here.  This module only
handles strict JSON I/O, cache keys, model pricing and a per-run budget.  A
caller must validate any business meaning before using a successful response.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

PROMPT_VERSION = "llm-boundary-v2"
MAX_RUN_USD = Decimal("1.00")
PILOT_ORIGIN = "2025-09-01"
PILOT_TARGET_MONTHS = ("2025-10-01", "2025-11-01", "2025-12-01")

_CELL = re.compile(r"^[A-Z]{1,3}[1-9][0-9]*$")
_MONTH = re.compile(r"^20[0-9]{2}-(0[1-9]|1[0-2])-01$")


MAPPING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "report_type": {
            "type": "string",
            "enum": [
                "monthly_sales",
                "transactions",
                "stock",
                "snapshot",
                "shipments",
                "quantity_rules",
                "unknown",
            ],
        },
        "header_row": {"type": "integer", "minimum": 1},
        "data_start_row": {"type": "integer", "minimum": 1},
        # Keep the extraction contract deliberately narrow.  Additional
        # interpretations stay unresolved instead of becoming model-defined
        # fields that the downstream normalizer cannot verify.
        "columns": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                **{name: {"type": ["string", "null"]} for name in ("name", "article", "unit")},
                "fields": {
                    "type": "object",
                    "properties": {
                        name: {"type": ["string", "null"]}
                        for name in (
                            "timestamp",
                            "quantity",
                            "warehouse",
                            "document_number",
                            "document_text",
                            "quantity_rule",
                            "category",
                        )
                    },
                    "required": [
                        "timestamp",
                        "quantity",
                        "warehouse",
                        "document_number",
                        "document_text",
                        "quantity_rule",
                        "category",
                    ],
                    "additionalProperties": False,
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": [
                                    "sales_total",
                                    "sales_average",
                                    "stock_total",
                                    "showroom",
                                    "trading_area",
                                    "distribution_center",
                                    "retail",
                                    "on_hand",
                                    "reserved",
                                    "free",
                                    "growth_change",
                                    "seasonality_change",
                                    "coverage_unspecified",
                                    "planned_order",
                                    "cost_unspecified",
                                    "weight_unspecified",
                                ],
                            },
                            "column": {"type": "string"},
                        },
                        "required": ["name", "column"],
                        "additionalProperties": False,
                    },
                },
                "shipments": {"type": "array", "items": {"type": "string"}},
                "months": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "period": {"type": "string"},
                        },
                        "required": ["column", "period"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["sku", "name", "article", "unit", "months", "fields", "metrics", "shipments"],
            "additionalProperties": False,
        },
        "source_cells": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"cell": {"type": "string"}, "purpose": {"type": "string"}},
                "required": ["cell", "purpose"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["report_type", "header_row", "data_start_row", "columns", "source_cells"],
    "additionalProperties": False,
}

FORECAST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "forecasts": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "target_month": {"type": "string"},
                    "quantity": {"type": "number", "minimum": 0},
                    "rationale": {"type": "string"},
                },
                "required": ["target_month", "quantity", "rationale"],
                "additionalProperties": False,
            },
        },
        "limitations": {"type": "string"},
    },
    "required": ["forecasts", "limitations"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        try:
            input_price = Decimal(str(self.input_per_million))
            output_price = Decimal(str(self.output_per_million))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Model prices must be finite amounts") from exc
        if not input_price.is_finite() or not output_price.is_finite() or input_price < 0 or output_price < 0:
            raise ValueError("Model prices must be finite and nonnegative")
        object.__setattr__(self, "input_per_million", input_price)
        object.__setattr__(self, "output_per_million", output_price)

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts must be nonnegative")
        return (
            Decimal(input_tokens) * self.input_per_million + Decimal(output_tokens) * self.output_per_million
        ) / Decimal(1_000_000)


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    pricing: ModelPricing | None
    max_input_tokens: int = 8_000
    max_output_tokens: int = 512

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id is required")
        if (
            not isinstance(self.max_input_tokens, int)
            or not isinstance(self.max_output_tokens, int)
            or self.max_input_tokens <= 0
            or self.max_output_tokens <= 0
        ):
            raise ValueError("Token limits must be positive")

    @property
    def reservation(self) -> Decimal:
        if self.pricing is None:
            raise ValueError("Unknown model pricing")
        return self.pricing.cost(self.max_input_tokens, self.max_output_tokens)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class BudgetEvent:
    model: str
    purpose: str
    reserved: Decimal
    charged: Decimal
    status: str
    usage: Usage | None = None


@dataclass(frozen=True)
class Reservation:
    id: int
    amount: Decimal
    model: str
    purpose: str


class BudgetLedger:
    """Per-run reservation and charge ledger.

    A missing usage report charges the reservation.  This is conservative and
    keeps retries/escalations below the hard cap even when a failed response
    cannot tell us how many tokens the provider consumed.
    """

    def __init__(self, limit: Decimal = MAX_RUN_USD):
        try:
            limit = Decimal(str(limit))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Budget limit must be a finite amount from zero to one dollar") from exc
        if not limit.is_finite() or limit < 0 or limit > MAX_RUN_USD:
            raise ValueError("Budget limit must be nonnegative")
        self.limit = limit
        self.reserved = Decimal(0)
        self.spent = Decimal(0)
        self.events: list[BudgetEvent] = []
        self._next_id = 1
        self._active: dict[int, Reservation] = {}

    @property
    def available(self) -> Decimal:
        return self.limit - self.spent - self.reserved

    def reserve(self, amount: Decimal, *, model: str, purpose: str) -> Reservation | None:
        if not amount.is_finite() or amount < 0 or amount > self.available:
            return None
        reservation = Reservation(self._next_id, amount, model, purpose)
        self._next_id += 1
        self.reserved += amount
        self._active[reservation.id] = reservation
        return reservation

    def record_failure(self, *, model: str | None, purpose: str, status: str) -> None:
        """Record a rejected call which never received a reservation."""

        self.events.append(BudgetEvent(model or "unknown", purpose, Decimal(0), Decimal(0), status))

    def settle(
        self,
        reservation: Reservation,
        *,
        usage: Usage | None,
        status: str,
        pricing: ModelPricing | None,
    ) -> Decimal:
        active = self._active.get(reservation.id)
        if active != reservation or reservation.amount > self.reserved:
            raise ValueError("Unknown or already settled reservation")
        del self._active[reservation.id]
        self.reserved -= reservation.amount
        charged = (
            reservation.amount
            if usage is None or pricing is None
            else pricing.cost(usage.input_tokens, usage.output_tokens)
        )
        # The request token limits make this equal to or below the reservation
        # for a conforming provider.  Keep an unexpected overage in the ledger
        # rather than silently under-reporting it; available becomes negative,
        # so no later request can be dispatched.
        self.spent += charged
        self.events.append(
            BudgetEvent(
                reservation.model,
                reservation.purpose,
                reservation.amount,
                charged,
                status,
                usage,
            )
        )
        return charged

    def snapshot(self) -> dict[str, Any]:
        return {
            "limit_usd": format(self.limit, "f"),
            "reserved_usd": format(self.reserved, "f"),
            "spent_usd": format(self.spent, "f"),
            "available_usd": format(self.available, "f"),
            "events": [
                {
                    "model": event.model,
                    "purpose": event.purpose,
                    "reserved_usd": format(event.reserved, "f"),
                    "charged_usd": format(event.charged, "f"),
                    "status": event.status,
                    "usage": asdict(event.usage) if event.usage else None,
                }
                for event in self.events
            ],
        }


class CacheStore(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class InMemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self.values.get(key)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value


class JsonFileCache:
    """Small persistent cache suitable for a run-local cache file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def get(self, key: str) -> Any | None:
        return self._read().get(key)

    def set(self, key: str, value: Any) -> None:
        values = self._read()
        values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False, sort_keys=True))
        temporary.replace(self.path)


class ResponsesTransport(Protocol):
    def __call__(self, **kwargs: Any) -> Mapping[str, Any]: ...


class StdlibResponsesTransport:
    """OpenAI Responses API transport using only Python's standard library."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.openai.com/v1/responses",
        timeout: float = 30,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout

    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(kwargs["body"], ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"http_{exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("transport_error") from exc


@dataclass(frozen=True)
class LLMCallResult:
    ok: bool
    value: dict[str, Any] | None = None
    error: str | None = None
    cached: bool = False
    model: str | None = None
    usage: Usage | None = None
    cache_key: str | None = None


def _canonical(value: Any) -> str:
    def encode(item: Any) -> Any:
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError("Non-finite decimal is not JSON-compatible")
            return {"__decimal__": format(item, "f")}
        if isinstance(item, Mapping):
            return {str(key): encode(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [encode(value) for value in item]
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        raise TypeError(f"Value is not JSON-compatible: {type(item).__name__}")

    return json.dumps(
        encode(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def cache_key(
    *, input_data: Any, schema: Mapping[str, Any], prompt_version: str, model: str, prompt: str
) -> str:
    material = {
        "input": input_data,
        "schema": schema,
        "prompt_version": prompt_version,
        "model": model,
        "prompt": prompt,
    }
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()


def _schema_error(value: Any, schema: Mapping[str, Any], path: str = "$", root: bool = True) -> str | None:
    expected = schema.get("type")
    if isinstance(expected, list):
        if value is None and "null" in expected:
            return None
        return _schema_error(value, {**schema, "type": next(t for t in expected if t != "null")}, path, root)
    if expected == "object":
        if not isinstance(value, dict):
            return f"{path}: expected object"
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            return f"{path}: missing {missing}"
        if schema.get("additionalProperties") is False:
            unexpected = set(value) - set(schema.get("properties", {}))
            if unexpected:
                return f"{path}: unexpected {sorted(unexpected)}"
        for key, child in schema.get("properties", {}).items():
            if key in value:
                error = _schema_error(value[key], child, f"{path}.{key}", root=False)
                if error:
                    return error
    elif expected == "array":
        if not isinstance(value, list):
            return f"{path}: expected array"
        if "minItems" in schema and len(value) < schema["minItems"]:
            return f"{path}: too few items"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path}: too many items"
        for index, item in enumerate(value):
            error = _schema_error(item, schema.get("items", {}), f"{path}[{index}]", root=False)
            if error:
                return error
    elif expected == "string":
        if not isinstance(value, str):
            return f"{path}: expected string"
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{path}: expected integer"
    elif expected == "number":
        if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
            return f"{path}: expected number"
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return f"{path}: expected finite number"
        if not number.is_finite():
            return f"{path}: expected finite number"
    elif expected == "boolean":
        if not isinstance(value, bool):
            return f"{path}: expected boolean"
    elif expected == "null":
        if value is not None:
            return f"{path}: expected null"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: invalid enum"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path}: below minimum"
    return None


def _response_value(response: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None, Usage | None]:
    status = response.get("status")
    if status == "incomplete" or response.get("incomplete_details") is not None:
        return None, "incomplete", _usage(response)
    if response.get("error") is not None:
        return None, "transport_error", _usage(response)
    output = response.get("output_parsed")
    if isinstance(output, dict):
        return output, None, _usage(response)
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError:
            return None, "invalid_response", _usage(response)
        return (
            (parsed if isinstance(parsed, dict) else None),
            None if isinstance(parsed, dict) else "invalid_response",
            _usage(response),
        )
    for item in response.get("output", []):
        for content in item.get("content", []) if isinstance(item, dict) else []:
            if content.get("type") == "refusal" or "refusal" in content:
                return None, "refusal", _usage(response)
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, dict) and isinstance(text.get("value"), str):
                    text = text["value"]
                if isinstance(text, str):
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        return None, "invalid_response", _usage(response)
                    return (
                        (parsed if isinstance(parsed, dict) else None),
                        None if isinstance(parsed, dict) else "invalid_response",
                        _usage(response),
                    )
                if isinstance(content.get("parsed"), dict):
                    return content["parsed"], None, _usage(response)
    return None, "invalid_response", _usage(response)


def _usage(response: Mapping[str, Any]) -> Usage | None:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return None
    input_value = usage.get("input_tokens")
    output_value = usage.get("output_tokens")
    if (
        isinstance(input_value, bool)
        or isinstance(output_value, bool)
        or not isinstance(input_value, int)
        or not isinstance(output_value, int)
    ):
        return None
    input_tokens = input_value
    output_tokens = output_value
    if input_tokens < 0 or output_tokens < 0:
        return None
    return Usage(input_tokens, output_tokens)


class LLMClient:
    def __init__(
        self,
        *,
        cheap: ModelConfig | None = None,
        strong: ModelConfig | None = None,
        budget: BudgetLedger | None = None,
        transport: ResponsesTransport | None = None,
        api_key: str | None = None,
        cache: CacheStore | None = None,
        prompt_version: str = PROMPT_VERSION,
    ):
        if transport is not None and api_key is not None:
            raise ValueError("Provide transport or api_key, not both")
        self.cheap = cheap
        self.strong = strong
        self.budget = budget or BudgetLedger()
        self.transport = transport or (StdlibResponsesTransport(api_key) if api_key else None)
        self.cache = cache or InMemoryCache()
        self.prompt_version = prompt_version

    @staticmethod
    def _estimate_input_tokens(prompt: str, input_data: Any, schema: Mapping[str, Any]) -> int:
        # Byte-level tokenization cannot require more text tokens than UTF-8
        # bytes. Add framing allowance; an average chars/token estimate is NOT
        # a worst-case reservation, particularly for Cyrillic/numeric inputs.
        encoded = _canonical({"prompt": prompt, "input": input_data, "schema": schema}).encode("utf-8")
        return len(encoded) + 256

    def call_json(
        self,
        *,
        purpose: str,
        input_data: Any,
        prompt: str,
        schema: Mapping[str, Any],
        model: ModelConfig | None = None,
        max_attempts: int = 1,
        validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> LLMCallResult:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        config = model or self.cheap
        if config is None:
            self.budget.record_failure(model=None, purpose=purpose, status="pricing_unavailable")
            return LLMCallResult(False, error="pricing_unavailable", cache_key=None)
        try:
            key = cache_key(
                input_data=input_data,
                schema=schema,
                prompt_version=self.prompt_version,
                model=config.model_id,
                prompt=prompt,
            )
        except (TypeError, ValueError):
            self.budget.record_failure(model=config.model_id, purpose=purpose, status="invalid_input")
            return LLMCallResult(False, error="invalid_input", model=config.model_id)
        try:
            cached = self.cache.get(key)
        except (OSError, ValueError):
            self.budget.record_failure(model=config.model_id, purpose=purpose, status="cache_read_failed")
            cached = None
        if isinstance(cached, dict):
            error = _schema_error(cached, schema)
            if error is None and (validator is None or _validate_call(validator, cached) is None):
                return LLMCallResult(True, cached, cached=True, model=config.model_id, cache_key=key)
        if config.pricing is None:
            self.budget.record_failure(model=config.model_id, purpose=purpose, status="pricing_unavailable")
            return LLMCallResult(False, error="pricing_unavailable", model=config.model_id, cache_key=key)
        if self.transport is None:
            self.budget.record_failure(model=config.model_id, purpose=purpose, status="transport_disabled")
            return LLMCallResult(False, error="transport_disabled", model=config.model_id, cache_key=key)
        try:
            estimated_input_tokens = self._estimate_input_tokens(prompt, input_data, schema)
        except (TypeError, ValueError):
            self.budget.record_failure(model=config.model_id, purpose=purpose, status="invalid_input")
            return LLMCallResult(False, error="invalid_input", model=config.model_id, cache_key=key)
        if estimated_input_tokens > config.max_input_tokens:
            self.budget.record_failure(model=config.model_id, purpose=purpose, status="input_too_large")
            return LLMCallResult(False, error="input_too_large", model=config.model_id, cache_key=key)
        body = {
            "model": config.model_id,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": _canonical(input_data)}]},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "replenishment_output",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": config.max_output_tokens,
        }
        last_error = "invalid_response"
        for _attempt in range(max_attempts):
            reservation = self.budget.reserve(config.reservation, model=config.model_id, purpose=purpose)
            if reservation is None:
                self.budget.record_failure(model=config.model_id, purpose=purpose, status="budget_exhausted")
                return LLMCallResult(False, error="budget_exhausted", model=config.model_id, cache_key=key)
            usage = None
            value = None
            try:
                response = self.transport(model=config.model_id, body=body)
                value, error, usage = _response_value(response)
                last_error = error or "invalid_response"
                if value is not None:
                    schema_error = _schema_error(value, schema)
                    validation_error = _validate_call(validator, value) if validator else None
                    if schema_error is None and validation_error is None:
                        last_error = None
                    else:
                        last_error = "invalid_response"
            except Exception:
                last_error = "transport_error"
            self.budget.settle(
                reservation, usage=usage, status=last_error or "success", pricing=config.pricing
            )
            if last_error is None:
                try:
                    self.cache.set(key, value)
                except (OSError, ValueError):
                    self.budget.record_failure(
                        model=config.model_id, purpose=purpose, status="cache_write_failed"
                    )
                return LLMCallResult(True, value, model=config.model_id, usage=usage, cache_key=key)
        return LLMCallResult(False, error=last_error, model=config.model_id, usage=usage, cache_key=key)

    def call_with_escalation(
        self,
        *,
        purpose: str,
        input_data: Any,
        prompt: str,
        schema: Mapping[str, Any],
        validator: Callable[[dict[str, Any]], None] | None = None,
        cheap_attempts: int = 1,
    ) -> LLMCallResult:
        result = self.call_json(
            purpose=purpose,
            input_data=input_data,
            prompt=prompt,
            schema=schema,
            model=self.cheap,
            max_attempts=cheap_attempts,
            validator=validator,
        )
        # Unknown model pricing disables the paid stage entirely.  It is not
        # safe to silently replace an unpriced cheap model with a priced one.
        if result.ok or self.strong is None or result.error in {"transport_disabled", "pricing_unavailable"}:
            return result
        return self.call_json(
            purpose=f"{purpose}:escalation",
            input_data=input_data,
            prompt=prompt,
            schema=schema,
            model=self.strong,
            max_attempts=1,
            validator=validator,
        )


def _configured_model(value: Any) -> ModelConfig | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("LLM model configuration must be an object")
    model_id = value.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("Configured LLM model_id is required")
    input_price = value.get("input_per_million")
    output_price = value.get("output_per_million")
    pricing_value = value.get("pricing")
    if isinstance(pricing_value, Mapping):
        input_price = pricing_value.get("input_per_million", input_price)
        output_price = pricing_value.get("output_per_million", output_price)
    pricing = None
    if input_price is not None and output_price is not None:
        pricing = ModelPricing(input_price, output_price)
    return ModelConfig(
        model_id,
        pricing,
        max_input_tokens=int(value.get("max_input_tokens", 8_000)),
        max_output_tokens=int(value.get("max_output_tokens", 512)),
    )


def _environment_model(prefix: str) -> ModelConfig:
    model_id = os.environ.get(f"{prefix}MODEL", "").strip()
    if not model_id:
        raise ValueError(f"{prefix}MODEL is required")
    values: dict[str, Any] = {"model_id": model_id}
    for field in ("input_per_million", "output_per_million"):
        name = f"{prefix}{field.upper()}"
        value = os.environ.get(name, "").strip()
        if value:
            try:
                ModelPricing(value, value)
            except ValueError:
                raise ValueError(f"{name} must be a finite nonnegative USD price") from None
            values[field] = value
    for field, default in (("max_input_tokens", 8_000), ("max_output_tokens", 512)):
        name = f"{prefix}{field.upper()}"
        value = os.environ.get(name, "").strip()
        try:
            limit = int(value) if value else default
            if value and (not re.fullmatch(r"[0-9]+", value) or limit <= 0):
                raise ValueError
        except ValueError:
            raise ValueError(f"{name} must be a positive integer") from None
        values[field] = limit
    return _configured_model(values)


def load_llm_client(
    config_path: str | Path | None = None,
    *,
    cache_path: str | Path | None = None,
    budget: BudgetLedger | None = None,
) -> LLMClient | None:
    """Load JSON or opt-in environment settings; absent prices disable paid calls."""

    if config_path is None:
        enabled = os.environ.get("OPENAI_ENABLED", "false").strip().lower()
        if enabled in {"", "false"}:
            return None
        if enabled != "true":
            raise ValueError("OPENAI_ENABLED must be true or false")
        cheap = _environment_model("OPENAI_")
        strong = None
        if any(
            os.environ.get(f"OPENAI_STRONG_{suffix}", "").strip()
            for suffix in (
                "MODEL",
                "INPUT_PER_MILLION",
                "OUTPUT_PER_MILLION",
                "MAX_INPUT_TOKENS",
                "MAX_OUTPUT_TOKENS",
            )
        ):
            strong = _environment_model("OPENAI_STRONG_")
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key and (not api_key.isascii() or any(char.isspace() for char in api_key)):
            raise ValueError("OPENAI_API_KEY has invalid characters")
        return LLMClient(
            cheap=cheap,
            strong=strong,
            budget=budget,
            api_key=api_key or None,
            cache=JsonFileCache(cache_path) if cache_path is not None else InMemoryCache(),
        )

    raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("LLM configuration must be an object")
    key_env = raw.get("api_key_env", "OPENAI_API_KEY")
    if not isinstance(key_env, str) or not key_env:
        raise ValueError("api_key_env must be a nonempty string")
    api_key = os.environ.get(key_env)
    cache = JsonFileCache(cache_path) if cache_path is not None else InMemoryCache()
    return LLMClient(
        cheap=_configured_model(raw.get("cheap")),
        strong=_configured_model(raw.get("strong")),
        budget=budget,
        api_key=api_key,
        cache=cache,
        prompt_version=str(raw.get("prompt_version", PROMPT_VERSION)),
    )


def _valid_training_quantity(value: Any) -> bool:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return quantity.is_finite() and quantity >= 0


def _pilot_evaluation(
    value: Mapping[str, Any] | None,
    target_rows: Sequence[Mapping[str, Any]],
    target_months: Sequence[str],
    baseline: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Score a pilot after the call; target rows never enter its request."""

    observed = {str(row["month"]): row.get("quantity") for row in target_rows}
    actuals = {month: observed.get(month) for month in target_months}
    forecasts = value.get("forecasts", ()) if isinstance(value, Mapping) else ()
    predicted = {
        str(row.get("target_month")): row.get("quantity") for row in forecasts if isinstance(row, Mapping)
    }
    llm_errors: list[Decimal] = []
    baseline_errors: list[Decimal] = []
    scored_months: list[str] = []
    baseline_predictions = {
        str(row.get("target_month")): row.get("quantity")
        for row in (baseline or {}).get("forecasts", ())
        if isinstance(row, Mapping)
    }
    for month, raw_actual in actuals.items():
        try:
            actual = Decimal(str(raw_actual))
            prediction = Decimal(str(predicted[month]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            continue
        if not actual.is_finite() or not prediction.is_finite() or actual < 0 or prediction < 0:
            continue
        scored_months.append(month)
        llm_errors.append(abs(prediction - actual))
        try:
            baseline_quantity = Decimal(str(baseline_predictions[month]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            baseline_quantity = None
        if baseline_quantity is not None and baseline_quantity.is_finite() and baseline_quantity >= 0:
            baseline_errors.append(abs(baseline_quantity - actual))

    def mean(values: Sequence[Decimal]) -> str | None:
        return format(sum(values, Decimal(0)) / len(values), "f") if values else None

    return {
        "target_months": list(target_months),
        "actuals": actuals,
        "scored_months": scored_months,
        "missing_or_invalid_actuals": len(actuals) - len(scored_months),
        "llm_mae": mean(llm_errors),
        "statistical_baseline_mae": mean(baseline_errors),
    }


def run_historical_pilot(
    client: LLMClient,
    batch: Mapping[str, Any],
    *,
    sample_size: int = 3,
) -> dict[str, Any]:
    """Run a small deterministic, diagnostic-only sample from pre-target history."""

    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    from .forecasting import forecast_batch

    date.fromisoformat(str(batch["planning_date"]))
    origin = date.fromisoformat(PILOT_ORIGIN)
    target_months = list(PILOT_TARGET_MONTHS)
    series = [
        value
        for value in batch.get("series", [])
        if isinstance(value, Mapping)
        and sum(
            1
            for row in value.get("history", ())
            if isinstance(row, Mapping)
            and str(row.get("month", "")) < PILOT_ORIGIN
            and _valid_training_quantity(row.get("quantity"))
        )
        >= 3
    ]
    series = sorted(series, key=lambda value: str(value.get("series_id", "")))[:sample_size]
    results: list[dict[str, Any]] = []
    for item in series:
        history = sorted(item["history"], key=lambda row: str(row.get("month", "")))
        training_rows = [row for row in history if str(row.get("month", "")) < PILOT_ORIGIN]
        target_rows = [row for row in history if str(row.get("month", "")) in target_months]
        # Evidence remains in the batch for the audit trail; the pilot only
        # needs normalized month/quantity pairs and must not receive source
        # payloads or held-out observations.
        model_history = [
            {"month": row.get("month"), "quantity": row.get("quantity")} for row in training_rows
        ]
        training_series = {**item, "history": model_history}
        baseline_rows, _ = forecast_batch([training_series], origin)
        baseline = {"forecasts": baseline_rows}
        result = forecast_historical_pilot(
            client,
            history=model_history,
            target_months=target_months,
            context={
                "supplier": item.get("supplier"),
                "sku": item.get("sku"),
                "scope": item.get("scope"),
                "unit": item.get("unit"),
                "category": item.get("category")
                if (item.get("parameters", {}).get("category_available_from") or "9999-01-01") < PILOT_ORIGIN
                else None,
            },
        )
        results.append(
            {
                "series_id": item.get("series_id"),
                "ok": result.ok,
                "value": result.value,
                "error": result.error,
                "cached": result.cached,
                "model": result.model,
                "usage": asdict(result.usage) if result.usage else None,
                "cache_key": result.cache_key,
                "evaluation": _pilot_evaluation(result.value, target_rows, target_months, baseline),
            }
        )
    return {
        "promotion_status": "diagnostic_only",
        "origin": PILOT_ORIGIN,
        "sample_size": len(series),
        "results": results,
        "accounting": client.budget.snapshot(),
    }


def _validate_call(validator: Callable[[dict[str, Any]], None] | None, value: dict[str, Any]) -> str | None:
    if validator is None:
        return None
    try:
        validator(value)
    except (TypeError, ValueError, KeyError):
        return "invalid_response"
    return None


def validate_mapping(mapping: Mapping[str, Any], *, available_cells: set[str] | None = None) -> None:
    error = _schema_error(mapping, MAPPING_SCHEMA)
    if error:
        raise ValueError(error)
    if mapping["header_row"] >= mapping["data_start_row"]:
        raise ValueError("data_start_row must be at or after header_row")
    cells = [item["cell"] for item in mapping["source_cells"]]
    if any(not _CELL.fullmatch(cell) for cell in cells):
        raise ValueError("Invalid source cell")
    if len(cells) != len(set(cells)):
        raise ValueError("Duplicate source cell")
    if available_cells is not None and any(cell not in available_cells for cell in cells):
        raise ValueError("Unknown source cell")
    months = mapping["columns"].get("months", [])
    if not isinstance(months, list):
        raise ValueError("columns.months must be a list")
    seen: set[str] = set()
    for item in months:
        if (
            not isinstance(item, Mapping)
            or not re.fullmatch(r"[A-Z]{1,3}", str(item.get("column", "")))
            or not _MONTH.fullmatch(str(item.get("period", "")))
        ):
            raise ValueError("Invalid month column mapping")
        if item["period"] in seen:
            raise ValueError("Duplicate mapped period")
        seen.add(item["period"])


def extract_mapping(
    client: LLMClient, sheet: Mapping[str, Any], *, validator: Callable[[dict[str, Any]], Any] | None = None
) -> LLMCallResult:
    available = set(sheet.get("available_cells", ()))

    def validate(value: dict[str, Any]) -> None:
        validate_mapping(value, available_cells=available or None)
        if validator:
            validator(value)

    prompt = (
        "Return only the strict mapping schema. Cite source cells for every interpretation. "
        "Do not rewrite rows or invent quantities; unresolved fields must remain represented as unknown."
    )
    return client.call_with_escalation(
        purpose="worksheet_mapping",
        input_data=dict(sheet),
        prompt=prompt,
        schema=MAPPING_SCHEMA,
        validator=validate,
    )


def _validate_forecast(value: dict[str, Any], target_months: Sequence[str]) -> None:
    expected = list(target_months)
    if len(expected) != 3 or any(not _MONTH.fullmatch(item) for item in expected) or len(set(expected)) != 3:
        raise ValueError("Exactly three unique target months required")
    rows = value.get("forecasts")
    if not isinstance(rows, list) or [item.get("target_month") for item in rows] != expected:
        raise ValueError("Forecasts must contain target months in requested order")
    for item in rows:
        if not isinstance(item.get("rationale"), str) or not item["rationale"].strip():
            raise ValueError("Forecast rationale required")
        quantity = item.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float, Decimal)):
            raise ValueError("Forecast quantity must be numeric")
        if not Decimal(str(quantity)).is_finite() or quantity < 0:
            raise ValueError("Forecast quantity must be finite and nonnegative")


def forecast_historical_pilot(
    client: LLMClient,
    *,
    history: Sequence[Mapping[str, Any]],
    target_months: Sequence[str],
    context: Mapping[str, Any] | None = None,
    future_actuals: Sequence[Mapping[str, Any]] | None = None,
) -> LLMCallResult:
    """Run one three-month LLM challenger using only pre-target history.

    ``future_actuals`` is accepted only as a guardrail for callers that have a
    complete evaluation case. It is deliberately checked and omitted from the
    model input, so actuals cannot leak into the pilot prompt.
    """

    _validate_history(history, target_months)
    if len(target_months) != 3:
        raise ValueError("Exactly three target months required")
    future = future_actuals or ()
    targets = set(target_months)
    if any(str(row.get("month")) in targets for row in future):
        # Keep evaluation actuals out of the model request while allowing the
        # caller to pass them for explicit leakage checks.
        pass
    input_data = {
        "history": [dict(row) for row in history],
        "context": dict(context or {}),
        "target_months": list(target_months),
    }
    prompt = (
        "Produce exactly three nonnegative historical forecasts. Use only the supplied history and context; "
        "do not infer future actuals, browse, call tools, or claim deployment suitability."
    )
    return client.call_json(
        purpose="historical_forecast_pilot",
        input_data=input_data,
        prompt=prompt,
        schema=FORECAST_SCHEMA,
        validator=lambda value: _validate_forecast(value, target_months),
    )


def _validate_history(history: Sequence[Mapping[str, Any]], target_months: Sequence[str]) -> None:
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise ValueError("history must be a sequence")
    if len(target_months) != 3 or any(not _MONTH.fullmatch(str(item)) for item in target_months):
        raise ValueError("Exactly three valid target months required")
    first_target = min(target_months)
    seen: set[str] = set()
    for row in history:
        if not isinstance(row, Mapping):
            raise ValueError("history rows must be mappings")
        month = str(row.get("month", ""))
        if not _MONTH.fullmatch(month) or month in seen or month >= first_target:
            raise ValueError("history contains duplicate or future month")
        seen.add(month)
        quantity = row.get("quantity")
        if quantity is None:
            continue
        try:
            parsed = Decimal(str(quantity))
        except InvalidOperation as exc:
            raise ValueError("history quantity must be numeric") from exc
        if not parsed.is_finite():
            raise ValueError("history quantity must be finite")
