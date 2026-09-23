"""Multi-day delivery suggestions from explicit, stock-safe inputs; no I/O or writes.

Times are integer minutes from midnight at the start of the planning horizon.
Windows require unloading to FINISH by closing time. Orders are never dropped.
"""

from dataclasses import dataclass
from decimal import Decimal

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

DAY = 1440
MONEY_SCALE = 1_000_000


@dataclass(frozen=True)
class Delivery:
    id: str
    location: int
    preferred_day: int
    windows: tuple[tuple[int, int], ...]
    ready_minute: int
    latest_safe_minute: int
    service_minutes: int
    weight_kg: int
    volume_litres: int
    locked_day: bool = False


@dataclass(frozen=True)
class VehicleShift:
    vehicle_id: str
    day: int
    start_minute: int
    end_minute: int
    capacity_kg: int
    capacity_litres: int
    fuel_ml_per_km: int
    activation_cost: int = 0


@dataclass(frozen=True)
class RoadMatrix:
    metres: tuple[tuple[int | None, ...], ...]
    minutes: tuple[tuple[int | None, ...], ...]


@dataclass(frozen=True)
class Costs:
    fuel_price_per_litre: int
    paid_cost_per_minute: int
    changed_day_penalty: int = 0


@dataclass(frozen=True)
class Visit:
    delivery_id: str
    service_start_minute: int
    service_end_minute: int


@dataclass(frozen=True)
class Route:
    vehicle_id: str
    day: int
    visits: tuple[Visit, ...]
    start_minute: int
    end_minute: int
    distance_metres: int
    driving_minutes: int
    fuel_litres: Decimal


@dataclass(frozen=True)
class Plan:
    status: str
    routes: tuple[Route, ...] = ()
    cost: Decimal | None = None


@dataclass(frozen=True)
class DayChange:
    delivery_id: str
    from_day: int
    to_day: int
    reason: str = "lower_weekly_cost_within_allowed_windows"


@dataclass(frozen=True)
class Recommendation:
    baseline: Plan
    proposed: Plan
    changes: tuple[DayChange, ...]
    savings: Decimal | None


def _nonnegative(*values: int) -> None:
    if any(type(value) is not int or not 0 <= value <= 10_000_000 for value in values):
        raise ValueError("expected nonnegative integers no greater than 10000000")


def stock_deadline(
    available_units: int, demand_buckets: tuple[tuple[int, int], ...], *, reserve_units: int = 0
) -> int | None:
    """Conservative arrival deadline: start of first bucket that would breach reserve.

    A bucket is (start_minute, predicted consumption). No future receipts are assumed.
    None means covered within the supplied forecast, not beyond its horizon.
    Call per SKU and take the earliest non-None deadline for the whole delivery.
    """
    _nonnegative(available_units, reserve_units)
    if not demand_buckets:
        raise ValueError("at least one forecast bucket is required")
    previous = -1
    for minute, units in demand_buckets:
        _nonnegative(minute, units)
        if minute <= previous:
            raise ValueError("demand buckets must be strictly increasing")
        previous = minute
    if available_units < reserve_units:
        return 0
    remaining = available_units
    for minute, units in demand_buckets:
        remaining -= units
        if remaining < reserve_units:
            return minute
    return None


