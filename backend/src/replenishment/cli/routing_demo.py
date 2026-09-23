"""Run the synthetic Monday-to-Thursday example: python -m replenishment.cli.routing_demo."""

import json
from dataclasses import asdict

from replenishment.routing import DAY, Costs, Delivery, RoadMatrix, VehicleShift, recommend_schedule


def main() -> None:
    positions = (0, -10, 50, 51)
    minutes = tuple(tuple(abs(a - b) for b in positions) for a in positions)
    road = RoadMatrix(tuple(tuple(d * 1000 for d in row) for row in minutes), minutes)
    monday, thursday = (480, 720), (3 * DAY + 480, 3 * DAY + 720)
    orders = (
        Delivery("west", 1, 0, (monday,), 0, monday[1], 10, 100, 100, True),
        Delivery("remote", 2, 0, (monday, thursday), 0, thursday[1], 10, 100, 100),
        Delivery("east", 3, 3, (thursday,), 0, thursday[1], 10, 100, 100, True),
    )
    shifts = tuple(VehicleShift("van", day, day * DAY + 480, day * DAY + 720, 1000, 1000, 100)
                   for day in (0, 3))
    costs = Costs(fuel_price_per_litre=250, paid_cost_per_minute=50)
    result = recommend_schedule(orders, shifts, road, costs)
    print(json.dumps({
        "synthetic": True,
        "horizon_start": "2026-09-28",
        "time_basis": "minutes from horizon midnight in one local timezone",
        "road_basis": "invented line distances, one minute per kilometre; no road API",
        "currency": "KZT; illustrative rates, not researched prices",
        "costs": asdict(costs),
        "recommendation": asdict(result),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
