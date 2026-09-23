"""Real Almaty businesses/road network with explicit hypothetical delivery inputs.

Run from backend/: uv run python -m replenishment.cli.almaty_routes
The default run is offline. --fetch-roads captures a new matrix at --matrix.
"""

import argparse
import hashlib
import json
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from replenishment.routing import DAY, Costs, Delivery, VehicleShift, recommend_schedule, stock_deadline
from replenishment.routing_osrm import road_matrix_from_osrm

OSRM_BASE = "https://routing.openstreetmap.de/routed-car"
USER_AGENT = "HackAlem-Replenishment-Routing-Demo/1.0 (public-business-location research)"


def fetch_json(url: str) -> dict:
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
        payload = json.load(response)
    if payload.get("code") != "Ok":
        raise ValueError(f"OSRM request failed: {payload.get('code')}")
    return payload


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def example_inputs(locations: list[dict]):
    """Scenario declared before solving: southern outlier Monday; southwest route Thursday."""
    monday = {"electroset", "tekled", "svetotehnika", "distel"}
    forecast = tuple((day * DAY + 540, 10) for day in range(5))
    safe = stock_deadline(50, forecast, reserve_units=10)
    orders = []
    for i, location in enumerate(locations[1:], start=1):
        preferred = 0 if location["id"] in monday else 3
        days = (0, 3) if location["id"] == "distel" else (preferred,)
        orders.append(Delivery(
            id=location["id"], location=i, preferred_day=preferred,
            windows=tuple((day * DAY + 600, day * DAY + 780) for day in days),
            ready_minute=0, latest_safe_minute=safe if location["id"] == "distel" else days[-1] * DAY + 780,
            service_minutes=15, weight_kg=100, volume_litres=150,
            locked_day=location["id"] != "distel",
        ))
    shifts = tuple(VehicleShift("van_1", day, day * DAY + 600, day * DAY + 840,
                                1000, 4000, 100) for day in (0, 3))
    return tuple(orders), shifts, Costs(250, 50)