def _windows(order: Delivery, fixed_days: bool) -> list[tuple[int, int]]:
    result = []
    for opening, closing in order.windows:
        if (fixed_days or order.locked_day) and opening // DAY != order.preferred_day:
            continue
        lower = max(opening, order.ready_minute)
        upper = min(min(closing, order.latest_safe_minute) - order.service_minutes,
                    (opening // DAY + 1) * DAY - 1)
        if lower <= upper:
            result.append((lower, upper))
    return result


def validate_inputs(
    orders: tuple[Delivery, ...], shifts: tuple[VehicleShift, ...], road: RoadMatrix, costs: Costs,
) -> None:
    """Validate the shared solver contract without running a search."""
    if len(orders) > 200 or not 1 <= len(shifts) <= 100:
        raise ValueError("prototype requires at most 200 orders and 1..100 vehicle shifts")
    _nonnegative(costs.fuel_price_per_litre, costs.paid_cost_per_minute, costs.changed_day_penalty)
    if costs.fuel_price_per_litre + costs.paid_cost_per_minute == 0:
        raise ValueError("at least one fuel/time cost must be positive")
    size = len(road.metres)
    if size < 1 or len(road.minutes) != size:
        raise ValueError("road matrices must be nonempty and the same size")
    for i, (distances, times) in enumerate(zip(road.metres, road.minutes, strict=True)):
        if len(distances) != size or len(times) != size:
            raise ValueError("road matrices must be square")
        for j, (distance, minutes) in enumerate(zip(distances, times, strict=True)):
            if (distance is None) != (minutes is None):
                raise ValueError("unreachable arcs must be None in both matrices")
            if distance is not None:
                _nonnegative(distance, minutes)
            if i == j and (distance != 0 or minutes != 0):
                raise ValueError("matrix diagonal must be zero")
    seen = set()
    for shift in shifts:
        _nonnegative(shift.day, shift.start_minute, shift.end_minute, shift.capacity_kg,
                     shift.capacity_litres, shift.fuel_ml_per_km, shift.activation_cost)
        if not shift.vehicle_id or (shift.vehicle_id, shift.day) in seen:
            raise ValueError("one shift per physical vehicle per day is required")
        seen.add((shift.vehicle_id, shift.day))
        if not shift.day * DAY <= shift.start_minute < shift.end_minute <= (shift.day + 1) * DAY:
            raise ValueError("shift must fit within its declared day")
        if shift.day >= 14 or shift.fuel_ml_per_km == 0:
            raise ValueError("prototype horizon is 14 days and fuel consumption must be positive")
    if len({order.id for order in orders}) != len(orders):
        raise ValueError("duplicate delivery IDs")
    for order in orders:
        _nonnegative(order.location, order.preferred_day, order.ready_minute, order.latest_safe_minute,
                     order.service_minutes, order.weight_kg, order.volume_litres)
        if not order.id or not 0 <= order.location < size or order.preferred_day >= 14:
            raise ValueError("invalid delivery ID, location or preferred day")
        if type(order.locked_day) is not bool:
            raise ValueError("locked_day must be a boolean")
        if order.ready_minute > order.latest_safe_minute or order.latest_safe_minute > 14 * DAY:
            raise ValueError("invalid ready/deadline interval")
        previous_close = -1
        for opening, closing in order.windows:
            _nonnegative(opening, closing)
            if not previous_close < opening < closing <= 14 * DAY:
                raise ValueError("windows must be ordered, disjoint and within 14 days")
            if opening // DAY != (closing - 1) // DAY:
                raise ValueError("receiving windows cannot cross midnight")
            previous_close = closing
    largest_distance = max((d for row in road.metres for d in row if d is not None), default=0)
    bound = ((len(orders) + len(shifts)) * largest_distance * max(s.fuel_ml_per_km for s in shifts)
             * costs.fuel_price_per_litre
             + MONEY_SCALE * (len(shifts) * DAY * costs.paid_cost_per_minute
                              + sum(s.activation_cost for s in shifts)
                              + len(orders) * costs.changed_day_penalty))
    if bound >= 2**60:
        raise ValueError("cost scale too large for the integer solver")


def _solve(
    orders: tuple[Delivery, ...], shifts: tuple[VehicleShift, ...], road: RoadMatrix,
    costs: Costs, fixed_days: bool, time_limit_ms: int, seed: Plan | None = None,
) -> Plan:
    if not orders:
        return Plan("empty", cost=Decimal(0))
    allowed = [_windows(order, fixed_days) for order in orders]
    if any(not windows for windows in allowed):
        return Plan("no_eligible_window")
    manager = pywrapcp.RoutingIndexManager(len(orders) + 1, len(shifts), 0)
    routing = pywrapcp.RoutingModel(manager)
    locations = [0] + [order.location for order in orders]
    service = [0] + [order.service_minutes for order in orders]
    horizon = 14 * DAY

    def transit(a, b):
        source, destination = manager.IndexToNode(a), manager.IndexToNode(b)
        travel = road.minutes[locations[source]][locations[destination]]
        return horizon + 1 if travel is None else service[source] + travel

    routing.AddDimension(routing.RegisterTransitCallback(transit), horizon, horizon, False, "Time")
    time = routing.GetDimensionOrDie("Time")
    for attribute, capacity in (("weight_kg", "capacity_kg"), ("volume_litres", "capacity_litres")):
        demands = [0] + [getattr(order, attribute) for order in orders]
        callback = routing.RegisterUnaryTransitCallback(lambda i, d=demands: d[manager.IndexToNode(i)])
        routing.AddDimensionWithVehicleCapacity(callback, 0, [getattr(s, capacity) for s in shifts],
                                              True, attribute)
    for node, windows in enumerate(allowed, start=1):
        cumulative = time.CumulVar(manager.NodeToIndex(node))
        cumulative.SetRange(windows[0][0], windows[-1][1])
        for (_, end), (start, _) in zip(windows, windows[1:], strict=False):
            cumulative.RemoveInterval(end + 1, start - 1)
        routing.AddVariableMinimizedByFinalizer(cumulative)

    for vehicle, shift in enumerate(shifts):
        def arc_cost(a, b, s=shift):
            source, destination = manager.IndexToNode(a), manager.IndexToNode(b)
            distance = road.metres[locations[source]][locations[destination]]
            fuel_cost = (distance or 0) * s.fuel_ml_per_km * costs.fuel_price_per_litre
            changed = source > 0 and orders[source - 1].preferred_day != s.day
            return fuel_cost + int(changed) * costs.changed_day_penalty * MONEY_SCALE

        routing.SetArcCostEvaluatorOfVehicle(routing.RegisterTransitCallback(arc_cost), vehicle)
        routing.SetFixedCostOfVehicle(shift.activation_cost * MONEY_SCALE, vehicle)
        time.SetSpanCostCoefficientForVehicle(costs.paid_cost_per_minute * MONEY_SCALE, vehicle)
        time.CumulVar(routing.Start(vehicle)).SetValue(shift.start_minute)
        time.CumulVar(routing.End(vehicle)).SetRange(shift.start_minute, shift.end_minute)
        routing.AddVariableMinimizedByFinalizer(time.CumulVar(routing.End(vehicle)))

    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    parameters.time_limit.FromMilliseconds(time_limit_ms)
    initial = None
    if seed and seed.cost is not None:
        node_ids = {order.id: i + 1 for i, order in enumerate(orders)}
        seed_routes = {
            (r.vehicle_id, r.day): [node_ids[v.delivery_id] for v in r.visits] for r in seed.routes
        }
        initial = routing.ReadAssignmentFromRoutes(
            [seed_routes.get((s.vehicle_id, s.day), []) for s in shifts], True
        )
    solution = (routing.SolveFromAssignmentWithParameters(initial, parameters) if initial
                else routing.SolveWithParameters(parameters))
    if solution is None:
        status = routing_enums_pb2.RoutingSearchStatus.DESCRIPTOR.enum_types_by_name["Value"].values_by_number
        return Plan(status[routing.status()].name.lower())

    routes = []
    for vehicle, shift in enumerate(shifts):
        if not routing.IsVehicleUsed(solution, vehicle):
            continue
        visits, distance, driving = [], 0, 0
        index = routing.Start(vehicle)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node:
                start = solution.Min(time.CumulVar(index))
                visits.append(Visit(orders[node - 1].id, start, start + service[node]))
            following = solution.Value(routing.NextVar(index))
            source, destination = locations[node], locations[manager.IndexToNode(following)]
            distance += road.metres[source][destination]
            driving += road.minutes[source][destination]
            index = following
        routes.append(Route(shift.vehicle_id, shift.day, tuple(visits), shift.start_minute,
                            solution.Min(time.CumulVar(index)), distance, driving,
                            Decimal(distance * shift.fuel_ml_per_km) / MONEY_SCALE))
    # ponytail: static road matrix and constant fuel/km; calibrate with real fleet telemetry later.
    plan = Plan("feasible", tuple(routes), Decimal(solution.ObjectiveValue()) / MONEY_SCALE)
    validate_plan(plan, orders, shifts, road, costs, fixed_days=fixed_days)
    return plan


def validate_plan(
    plan: Plan, orders: tuple[Delivery, ...], shifts: tuple[VehicleShift, ...], road: RoadMatrix,
    costs: Costs, *, fixed_days: bool = False,
) -> None:
    """Replay a complete plan independently of the solver; raise on any inconsistency."""
    order_by_id = {order.id: order for order in orders}
    shift_by_id = {(shift.vehicle_id, shift.day): shift for shift in shifts}
    served, used = set(), set()
    total_cost = Decimal(0)
    for route in plan.routes:
        key = (route.vehicle_id, route.day)
        if key in used or key not in shift_by_id or not route.visits:
            raise ValueError("invalid or duplicate vehicle route")
        used.add(key)
        shift = shift_by_id[key]
        if route.start_minute != shift.start_minute or route.end_minute > shift.end_minute:
            raise ValueError("shift boundary violation")
        previous_location, clock = 0, route.start_minute
        distance = driving = weight = volume = changes = 0
        for visit in route.visits:
            if visit.delivery_id in served or visit.delivery_id not in order_by_id:
                raise ValueError("duplicate or unknown delivery")
            served.add(visit.delivery_id)
            order = order_by_id[visit.delivery_id]
            travel = road.minutes[previous_location][order.location]
            if travel is None or visit.service_start_minute < clock + travel:
                raise ValueError("unreachable or impossible visit timing")
            if (visit.service_end_minute != visit.service_start_minute + order.service_minutes
                    or visit.service_start_minute // DAY != route.day
                    or not any(a <= visit.service_start_minute <= b for a, b in _windows(order, fixed_days))):
                raise ValueError("delivery window violation")
            distance += road.metres[previous_location][order.location]
            driving += travel
            weight += order.weight_kg
            volume += order.volume_litres
            changes += int(order.preferred_day != route.day)
            previous_location, clock = order.location, visit.service_end_minute
        travel = road.minutes[previous_location][0]
        if travel is None or route.end_minute < clock + travel:
            raise ValueError("impossible depot return")
        distance += road.metres[previous_location][0]
        driving += travel
        fuel = Decimal(distance * shift.fuel_ml_per_km) / MONEY_SCALE
        if weight > shift.capacity_kg or volume > shift.capacity_litres:
            raise ValueError("vehicle capacity violation")
        if (distance, driving, fuel) != (route.distance_metres, route.driving_minutes, route.fuel_litres):
            raise ValueError("route metrics disagree with matrix")
        total_cost += (fuel * costs.fuel_price_per_litre + shift.activation_cost
                       + (route.end_minute - route.start_minute) * costs.paid_cost_per_minute
                       + changes * costs.changed_day_penalty)
    if served != set(order_by_id) or total_cost != plan.cost:
        raise ValueError("missing deliveries or inconsistent objective")


def recommend_schedule(
    orders: tuple[Delivery, ...], shifts: tuple[VehicleShift, ...], road: RoadMatrix, costs: Costs,
    *, time_limit_ms: int = 1000,
) -> Recommendation:
    """Compare optimized preferred-day routes with a jointly optimized multi-day plan.

    All orders are mandatory, one trip per physical vehicle/day, depot is location 0.
    Existing confirmed appointments must have locked_day=True or restrictive windows.
    This prototype models uninterrupted shifts; breaks/loading must be budgeted outside
    these shifts. No dispatch, customer contact, inventory write or approval occurs.
    """
    validate_inputs(orders, shifts, road, costs)
    _nonnegative(time_limit_ms)
    if not 1 <= time_limit_ms <= 60_000:
        raise ValueError("time_limit_ms must be in 1..60000 per solve")
    baseline = _solve(orders, shifts, road, costs, True, time_limit_ms)
    proposed = _solve(orders, shifts, road, costs, False, time_limit_ms, baseline)
    if baseline.cost is not None and (proposed.cost is None or proposed.cost >= baseline.cost):
        proposed = baseline
    preferred = {order.id: order.preferred_day for order in orders}
    savings = (baseline.cost - proposed.cost
               if baseline.cost is not None and proposed.cost is not None else None)
    reason = ("lower_weekly_cost_within_allowed_windows" if savings is not None
              else "feasible_alternative_within_allowed_windows")
    changes = tuple(DayChange(visit.delivery_id, preferred[visit.delivery_id], route.day, reason)
                    for route in proposed.routes for visit in route.visits
                    if preferred[visit.delivery_id] != route.day)
    return Recommendation(baseline, proposed, changes, savings)
