import json
import os
import traceback
from decimal import Decimal
from pathlib import Path

import pytest

from replenishment.calculation.llm import (
    MAPPING_SCHEMA,
    BudgetLedger,
    InMemoryCache,
    LLMClient,
    ModelConfig,
    ModelPricing,
    Usage,
    extract_mapping,
    forecast_historical_pilot,
    load_llm_client,
    run_historical_pilot,
    validate_mapping,
)


def pricing(input_price="0.10", output_price="0.50"):
    return ModelPricing(Decimal(input_price), Decimal(output_price))


def response(value, *, input_tokens=10, output_tokens=4):
    return {
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def client(transport, *, cap="1.00", cache=None):
    return LLMClient(
        cheap=ModelConfig("test-cheap", pricing(), max_input_tokens=8_000, max_output_tokens=20),
        strong=ModelConfig("test-strong", pricing("1", "2"), max_input_tokens=8_000, max_output_tokens=20),
        budget=BudgetLedger(Decimal(cap)),
        transport=transport,
        cache=cache or InMemoryCache(),
    )


def test_structured_call_caches_exact_input_and_accounts_usage():
    calls = []
    value = {"ok": True}
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    def transport(**kwargs):
        calls.append(kwargs)
        return response(value)

    llm = client(transport)
    first = llm.call_json(purpose="test", input_data={"b": 2, "a": 1}, prompt="v1", schema=schema)
    second = llm.call_json(purpose="test", input_data={"a": 1, "b": 2}, prompt="v1", schema=schema)

    assert first.ok and second.ok and second.cached
    assert len(calls) == 1
    assert llm.budget.spent == Decimal("0.000003")
    assert calls[0]["body"]["text"]["format"]["strict"] is True


def test_refusal_and_incomplete_are_fail_safe():
    responses = iter(
        [
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
            },
            {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        ]
    )
    llm = client(lambda **_: next(responses))
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    assert llm.call_json(purpose="test", input_data={}, prompt="v1", schema=schema).error == "refusal"
    assert llm.call_json(purpose="test", input_data={}, prompt="v1", schema=schema).error == "incomplete"


def test_escalation_once_and_budget_reservation_blocks_expensive_call():
    outputs = iter([response({"wrong": True}), response({"wrong": True})])
    llm = client(lambda **_: next(outputs), cap="0.00002")
    result = extract_mapping(llm, {"sheet": "A", "available_cells": ["A1"]})
    assert not result.ok
    assert result.error in {"invalid_response", "budget_exhausted"}
    assert llm.budget.snapshot()["events"]


def test_mapping_rejects_unknown_source_cells():
    mapping = {
        "report_type": "monthly_sales",
        "header_row": 1,
        "data_start_row": 2,
        "columns": {
            "sku": "A",
            "name": None,
            "article": None,
            "unit": None,
            "months": [{"column": "B", "period": "2026-01-01"}],
            "fields": {
                key: None
                for key in MAPPING_SCHEMA["properties"]["columns"]["properties"]["fields"]["required"]
            },
            "metrics": [],
            "shipments": [],
        },
        "source_cells": [{"cell": "Z99", "purpose": "header"}],
    }
    try:
        validate_mapping(mapping, available_cells={"A1", "B1"})
    except ValueError as exc:
        assert "source cell" in str(exc)
    else:
        raise AssertionError("invalid source cell accepted")
    mapping["source_cells"] = [{"cell": "A1", "purpose": "sku"}, {"cell": "B1", "purpose": "month"}]
    validate_mapping(mapping, available_cells={"A1", "B1"})
    llm = client(lambda **_: response(mapping))
    result = extract_mapping(llm, {"available_cells": ["A1", "B1"]})
    assert result.ok


def test_historical_pilot_excludes_future_actuals_and_requires_three_targets():
    seen = []

    def transport(**kwargs):
        seen.append(kwargs["body"]["input"])
        return response(
            {
                "forecasts": [
                    {"target_month": "2026-10-01", "quantity": 1, "rationale": "level"},
                    {"target_month": "2026-11-01", "quantity": 2, "rationale": "level"},
                    {"target_month": "2026-12-01", "quantity": 3, "rationale": "level"},
                ],
                "limitations": "pilot",
            }
        )

    history = [{"month": "2026-08-01", "quantity": "4"}, {"month": "2026-09-01", "quantity": "5"}]
    result = forecast_historical_pilot(
        client(transport),
        history=history,
        target_months=["2026-10-01", "2026-11-01", "2026-12-01"],
        future_actuals=[{"month": "2026-10-01", "quantity": "999"}],
    )
    assert result.ok
    payload = str(seen[0])
    assert "999" not in payload
    assert result.value["forecasts"][0]["quantity"] == 1


def test_persistent_cache_round_trip(tmp_path: Path):
    from replenishment.calculation.llm import JsonFileCache

    path = tmp_path / "llm-cache.json"
    cache = JsonFileCache(path)
    cache.set("key", {"ok": True})
    assert JsonFileCache(path).get("key") == {"ok": True}


def test_budget_rejects_over_cap_and_duplicate_settlement():
    with pytest.raises(ValueError):
        BudgetLedger(Decimal("1.01"))
    with pytest.raises(ValueError):
        BudgetLedger(Decimal("NaN"))

    budget = BudgetLedger(Decimal("0.01"))
    reservation = budget.reserve(Decimal("0.001"), model="test", purpose="test")
    assert reservation is not None
    budget.settle(reservation, usage=Usage(20_000, 0), status="success", pricing=pricing())
    assert budget.spent == Decimal("0.002")
    with pytest.raises(ValueError):
        budget.settle(reservation, usage=None, status="failure", pricing=pricing())


def test_unknown_pricing_disables_escalation_and_schema_is_strict():
    calls = []
    llm = LLMClient(
        cheap=ModelConfig("unknown-cheap", None, max_input_tokens=100, max_output_tokens=20),
        strong=ModelConfig("test-strong", pricing(), max_input_tokens=100, max_output_tokens=20),
        transport=lambda **kwargs: calls.append(kwargs) or response({"ok": True}),
    )
    result = llm.call_with_escalation(
        purpose="test",
        input_data={},
        prompt="v1",
        schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    )
    assert result.error == "pricing_unavailable"
    assert calls == []
    assert MAPPING_SCHEMA["properties"]["columns"]["additionalProperties"] is False


def test_input_token_limit_blocks_dispatch():
    calls = []
    llm = client(lambda **kwargs: calls.append(kwargs) or response({"ok": True}))
    result = llm.call_json(
        purpose="test",
        input_data={"text": "x" * 20_000},
        prompt="v1",
        schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    )
    assert result.error == "input_too_large"
    assert calls == []


def test_config_loader_without_key_disables_paid_stage(tmp_path: Path):
    config_path = tmp_path / "llm.json"
    config_path.write_text(
        json.dumps(
            {
                "api_key_env": "MISSING_OPENAI_KEY",
                "cheap": {
                    "model_id": "test-cheap",
                    "input_per_million": "0.10",
                    "output_per_million": "0.50",
                    "max_input_tokens": 1_000,
                    "max_output_tokens": 20,
                },
            }
        ),
        encoding="utf-8",
    )
    llm = load_llm_client(config_path)
    result = llm.call_json(
        purpose="test",
        input_data={},
        prompt="v1",
        schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    )
    assert result.error == "transport_disabled"


def test_historical_pilot_uses_source_training_only():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from evaluation.cases import read_batch

    source_batch = read_batch()
    source_series = next(
        series
        for series in sorted(source_batch["series"], key=lambda item: item["series_id"])
        if sum(1 for row in series["history"] if row["month"] < "2025-09-01" and row["quantity"] is not None)
        >= 3
    )
    calls = []

    def transport(**kwargs):
        calls.append(kwargs)
        return response(
            {
                "forecasts": [
                    {"target_month": month, "quantity": 1, "rationale": "pilot"}
                    for month in ("2025-10-01", "2025-11-01", "2025-12-01")
                ],
                "limitations": "diagnostic",
            }
        )

    def run(batch):
        return run_historical_pilot(
            client(transport),
            {**batch, "series": [dict(source_series, history=list(source_series["history"]))]},
        )

    base = run(source_batch)
    poisoned_series = dict(
        source_series,
        history=[
            *source_series["history"],
            {"month": "2026-01-01", "quantity": "999999", "evidence": []},
        ],
    )
    poisoned = run({**source_batch, "series": [poisoned_series]})
    assert base["origin"] == "2025-09-01"
    assert base["promotion_status"] == "diagnostic_only"
    assert base["results"][0]["evaluation"]["target_months"] == [
        "2025-10-01",
        "2025-11-01",
        "2025-12-01",
    ]
    assert poisoned["results"][0]["evaluation"] == base["results"][0]["evaluation"]
    assert calls[0]["body"]["input"] == calls[1]["body"]["input"]
    assert "999999" not in str(calls[0]["body"]["input"])


def test_byte_bound_and_cache_failure_do_not_double_settle_or_retry_cheap():
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    text = "я" * 100
    assert LLMClient._estimate_input_tokens("", {"text": text}, schema) >= len(text.encode())

    class BrokenCache:
        def get(self, key):
            raise OSError("cache unavailable")

        def set(self, key, value):
            raise OSError("cache unavailable")

    llm = client(lambda **_: response({}), cache=BrokenCache())
    result = llm.call_json(purpose="test", input_data={}, prompt="v1", schema=schema)
    assert result.ok and llm.budget.reserved == 0
    assert llm.budget.spent == Decimal("0.000003")
    calls = []
    llm = LLMClient(cheap=llm.cheap, transport=lambda **kw: calls.append(kw) or response({"bad": True}))
    assert not llm.call_with_escalation(purpose="test", input_data={}, prompt="v1", schema=schema).ok
    assert len(calls) == 1


def test_partial_usage_report_charges_full_reservation():
    llm = client(lambda **_: {**response({}), "usage": {"output_tokens": 2}})
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    assert llm.call_json(purpose="test", input_data={}, prompt="v1", schema=schema).ok
    assert llm.budget.spent == llm.cheap.reservation


@pytest.fixture
def openai_environment(monkeypatch):
    for name in os.environ:
        if name.startswith("OPENAI_"):
            monkeypatch.delenv(name)
    for name, value in {
        "OPENAI_ENABLED": "true",
        "OPENAI_API_KEY": "test-secret",
        "OPENAI_MODEL": "test-env",
        "OPENAI_INPUT_PER_MILLION": "0.10",
        "OPENAI_OUTPUT_PER_MILLION": "0.50",
    }.items():
        monkeypatch.setenv(name, value)
    calls = []

    def transport(self, **kwargs):
        calls.append(kwargs)
        return response({})

    monkeypatch.setattr("replenishment.calculation.llm.StdlibResponsesTransport.__call__", transport)
    return calls


def environment_call(llm):
    return llm.call_with_escalation(
        purpose="environment-test",
        input_data={},
        prompt="v1",
        schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    )


@pytest.mark.parametrize("enabled", [None, "", "false"])
def test_environment_disabled(monkeypatch, openai_environment, enabled):
    if enabled is None:
        monkeypatch.delenv("OPENAI_ENABLED")
    else:
        monkeypatch.setenv("OPENAI_ENABLED", enabled)
    monkeypatch.setenv("OPENAI_INPUT_PER_MILLION", "invalid")
    assert load_llm_client() is None
    assert openai_environment == []


def test_environment_enabled_reads_at_invocation_and_reuses_client_guards(monkeypatch, openai_environment):
    llm = load_llm_client()
    assert llm.cheap.model_id == "test-env"
    assert (llm.cheap.max_input_tokens, llm.cheap.max_output_tokens) == (8000, 512)
    assert llm.strong is None
    assert llm.transport.endpoint == "https://api.openai.com/v1/responses"
    assert llm.transport.timeout == 30
    assert llm.budget.limit == Decimal("1.00")
    assert environment_call(llm).ok
    assert environment_call(llm).cached
    assert len(openai_environment) == 1
    assert llm.budget.spent == Decimal("0.000003")
    monkeypatch.setenv("OPENAI_ENABLED", "false")
    assert load_llm_client() is None


@pytest.mark.parametrize(
    "name,error",
    [
        ("OPENAI_API_KEY", "transport_disabled"),
        ("OPENAI_INPUT_PER_MILLION", "pricing_unavailable"),
        ("OPENAI_OUTPUT_PER_MILLION", "pricing_unavailable"),
    ],
)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_environment_missing_settings_block_dispatch(monkeypatch, openai_environment, name, error, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    llm = load_llm_client()
    assert environment_call(llm).error == error
    assert llm.budget.events[-1].status == error
    assert llm.budget.spent == 0
    assert openai_environment == []


@pytest.mark.parametrize(
    "name,value",
    [
        ("OPENAI_ENABLED", "secret-invalid"),
        ("OPENAI_MODEL", ""),
        ("OPENAI_INPUT_PER_MILLION", "secret-invalid"),
        ("OPENAI_OUTPUT_PER_MILLION", "NaN"),
        ("OPENAI_INPUT_PER_MILLION", "Infinity"),
        ("OPENAI_OUTPUT_PER_MILLION", "-1"),
        ("OPENAI_MAX_INPUT_TOKENS", "secret-invalid"),
        ("OPENAI_MAX_OUTPUT_TOKENS", "1.5"),
        ("OPENAI_MAX_OUTPUT_TOKENS", "0"),
        ("OPENAI_API_KEY", "secret-invalid\nheader"),
        ("OPENAI_STRONG_INPUT_PER_MILLION", "1"),
    ],
)
def test_environment_rejects_invalid_settings_without_values(monkeypatch, openai_environment, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError) as caught:
        load_llm_client()
    rendered = "".join(traceback.format_exception(caught.value))
    assert "secret-invalid" not in rendered
    assert "test-secret" not in rendered
    assert openai_environment == []


def test_environment_optional_escalation(monkeypatch, openai_environment):
    monkeypatch.setenv("OPENAI_STRONG_MODEL", "test-strong")
    monkeypatch.setenv("OPENAI_STRONG_INPUT_PER_MILLION", "1")
    monkeypatch.setenv("OPENAI_STRONG_OUTPUT_PER_MILLION", "2")
    llm = load_llm_client()
    assert (llm.strong.max_input_tokens, llm.strong.max_output_tokens) == (8000, 512)
    monkeypatch.setenv("OPENAI_STRONG_MAX_INPUT_TOKENS", "9000")
    monkeypatch.setenv("OPENAI_STRONG_MAX_OUTPUT_TOKENS", "128")
    llm = load_llm_client()
    assert (llm.strong.max_input_tokens, llm.strong.max_output_tokens) == (9000, 128)
    outputs = iter([response({"unexpected": True}), response({})])
    calls = []

    def transport(**kwargs):
        calls.append(kwargs["model"])
        return next(outputs)

    llm.transport = transport
    assert environment_call(llm).ok
    assert calls == ["test-env", "test-strong"]
    monkeypatch.delenv("OPENAI_STRONG_OUTPUT_PER_MILLION")
    llm = load_llm_client()
    llm.transport = lambda **_: response({"unexpected": True})
    assert environment_call(llm).error == "pricing_unavailable"
    monkeypatch.setenv("OPENAI_STRONG_MAX_OUTPUT_TOKENS", "invalid")
    with pytest.raises(ValueError, match="OPENAI_STRONG_MAX_OUTPUT_TOKENS"):
        load_llm_client()


def test_json_precedes_environment_settings(monkeypatch, openai_environment, tmp_path):
    monkeypatch.setenv("OPENAI_ENABLED", "false")
    monkeypatch.setenv("OPENAI_INPUT_PER_MILLION", "invalid")
    monkeypatch.setenv("OPENAI_STRONG_MODEL", "ignored")
    monkeypatch.setenv("CUSTOM_LLM_KEY", "custom-secret")
    path = tmp_path / "llm.json"
    path.write_text(
        json.dumps(
            {
                "api_key_env": "CUSTOM_LLM_KEY",
                "cheap": {
                    "model_id": "json-model",
                    "input_per_million": "1",
                    "output_per_million": "2",
                    "max_input_tokens": 2000,
                    "max_output_tokens": 100,
                },
            }
        )
    )
    llm = load_llm_client(path)
    assert llm.cheap.model_id == "json-model"
    assert llm.cheap.pricing == pricing("1", "2")
    assert (llm.cheap.max_input_tokens, llm.cheap.max_output_tokens) == (2000, 100)
    assert llm.strong is None
    assert llm.transport.api_key == "custom-secret"
    assert environment_call(llm).ok
    assert len(openai_environment) == 1
