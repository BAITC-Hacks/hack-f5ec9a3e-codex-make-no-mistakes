"""HTTP acceptance for quantities + delivery timing using saved real Almaty roads."""

from decimal import Decimal, localcontext

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from replenishment.api.app import create_app
from replenishment.delivery_planning import DeliveryPlanningRequest, recommend_deliveries
from replenishment.delivery_planning_demo import almaty_demo_input


@pytest.fixture
def client():
    engine = create_engine("sqlite://")
    # These endpoints must not read or write a database, even through the real app.
    def unavailable(*args, **kwargs):
        raise AssertionError("delivery recommendation unexpectedly accessed the database")
    engine.connect = unavailable
    with TestClient(create_app(engine)) as http:
        yield http
    engine.dispose()


@pytest.fixture
def payload():
    data = almaty_demo_input().model_dump(mode="json")
    data["solve_time_limit_ms"] = 300
    return data


def distel(data):
    return next(c for c in data["clients"] if c["client_id"] == "distel")


def test_real_app_recommends_quantities_and_better_day_and_documents_contract(client):
    example = client.get("/api/v1/delivery-planning/demo-input")
    assert example.status_code == 200
    response = client.post("/api/v1/delivery-planning/recommend", json=example.json())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ready_for_review"
    assert len(result["clients"]) == 9 and all(c["status"] == "planned" for c in result["clients"])
    assert all(c["items"][0]["quantity"] == "40" for c in result["clients"])
    assert distel(result)["recommended_date"] == "2026-10-01"
    assert distel(result)["service_end_minute"] <= distel(result)["latest_safe_minute"]
    routing = result["routing"]
    assert Decimal(routing["savings"]) > 0
    assert sum(r["distance_metres"] for r in routing["proposed"]["routes"]) < sum(
        r["distance_metres"] for r in routing["baseline"]["routes"])
    schema = client.get("/openapi.json").json()
    assert "/api/v1/delivery-planning/recommend" in schema["paths"]


@pytest.mark.parametrize("constraint", ["stock", "capacity", "locked", "contract"])
def test_stock_or_commitment_or_vehicle_constraints_keep_monday(client, payload, constraint):
    customer = distel(payload)
    if constraint == "stock":
        customer["items"][0]["available_stock"] = "25"
        customer["items"][0]["reserve_units"] = "0"
    elif constraint == "capacity":
        payload["shifts"][1]["capacity_kg"] = 550
    elif constraint == "contract":
        customer["latest_delivery_minute"] = 2 * 1440
    else:
        customer["locked_day"] = True
    response = client.post("/api/v1/delivery-planning/recommend", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ready_for_review"
    assert distel(result)["recommended_date"] == "2026-09-28"
    assert result["routing"]["changes"] == []


def test_warehouse_stock_is_shared_across_clients_not_reused(client, payload):
    payload["products"][0]["warehouse_available"] = "359"
    response = client.post("/api/v1/delivery-planning/recommend", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "blocked" and result["routing"] is None
    assert result["issues"][0]["code"] == "warehouse_shortage"
    assert all(c["recommended_date"] is None and c["status"] == "blocked" for c in result["clients"])
    assert sum(Decimal(c["items"][0]["quantity"]) for c in result["clients"]) == 360


def test_no_need_and_unreachable_deadline_are_not_silently_dropped(client, payload):
    for customer in payload["clients"]:
        customer["items"][0]["available_stock"] = "1000"
    result = client.post("/api/v1/delivery-planning/recommend", json=payload).json()
    assert result["status"] == "no_delivery_needed" and result["routing"] is None
    assert len(result["clients"]) == 9
    assert all(c["items"][0]["quantity"] == "0" for c in result["clients"])
    distel(payload)["items"][0]["available_stock"] = "0"  # Already below the reserve.
    result = client.post("/api/v1/delivery-planning/recommend", json=payload).json()
    assert result["status"] == "no_feasible_plan"
    assert distel(result)["status"] == "blocked" and distel(result)["recommended_date"] is None
    assert distel(result)["latest_safe_minute"] == 0


def test_fractional_units_round_exactly_and_aggregate_conservative_load(payload):
    product = payload["products"][0]
    product.update(shipment_multiple="0.1", minimum_shipment="0.35", unit_weight_kg="0.3")
    for customer in payload["clients"]:
        customer["items"][0].update(available_stock="0", reserve_units="0", daily_forecast=["0"] * 5)
    customer = payload["clients"][0]
    customer["items"][0]["daily_forecast"][0] = "0.3"
    with localcontext() as context:
        context.prec = 2
        result = recommend_deliveries(DeliveryPlanningRequest.model_validate(payload))
    line = result.clients[0].items[0]
    assert line.quantity == Decimal("0.4") and line.rounding_surplus == Decimal("0.1")
    assert result.clients[0].weight_kg == 1
    assert result.status == "ready_for_review"


def test_earliest_sku_deadline_controls_the_whole_client_delivery(client, payload):
    product = payload["products"][0].copy()
    product.update(product_id="urgent", sku="URGENT", unit_weight_kg="0.1", unit_volume_litres="0.1")
    payload["products"].append(product)
    distel(payload)["items"].append({
        "product_id": "urgent", "available_stock": "25", "reserve_units": "0",
        "daily_forecast": ["10"] * 5,
    })
    response = client.post("/api/v1/delivery-planning/recommend", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ready_for_review"
    customer = distel(result)
    assert customer["recommended_date"] == "2026-09-28"
    assert customer["latest_safe_minute"] == 2 * 1440 + 1080
    assert [line["quantity"] for line in customer["items"]] == ["40", "25"]
    assert customer["weight_kg"] == 103


@pytest.mark.parametrize("bad", ["missing_forecast", "duplicate_product", "matrix_order", "stale_stock",
                                 "negative", "unknown_product", "invalid_window", "bool_capacity",
                                 "duplicate_sku_unit"])
def test_invalid_inputs_are_422(client, payload, bad):
    if bad == "missing_forecast":
        distel(payload)["items"][0]["daily_forecast"].pop()
    elif bad == "duplicate_product":
        payload["products"].append(payload["products"][0].copy())
    elif bad == "matrix_order":
        payload["matrix"]["location_ids"].reverse()
    elif bad == "stale_stock":
        payload["stock_as_of"] = "2026-09-27"
    elif bad == "negative":
        distel(payload)["items"][0]["daily_forecast"][0] = "-1"
    elif bad == "unknown_product":
        distel(payload)["items"][0]["product_id"] = "unknown"
    elif bad == "invalid_window":
        distel(payload)["receiving_windows"] = [[700, 600]]
    elif bad == "duplicate_sku_unit":
        payload["products"].append({**payload["products"][0], "product_id": "other-unit", "unit": "piece"})
    else:
        payload["shifts"][0]["capacity_kg"] = True
    response = client.post("/api/v1/delivery-planning/recommend", json=payload)
    assert response.status_code == 422, response.text
