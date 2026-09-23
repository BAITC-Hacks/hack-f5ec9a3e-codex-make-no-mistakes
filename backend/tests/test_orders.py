"""Order API validation and conservative database failure handling."""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from replenishment.api.orders import create_orders_router


def planning_input():
    return {
        "planning_date": "2026-09-23", "lead_time_days": 2, "review_days": 1,
        "rows": [{
            "row_id": "item-1", "supplier": "Systeme", "sku": "001", "name": "Cable",
            "stock_unit": "piece", "purchase_unit": "piece", "warehouse": "Almaty",
            "free_stock": "0", "stock_as_of": "2026-09-23", "stock_scope_confirmed": True,
            "incoming_complete": True, "constraints_confirmed": True,
            "stock_per_purchase_unit": "1", "minimum_order": "0", "order_multiple": "1",
            "daily_demand": "6", "basis": "synthetic",
            "sources": [{"label": "Synthetic acceptance fixture", "source_row_id": "fixture-row"}],
        }],
    }


def application(engine):
    app = FastAPI()
    app.include_router(create_orders_router(engine))
    return app


@pytest.fixture
def offline_client(monkeypatch):
    engine = create_engine("postgresql+psycopg://user:secret@localhost/unavailable")

    def unavailable():
        raise OperationalError("secret database URL", {}, Exception("secret"))

    monkeypatch.setattr(engine, "connect", unavailable)
    with TestClient(application(engine)) as client:
        yield client
    engine.dispose()


def test_preview_requires_no_database_and_preserves_decimal_strings(offline_client):
    response = offline_client.post("/api/v1/planning/calculate", json=planning_input())
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["recommended_quantity"] == "18"
    cases = offline_client.get("/api/v1/planning/demo-cases")
    assert cases.status_code == 200 and cases.json()


def test_auto_forecast_flows_through_custom_period_to_purchase_quantity(offline_client):
    payload = planning_input()
    payload.update(forecast_method="auto", forecast_end="2026-11-08")
    row = payload["rows"][0]
    row.pop("daily_demand")
    row.update(history_start="2026-07-29", history_end="2026-09-22")
    row["sales"] = [
        {"day": str(date(2026, 7, 29) + timedelta(days=index)), "quantity": "10", "document": str(index)}
        for index in range(56)
    ]
    response = offline_client.post("/api/v1/planning/calculate", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()["rows"][0]
    assert result["forecast_method"] == "weekly_ewma"
    assert result["coverage_end"] == "2026-11-09"
    assert result["forecast_demand"] == "470"
    assert result["recommended_quantity"] == "470"
    assert len(result["daily_balances"]) == 47


def test_database_errors_do_not_leak_credentials(offline_client):
    response = offline_client.post("/api/v1/scenarios", json={"name": "Test", "input": planning_input()})
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    for path in ("/api/v1/scenarios", "/api/v1/scenarios/00000000-0000-0000-0000-000000000000"):
        response = offline_client.get(path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}


def test_api_rejects_client_result_and_invalid_override_payloads(offline_client):
    response = offline_client.post("/api/v1/scenarios", json={
        "name": "Test", "input": planning_input(), "result": {"rows": []},
    })
    assert response.status_code == 422
    for quantity, reason in (("-1", "Because"), ("NaN", "Because"), ("Infinity", "Because"), ("1", "  ")):
        response = offline_client.put("/api/v1/scenarios/00000000-0000-0000-0000-000000000000", json={
            "expected_revision": 1, "name": "Test", "input": planning_input(),
            "overrides": [{"row_id": "item-1", "quantity": quantity, "reason": reason}],
        })
        assert response.status_code == 422