def metrics(plan) -> dict:
    if plan.cost is None:
        return {"status": plan.status}
    return {
        "status": plan.status,
        "orders_served": sum(len(r.visits) for r in plan.routes),
        "distance_km": sum(r.distance_metres for r in plan.routes) / 1000,
        "driving_minutes": sum(r.driving_minutes for r in plan.routes),
        "paid_minutes": sum(r.end_minute - r.start_minute for r in plan.routes),
        "fuel_litres_estimate": str(sum(r.fuel_litres for r in plan.routes)),
        "cost_kzt_assumed_rates": str(plan.cost),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locations", type=Path,
                        default=Path("../docs/sources/almaty-routing/locations.json"))
    parser.add_argument("--matrix", type=Path, default=Path("../docs/sources/almaty-routing/osrm-table.json"))
    parser.add_argument("--output", type=Path, default=Path("../artifacts/almaty-routing"))
    parser.add_argument("--fetch-roads", action="store_true")
    parser.add_argument("--fetch-geometry", action="store_true")
    args = parser.parse_args()
    source = json.loads(args.locations.read_text(encoding="utf-8"))
    locations = source["locations"]
    ids = [p["id"] for p in locations]
    coordinates = [[p["longitude"], p["latitude"]] for p in locations]
    if len(set(ids)) != len(ids) or len(set(map(tuple, coordinates))) != len(ids):
        raise ValueError("locations must have unique IDs and coordinates")
    if any(not 76.7 < lon < 77.1 or not 43.1 < lat < 43.4 for lon, lat in coordinates):
        raise ValueError("location outside the demonstration's Almaty bounds")
    if locations[0]["role"] != "assumed_depot_at_real_business":
        raise ValueError("first location must be the scenario depot")
    coordinate_text = ";".join(f"{lon},{lat}" for lon, lat in coordinates)
    if args.fetch_roads:
        if args.matrix.exists():
            raise ValueError("refusing to overwrite captured road data; choose a new --matrix path")
        url = f"{OSRM_BASE}/table/v1/driving/{coordinate_text}?annotations=distance,duration"
        response = fetch_json(url)
        road_matrix_from_osrm(response, len(locations))
        write_json(args.matrix, {
            "retrieved_at_utc": datetime.now(UTC).isoformat(), "request_url": url,
            "provider": "FOSSGIS public OSRM demo", "profile": "car", "live_traffic": False,
            "attribution": "Routing: OSRM/FOSSGIS. Road data: OpenStreetMap contributors, ODbL.",
            "attribution_url": "https://www.openstreetmap.org/copyright",
            "fix_map_url": "https://www.openstreetmap.org/fixthemap",
            "location_order": ids, "requested_coordinates_lon_lat": coordinates, "response": response,
        })
    capture = json.loads(args.matrix.read_text(encoding="utf-8"))
    if capture["location_order"] != ids or capture["requested_coordinates_lon_lat"] != coordinates:
        raise ValueError("captured matrix does not match location order/coordinates")
    response = capture["response"]
    road = road_matrix_from_osrm(response, len(locations))
    snapped = response.get("sources", [])
    destinations = response.get("destinations", [])
    if len(snapped) != len(locations) or len(destinations) != len(locations):
        raise ValueError("missing snapped-location evidence")
    if any(p["distance"] > 200 for p in snapped + destinations):
        raise ValueError("road snap exceeds 200 m; inspect location/road access before routing")
    orders, shifts, costs = example_inputs(locations)
    write_json(args.output / "scenario.json", {
        "horizon_start": "2026-09-28", "timezone": source["timezone"],
        "synthetic_fields": ["orders", "stock", "forecast", "receiving_windows", "fleet", "costs",
                             "depot_role"],
        "forecast_assumption": {"customer": "distel", "available_units": 50, "reserve_units": 10,
                                "daily_consumption": 10, "daily_bucket_start": "09:00"},
        "orders": [asdict(o) for o in orders], "shifts": [asdict(s) for s in shifts], "costs": asdict(costs),
    })
    variants = {
        "flexible_day": (orders, shifts),
        "stock_deadline_wednesday": (
            tuple(replace(o, latest_safe_minute=2 * DAY + 540) if o.id == "distel" else o for o in orders),
            shifts,
        ),
        "thursday_capacity_550kg": (
            orders, tuple(replace(s, capacity_kg=550) if s.day == 3 else s for s in shifts)
        ),
    }
    results, main_result = {}, None
    for name, (variant_orders, variant_shifts) in variants.items():
        result = recommend_schedule(variant_orders, variant_shifts, road, costs, time_limit_ms=2000)
        results[name] = {
            "baseline_metrics": metrics(result.baseline), "proposed_metrics": metrics(result.proposed),
            "orders": [asdict(o) for o in variant_orders], "shifts": [asdict(s) for s in variant_shifts],
            "recommendation": asdict(result),
        }
        if name == "flexible_day":
            main_result = result
        print(json.dumps({"scenario": name, "baseline": metrics(result.baseline),
                          "proposed": metrics(result.proposed),
                          "changes": [asdict(c) for c in result.changes]},
                         ensure_ascii=False))
    write_json(args.output / "results.json", {
        "created_at_utc": datetime.now(UTC).isoformat(), "locations": source,
        "road_capture_sha256": hashlib.sha256(args.matrix.read_bytes()).hexdigest(),
        "road_request_url": capture["request_url"], "road_retrieved_at_utc": capture["retrieved_at_utc"],
        "data_quality": {"locations": len(locations), "delivery_sites": len(orders), "duplicate_ids": 0,
                         "null_matrix_cells": sum(v is None for row in road.minutes for v in row),
                         "max_snap_metres": max(p["distance"] for p in snapped + destinations),
                         "traffic": "static car profile; no live traffic"},
        "scenarios": results,
    })
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": coordinate},
                 "properties": location} for location, coordinate in zip(locations, coordinates, strict=True)]
    if args.fetch_geometry and main_result:
        by_id = {p["id"]: coordinate for p, coordinate in zip(locations, coordinates, strict=True)}
        for plan_name, plan in (("baseline", main_result.baseline), ("proposed", main_result.proposed)):
            for route in plan.routes:
                points = [coordinates[0]] + [by_id[v.delivery_id] for v in route.visits] + [coordinates[0]]
                route_text = ";".join(f"{lon},{lat}" for lon, lat in points)
                query = urlencode({"overview": "full", "geometries": "geojson", "steps": "false",
                                   "continue_straight": "false"})
                url = f"{OSRM_BASE}/route/v1/driving/{route_text}?{query}"
                time.sleep(1.1)  # Respect public service's maximum of one request per second.
                geometry_response = fetch_json(url)
                write_json(args.output / f"osrm-{plan_name}-day{route.day}.json", {
                    "request_url": url, "retrieved_at_utc": datetime.now(UTC).isoformat(),
                    "response": geometry_response,
                })
                geometry = geometry_response["routes"][0]
                features.append({"type": "Feature", "geometry": geometry["geometry"], "properties": {
                    "plan": plan_name, "day": route.day, "vehicle_id": route.vehicle_id,
                    "delivery_ids": [v.delivery_id for v in route.visits],
                    "matrix_metres": route.distance_metres, "geometry_metres": geometry["distance"],
                    "geometry_driving_seconds": geometry["duration"], "provider": "OSRM/FOSSGIS",
                }})
    # Always replace this output so an offline rerun cannot expose stale route geometry.
    write_json(args.output / "routes.geojson", {
        "type": "FeatureCollection", "attribution": capture["attribution"],
        "attribution_url": capture["attribution_url"], "fix_map_url": capture["fix_map_url"],
        "geometry_status": "fetched" if args.fetch_geometry else "not_requested_points_only",
        "features": features,
    })
    write_json(args.output / "locations.geojson", {
        "type": "FeatureCollection", "features": features[:len(locations)],
    })


if __name__ == "__main__":
    main()
