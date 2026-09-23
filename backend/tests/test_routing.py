from dataclasses import replace
from decimal import Decimal

import pytest

from replenishment.routing import (
    DAY,
    Costs,
    Delivery,
    RoadMatrix,
    VehicleShift,
    recommend_schedule,
    stock_deadline,
    validate_plan,
)


def scenario():
    # Synthetic road kilometres on a line: depot, west, remote, Thursday neighbour.
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
    return orders, shifts, road, Costs(250, 50)


def solve(orders, shifts, road, costs):
    return recommend_schedule(orders, shifts, road, costs, time_limit_ms=100)


def test_monday_outlier_moves_to_thursday_with_measured_weekly_savings():
    orders, shifts, road, costs = scenario()
    result = solve(orders, shifts, road, costs)
    assert [(c.delivery_id, c.from_day, c.to_day) for c in result.changes] == [("remote", 0, 3)]
    assert result.baseline.cost == 18150
    assert result.proposed.cost == 10650
    assert result.savings == 7500
    assert sum(r.distance_metres for r in result.baseline.routes) == 222000
    assert sum(r.distance_metres for r in result.proposed.routes) == 122000
    assert sum(r.fuel_litres for r in result.proposed.routes) == Decimal("12.2")
    assert sum(r.end_minute - r.start_minute for r in result.proposed.routes) == 152
    validate_plan(result.proposed, orders, shifts, road, costs)


@pytest.mark.parametrize("constraint", ["stock", "promise", "weight", "volume", "shift", "penalty"])
def test_rescheduling_respects_stock_promises_capacity_shift_and_change_cost(constraint):
    orders, shifts, road, costs = scenario()
    if constraint == "stock":
        deadline = stock_deadline(25, tuple((day * DAY + 480, 10) for day in range(5)))
        assert deadline == 2 * DAY + 480
        orders = (orders[0], replace(orders[1], latest_safe_minute=deadline), orders[2])
    elif constraint == "promise":
        orders = (orders[0], replace(orders[1], locked_day=True), orders[2])
    elif constraint in ("weight", "volume"):
        field = "capacity_kg" if constraint == "weight" else "capacity_litres"
        shifts = (shifts[0], replace(shifts[1], **{field: 100}))
    elif constraint == "shift":
        shifts = (shifts[0], replace(shifts[1], end_minute=shifts[1].start_minute + 115))
    else:
        costs = replace(costs, changed_day_penalty=8000)
    result = solve(orders, shifts, road, costs)
    assert result.proposed.cost is not None
    assert not result.changes
    assert result.savings == 0


def test_readiness_can_make_preferred_day_invalid_without_fabricated_savings():
    orders, shifts, road, costs = scenario()
    orders = (orders[0], replace(orders[1], ready_minute=3 * DAY + 480), orders[2])
    result = solve(orders, shifts, road, costs)
    assert result.baseline.status == "no_eligible_window"
    assert result.proposed.status == "feasible"
    assert result.savings is None
    assert result.changes[0].reason == "feasible_alternative_within_allowed_windows"


def test_infeasible_orders_are_never_silently_dropped():
    orders, shifts, road, costs = scenario()
    orders = (replace(orders[0], weight_kg=1001), *orders[1:])
    result = solve(orders, shifts, road, costs)
    assert result.proposed.cost is None
    assert not result.proposed.routes
    assert result.savings is None


def test_directed_roads_return_leg_waiting_and_unloading_completion():
    order = Delivery("one", 1, 0, ((540, 600),), 0, 600, 10, 1, 1)
    shift = VehicleShift("van", 0, 480, 700, 10, 10, 100)
    road = RoadMatrix(((0, 5000), (25000, 0)), ((0, 5), (25, 0)))
    result = solve((order,), (shift,), road, Costs(250, 50))
    route = result.proposed.routes[0]
    assert route.distance_metres == 30000
    assert route.driving_minutes == 30
    assert route.end_minute - route.start_minute == 95  # includes 55 minutes of waiting
    assert route.visits[0].service_start_minute == 540
    assert route.visits[0].service_end_minute == 550
    late = replace(order, windows=((480, 494),), latest_safe_minute=494)
    assert solve((late,), (shift,), road, Costs(250, 50)).proposed.cost is None
    disconnected = RoadMatrix(((0, 5000), (None, 0)), ((0, 5), (None, 0)))
    assert solve((order,), (shift,), disconnected, Costs(250, 50)).proposed.cost is None


def test_forecast_deadline_is_conservative_and_respects_reserve():
    buckets = ((480, 10), (DAY + 480, 10), (2 * DAY + 480, 10))
    assert stock_deadline(30, buckets) is None
    assert stock_deadline(30, buckets, reserve_units=5) == 2 * DAY + 480
    assert stock_deadline(1, buckets, reserve_units=5) == 0
    with pytest.raises(ValueError, match="strictly increasing"):
        stock_deadline(10, ((480, 20), (0, 1)))
    with pytest.raises(ValueError, match="forecast bucket"):
        stock_deadline(10, ())


def test_validation_and_independent_replay_reject_corrupt_input_and_plan():
    orders, shifts, road, costs = scenario()
    with pytest.raises(ValueError, match="duplicate delivery"):
        solve(orders + (orders[0],), shifts, road, costs)
    with pytest.raises(ValueError, match="one shift"):
        solve(orders, shifts + (shifts[0],), road, costs)
    with pytest.raises(ValueError, match="square"):
        solve(orders, shifts, replace(road, minutes=((0,),) * 4), costs)
    with pytest.raises(ValueError, match="nonnegative integers"):
        solve(orders, shifts, road, replace(costs, fuel_price_per_litre=-1))
    with pytest.raises(ValueError, match="cost scale"):
        solve(orders, tuple(replace(s, fuel_ml_per_km=10_000_000) for s in shifts), road,
              replace(costs, fuel_price_per_litre=10_000_000))
    plan = solve(orders, shifts, road, costs).proposed
    with pytest.raises(ValueError, match="missing deliveries"):
        validate_plan(replace(plan, routes=plan.routes[:-1]), orders, shifts, road, costs)
    with pytest.raises(ValueError, match="metrics disagree"):
        broken = replace(plan.routes[0], distance_metres=0)
        validate_plan(replace(plan, routes=(broken, *plan.routes[1:])), orders, shifts, road, costs)


def test_empty_plan_has_zero_cost():
    _, shifts, road, costs = scenario()
    result = solve((), shifts, road, costs)
    assert result.proposed.status == "empty"
    assert result.savings == 0
