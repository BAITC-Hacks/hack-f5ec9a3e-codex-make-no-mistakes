"""Explicitly loaded Almaty example: real locations/roads, synthetic client forecasts."""

import json
from pathlib import Path

from replenishment.delivery_planning import DeliveryPlanningRequest
from replenishment.routing import DAY
from replenishment.routing_osrm import road_matrix_from_osrm


def almaty_demo_input() -> DeliveryPlanningRequest:
    source = Path(__file__).resolve().parents[3] / "docs/sources/almaty-routing"
    locations = json.loads((source / "locations.json").read_text(encoding="utf-8"))["locations"]
    capture = json.loads((source / "osrm-table.json").read_text(encoding="utf-8"))
    ids = [p["id"] for p in locations]
    if (capture["location_order"] != ids or capture["requested_coordinates_lon_lat"]
            != [[p["longitude"], p["latitude"]] for p in locations]):
        raise ValueError("Almaty fixture coordinates/order do not match the captured road matrix")
    road = road_matrix_from_osrm(capture["response"], len(locations))
    monday = {"electroset", "tekled", "svetotehnika", "distel"}
    clients = []
    for location in locations[1:]:
        flexible = location["id"] == "distel"
        day = 0 if location["id"] in monday else 3
        forecast = [0] * 5
        forecast[day] = 40
        if flexible:
            forecast = [10, 10, 10, 10, 40]
        clients.append({
            "client_id": location["id"], "name": location["name"], "address": location["address"],
            "preferred_day": day, "locked_day": not flexible, "service_minutes": 15,
            "receiving_windows": [[d * DAY + 600, d * DAY + 780] for d in ((0, 3) if flexible else (day,))],
            "items": [{"product_id": "example-electrical-pack", "available_stock": "50" if flexible else "0",
                       "reserve_units": "10" if flexible else "0", "daily_forecast": forecast}],
        })
    return DeliveryPlanningRequest.model_validate({
        "input_revision": "almaty-delivery-demo-v1", "basis": "synthetic",
        "forecast_reference": "Synthetic client demand for demonstration; not actual customer orders",
        "inventory_reference": "Synthetic opening client stock and unallocated warehouse stock",
        "horizon_start": "2026-09-28", "horizon_days": 5, "stock_as_of": "2026-09-28",
        "timezone": "Asia/Almaty", "demand_start_minute": 1080,
        "depot_id": ids[0], "currency": "KZT",
        "products": [{
            "product_id": "example-electrical-pack", "supplier": "Example supplier",
            "sku": "DEMO-PACK", "name": "Example electrical product pack (synthetic)", "unit": "pack",
            "warehouse_available": "1000", "unit_weight_kg": "2.5", "unit_volume_litres": "3.75",
            "shipment_multiple": "1", "minimum_shipment": "0",
        }],
        "clients": clients,
        "shifts": [{"vehicle_id": "van_1", "day": day, "start_minute": day * DAY + 600,
                    "end_minute": day * DAY + 840, "capacity_kg": 1000, "capacity_litres": 4000,
                    "fuel_ml_per_km": 100} for day in (0, 3)],
        "costs": {"fuel_price_per_litre": 250, "paid_cost_per_minute": 50, "changed_day_penalty": 0},
        "matrix": {"location_ids": ids, "metres": road.metres, "minutes": road.minutes,
                   "provider": capture["provider"], "profile": capture["profile"],
                   "captured_at": capture["retrieved_at_utc"]},
    })


if __name__ == "__main__":
    print(almaty_demo_input().model_dump_json(indent=2))
