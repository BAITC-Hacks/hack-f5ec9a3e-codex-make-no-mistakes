# Multi-day delivery planning / Планирование дней доставки

2026-09-23. Backend prototype implemented and tested. All example locations, demand,
travel times, fuel rates, and prices below are synthetic. Frontend integration is
owned separately.

**Real-geography follow-up:** [Almaty routing results](ALMATY_ROUTING_RESULTS.md)
uses nine sourced electrical-goods businesses, a real example-depot address, and
an actual OSRM road matrix. The delivery inputs remain hypothetical; the executed
case saves 8.183 km while enforcing stock and capacity constraints.

## Decision we want to make

For each delivery, choose **day + vehicle + stop order** across the planning horizon.
Monday is a preference unless it is a firm promise. Moving a remote Monday client
to Thursday is useful when Thursday's route already passes nearby and the customer
can safely receive the goods then. If Monday is a contractual deadline or stock
will run out on Tuesday, Thursday is inadmissible regardless of the mileage saved.

This is related to inventory routing, which jointly considers replenishment timing,
quantity, and routing. Our first implementation fixes order quantities and optimizes
timing/routes within supplied safe windows. This keeps the backend small while
covering the requested Monday-to-Thursday logic. See the research chapter
[Inventory Routing in Practice](https://www2.isye.gatech.edu/people/faculty/Martin_Savelsbergh/publications/vrp.pdf).

По-русски: система выбирает день, машину и порядок остановок сразу на несколько
дней. Перенос с понедельника на четверг допустим, только если хватает запаса,
получатель разрешает этот день и маршрут укладывается в ограничения. Подтверждённое
обещание на понедельник фиксируется. Прототип возвращает рекомендацию с маршрутами
и сравнением затрат; он ничего не отправляет клиенту и не меняет заказы в БД.

## From an accurate forecast to allowed delivery times

An accurate demand forecast is assumed, as requested. The forecast must still be
combined with usable customer stock, reservations, warehouse readiness, receiving
hours, and commitments. It cannot supply these facts by itself.

1. Compute usable customer stock per SKU, excluding quantities already committed
   elsewhere. Subtract predicted consumption over time. A reserve can be zero under
   the perfect-forecast assumption, or represent an explicit service policy.
2. Find the first demand period whose consumption would take remaining stock below
   the reserve. Finish replenishment before that period starts. The helper
   `stock_deadline()` implements this conservative rule. For daily forecasts, a
   Thursday depletion period means a deadline at the **start** of Thursday's period;
   it does not justify Thursday afternoon delivery.
3. For an order with several SKUs, use the earliest deadline. Intersect it with the
   contractual deadline, warehouse readiness, and the customer's receiving windows.
4. Pass those windows and `latest_safe_minute` to the route planner. All unloading
   must finish before both closing and the stock deadline. Set `locked_day=True`
   for a confirmed day. Narrow windows also represent confirmed appointments.

The stock helper excludes future receipts, including the proposed delivery, from
its stock calculation. This is conservative and prevents counting the same shipment
twice. It accepts `(bucket_start_minute, predicted_units)` pairs. `None` means no
reserve breach within the supplied forecast; the caller must still cap delivery
windows at the known forecast horizon and contractual deadline. Forecast buckets
must cover the period being considered; missing periods do not mean zero demand.
If stock already lies below the reserve, the helper returns minute zero.

Example: usable stock 50, reserve 10, consumption 10 each day starting Monday 08:00.
The first reserve breach is Friday's demand period. A Thursday delivery can be
considered. With usable stock 25 and no reserve, the breach starts Wednesday, so
Thursday is forbidden even if its route is cheaper.

The caller must allocate warehouse stock, verify that the fixed order quantity
covers demand through the next replenishment, and exclude receiving dates that would
exceed customer storage capacity. The route planner does not infer these from SKU
sales. If several orders affect the same inventory, validate their combined inventory
trajectory before accepting a plan. Full inventory/quantity optimization is a later
extension; it is not silently approximated by this prototype.

## How the backend plans

`replenishment.routing.recommend_schedule()` uses OR-Tools. Each physical vehicle/day
is a separate route starting and ending at depot location 0. Every delivery is a
mandatory node. Its time domain is the union of its allowed windows, so the solver
can move it between days while visiting it exactly once. Separate dimensions enforce
weight, volume, and elapsed time. OR-Tools documents the underlying
[capacity and time dimensions](https://developers.google.com/optimization/routing/dimensions).

The objective in one caller-specified currency is:

`estimated fuel cost + paid route-time cost + vehicle activation cost + changed-day penalty`

- Fuel estimate: `distance_km × vehicle_ml_per_km / 1000` litres.
- Paid time: fixed shift start until depot return, including driving, waiting, and service.
- Activation cost applies once to each used vehicle/day, and not to empty routes.
- Changed-day penalty expresses schedule stability/customer inconvenience; it is not
  physical fuel expenditure. Set it to a meaningful value to avoid small improvements
  causing unnecessary rescheduling.

Fuel and time can conflict. We minimize their declared combined cost and report each
physical measure separately. Constant consumption per kilometre is a proxy, not a
measured fuel model. Research on the
[Pollution-Routing Problem](https://www.sciencedirect.com/science/article/pii/S019126151100018X)
shows why speed and payload matter when modeling fuel more accurately.

The planner solves twice: first with the preferred days fixed, then with permitted
day changes and the first solution as a starting point. If the second result is worse
or unavailable, it retains the baseline. Each complete plan is independently replayed
to check coverage, capacity, windows, readiness/deadline, return time, metrics, and cost.
Savings belong to the **whole plan**; they are not summed from conflicting suggestions
computed one order at a time.

Both runs are time-limited heuristic searches. `feasible` means a valid solution was
found, not that global optimality was proved. An unsuccessful search has no plan/cost;
orders are never silently omitted. If only the flexible run succeeds, return the valid
alternative with `savings=None`, rather than inventing a baseline comparison.

## Executed example

Three clients lie on an invented line, with one minute of travel per kilometre:
depot at 0 km, a Monday client at -10 km, the flexible client at +50 km, and a Thursday
client at +51 km. This is a deterministic test matrix, not real road data. The same
van is available Monday and Thursday from 08:00 to 12:00. Service takes 10 minutes per
client; the fuel estimate is 10 L/100 km.

| Whole-plan measure | Preferred days fixed | Flexible client moved to Thursday |
| --- | ---: | ---: |
| Distance, including depot returns | 222 km | 122 km |
| Driving time | 222 min | 122 min |
| Paid route time | 252 min | 152 min |
| Estimated fuel | 22.2 L | 12.2 L |
| Illustrative cost | 18,150 KZT | 10,650 KZT |
| Orders delivered | 3 | 3 |

The illustrative prices are 250 KZT/litre and 50 KZT/minute, with zero activation
cost and change penalty. The result saves 100 km, 100 minutes, and an estimated 10 L
in this constructed case. These are executed synthetic results, not a business
savings forecast or a benchmark against real dispatchers.

Reproduce from `backend/`:

```powershell
uv sync --frozen
uv run python -m replenishment.cli.routing_demo
uv run pytest -q tests/test_routing.py
```

The demo emits JSON with both complete plans, proposed day changes, and savings.
Tests also cover a stock deadline, locked appointment, weight/volume overload, shift
deadline, change penalty, warehouse readiness, directed roads, waiting time, unloading
completion, an unreachable return, input validation, and independent plan validation.

## Integration contract

This is a Python backend function with dataclass inputs/outputs, plus a JSON demo.
The [client delivery API](../backend/DELIVERY_PLANNING.md) now composes it with SKU
quantity calculation and exposes `POST /api/v1/delivery-planning/recommend`.
The pure route function remains independent of HTTP and persistence.

| Input | Required meaning |
| --- | --- |
| `Delivery.id`, `location` | Stable order ID and row/column index in the road matrix |
| `preferred_day` | Tentative day offset; Monday is 0 in the demo |
| `windows` | Sorted non-overlapping `(opening, closing)` minute pairs on allowed dates |
| `ready_minute` | Earliest service start allowed by preparation/allocation policy |
| `latest_safe_minute` | Latest permitted unloading completion, capped by stock and contractual needs |
| `service_minutes`, `weight_kg`, `volume_litres` | Fixed service and load; integer units, round resource demand upward |
| `locked_day` | Restrict to the preferred day even if other windows were supplied |
| `VehicleShift` | Physical vehicle ID, day, absolute start/end, load limits, fuel rate, activation cost |
| `RoadMatrix` | Directed metres and minutes; matching `None` means unreachable |
| `Costs` | Fuel price/litre, paid cost/minute, and changed-day penalty in the same currency |

All times are integer minutes since the horizon's local midnight. Retain horizon
start and timezone in the surrounding scenario. Convert conservatively: round travel,
service, load, and readiness upward, and round deadlines and receiving closes downward.
The caller must supply a consistent local calendar; DST transitions are outside the
prototype. Use named dataclass arguments in integration code to make units explicit.

`Recommendation` contains `baseline`, `proposed`, `changes`, and `savings`. A plan has
status, routes, and cost. Each route gives its vehicle/day, ordered delivery IDs,
service start/end, depot departure/return, metres, driving minutes, and fuel estimate.
`dataclasses.asdict()` yields the field structure; Decimal costs/fuel should serialize
as strings, as the demo does. A suggested change includes the old/new day and a reason
code. The comparison uses optimized fixed-day routes, not an imported historical plan.

For integration, record the input/order revision, forecast cutoff, horizon/timezone,
matrix source/profile/time, and solver version/settings alongside each result. Recheck
the input revision before applying a suggestion, because orders and available capacity
can change. The pure function itself neither approves nor executes rescheduling.

## Limits and next extension

The tested slice has one depot, fixed quantities, one trip per physical vehicle/day,
up to 200 orders, 100 shifts, and 14 days. Shifts are uninterrupted availability
intervals: depot loading and required breaks must be outside them. Use it for short
routes that fit these intervals. It is not a full-day driver-break scheduler. Warehouse
stock and driver assignments must already be allocated without conflicts.

Use road matrices from the selected routing provider for real geography. This module
performs no geocoding/network calls; the synthetic `routing_demo` does not use OSRM.
The separate `almaty_routes` CLI now provides a captured OSRM integration. A shared static matrix
does not account for day-specific traffic, vehicle road restrictions, changing payload,
or engine idling fuel. Vehicle profiles must be compatible with the supplied matrix.

For actual rolling operation, recompute a 7–14 day horizon, freeze dispatched/confirmed
commitments, and preserve the same hard deadlines. Keep all due orders inside the
planning horizon so that deferral past its edge cannot manufacture savings. Next add
forecast/stock adapters and a versioned API around this function;
add breaks, time-dependent travel and joint inventory quantities when those inputs and
operating requirements are available.
