# Delivery route optimization / Оптимизация маршрутов доставки

Research date: 2026-09-23. Initial single-day design. Follow-up scope and the tested
backend prototype are in [Multi-day delivery planning](MULTIDAY_ROUTING.md), including
the Monday-to-Thursday example. The 20-store experiment proposed here remains unrun.
An executed nine-site follow-up with real Almaty businesses and OSRM road data is
documented in [Almaty routing results](ALMATY_ROUTING_RESULTS.md).

## Recommendation / Рекомендация

Start with a single warehouse, a small fleet, and a daily list of deliveries. Optimize vehicle assignment and stop order together, subject to load limits, receiving hours, unloading time, and return-to-warehouse deadlines. Use road travel times between locations, then solve a capacitated vehicle routing problem with time windows (CVRPTW). Coordinates are inputs to road routing; they are not enough to schedule deliveries.

For this Python project, my proposed first experiment is OR-Tools with a saved road matrix from OSRM. This is a design recommendation, not a benchmark conclusion. Keep the experiment separate from production ingestion and the core replenishment deliverable. The existing [backlog](BACKLOG.md) identifies delivery routing as an optional extension.

Кратко: сначала моделируем один склад, 20 условных магазинов и три машины. Оптимизируем распределение заказов и порядок остановок с ограничениями по весу, объёму, времени приёмки и сменам. Время движения берём по дорожной сети. Предлагаемый инструмент — OR-Tools; дорожная матрица — OSRM. Это исследование и план эксперимента: расчёт ещё не запускался, экономия не измерена. В исходных данных нет подтверждённых адресов клиентов и достаточных данных о загрузке; синтетические входы необходимо явно обозначать.

## What the algorithms do

There are two distinct calculations:

1. **Road routing:** estimate a journey between each pair of warehouse/store locations. OSRM's Table service provides durations and distances; its Route service provides route geometry. Preserve direction: A-to-B and B-to-A can differ. A missing connection must remain unreachable, never become zero travel time. OSRM API coordinates use longitude before latitude. [OSRM documentation](https://project-osrm.org/docs/v5.24.0/api/)
2. **Fleet optimization:** choose which vehicle serves each stop and in what order. Capacity dimensions handle weight and volume independently, while scheduling accounts for time windows. [OR-Tools capacity constraints](https://developers.google.com/optimization/routing/cvrp), [time windows](https://developers.google.com/optimization/routing/vrptw)

A practical solver constructs an initial route set, then searches for improvements. In OR-Tools, cheapest insertion and guided local search are available choices; set a time budget and inspect the returned status. A time-limited solution should be described as the best feasible plan found, not a proven global optimum. Failure to find a solution within the budget is not proof of infeasibility. [OR-Tools search options](https://developers.google.com/optimization/routing/routing_options)

Geographic grouping can help explain routes, but I would not fix clusters before solving this small scenario: doing so could prevent a vehicle from serving a nearby urgent stop across an arbitrary boundary. Straight-line distance is acceptable for a clearly labeled toy example, not evidence of real delivery savings. Machine learning is unnecessary for the initial route solver; later, observed trips could improve travel and unloading estimates.

## Proposed hypothetical scenario

All values below are experimental assumptions, not partner facts.

| Input | Initial assumption |
| --- | --- |
| Area | One city; choose and record it before generating locations |
| Depot | One warehouse, same start and finish |
| Stops | 20 synthetic stores at manually checked road-accessible points |
| Vehicles | Three vans, each 1,000 kg and 6 cubic metres |
| Availability | 08:00–17:00, one trip per van, return included |
| Loading | 20 minutes at the depot before departure; assume three loading positions |
| Driver break | 30 minutes starting within 12:00–13:00; experiment assumption |
| Receiving | Each store has its own explicit window, e.g. 09:00–12:00 or 13:00–16:00 |
| Service | 10 minutes per store initially |
| Delivery quantities | Synthetic weight and volume per stop; no negative loads or returns |
| Fulfilment | Each mandatory order delivered once, whole, by one vehicle |
| Search budget | Start with 10 seconds; compare with 30 seconds on the same inputs |

Aggregate load below fleet capacity is necessary but does not establish feasibility: individual orders, geography, and receiving windows can still prevent a complete plan. Waiting at a store is allowed; service and break time count toward the shift. Define receiving windows as service-start windows for the experiment. If unloading must finish before closing, reduce the latest allowable start by the service duration.

For each stop, record stable ID, latitude, longitude, order ID, delivery weight, delivery volume, service duration, receiving window, priority, and input provenance. For each vehicle, record capacity, start/end locations, availability, break requirements, and any access restrictions. Store time values in one declared timezone and use consistent integer units at the solver boundary, e.g. seconds, grams, and litres, with conservative rounding.

## Objective and operational rules

First require all mandatory deliveries to be served within hard constraints. Among feasible plans, minimize a declared cost:

`vehicle activation cost + distance cost + paid route-duration cost`

Paid route duration includes driving, waiting, unloading, loading, and paid breaks. Specify which costs are included to avoid counting the same operating expense twice. If reliable prices are unavailable, report kilometres and minutes separately instead of inventing financial savings. Minimizing the number of vehicles first is a different business objective and can produce longer working days; do not assume it silently.

If optional deliveries may be deferred, define that policy explicitly and compare plans first by priority-weighted unserved demand, then by operating cost. A shorter plan that simply omits orders is not an improvement. Keep mandatory deliveries mandatory; offer an explicitly labeled partial-plan diagnostic when a complete plan cannot be found.

Output each vehicle's ordered stops, arrival, service start/end, waiting time, remaining load, break, return time, and route totals. Display unserved orders and verified input failures. Do not invent a definitive reason for every unserved stop: interacting constraints and search limits can make the cause uncertain.

## Tool choices

| Option | Relevant capability | Assessment for this project |
| --- | --- | --- |
| OR-Tools + road matrix | Python solver with explicit capacity/time constraints | Preferred experiment: fits the backend language and permits custom rules |
| VROOM + routing engine | Jobs, shipments, multidimensional capacity, windows, skills, breaks | Alternative if its ready-made routing model covers the requirements |
| Google Route Optimization API | Managed fleet optimization using Google Maps data | Consider when managed operations justify an external service; verify regional support, billing, and terms before adoption |

Capabilities: [OR-Tools](https://developers.google.com/optimization/routing/cvrp), [VROOM project](https://github.com/VROOM-Project/vroom), [Google Route Optimization overview](https://developers.google.com/maps/documentation/route-optimization/overview). These alternatives have not been benchmarked here.

For the first demo, save the matrix and its provenance so the run does not depend on a public demo endpoint. Record road-data/provider version where available, vehicle profile, retrieval time, and whether traffic was modeled. Do not label ordinary static estimates as live traffic. Check local road coverage and vehicle restrictions before operational use; a car profile is not evidence that a road is suitable for every delivery vehicle.

## Connection to replenishment

The intended flow is:

`approved replenishment quantities → delivery orders with destinations and loads → road matrix → fleet plan → dispatcher review`

The [data model](DATA_MODEL.md) documents missing customer IDs and unit conversions, and an empty weight field in the source workbook. Product quantities alone cannot establish delivery weight, volume, store demand, or destination. Required new inputs are verified locations, delivery orders, fleet information, service windows, and load measurements or supported SKU conversions. Never distribute aggregate historical sales among invented stores and present this as observed demand.

Initially accept explicit scenario inputs and return a plan without database changes. When integration becomes useful, keep routing arithmetic independent of ORM and HTTP, and pass plain inputs through an application composition point, following [backend architecture](../backend/ARCHITECTURE.md). Persisted plans would need versioned inputs, matrix provenance, solver settings/status, and a separate schema design/migration.

Daily routing answers how to deliver already-selected quantities. The user's follow-up
explicitly requests day selection too. The [multi-day prototype](MULTIDAY_ROUTING.md)
now selects delivery days within supplied stock-safe windows, assuming accurate demand
predictions and fixed order quantities. Full joint inventory/quantity optimization
still requires store-level inventory and demand inputs.

## Experiment and acceptance criteria

This is a proposed protocol, not executed results.

1. Freeze the synthetic orders, coordinates, capacities, windows, matrix, and scenario seed. Validate coordinate order, nonnegative quantities, matching matrix IDs, and unreachable pairs before solving.
2. Build a transparent nearest-feasible-next-stop baseline using the same fleet, depot return, service times, breaks, and load limits. Also use an actual dispatcher plan when one becomes available. Preserve baseline failures rather than hiding them.
3. Solve the same instance with OR-Tools. Independently replay both plans to verify order coverage, uniqueness, load, timing, breaks, and depot return. Include return legs in every total.
4. Compare mandatory orders served, unserved priority, kilometres, driving time, total paid time, vehicles used, peak load, waiting, and longest shift. Report percentage savings only for comparable service and valid baselines: `(baseline - candidate) / baseline × 100`, with a nonzero denominator.
5. Test clustered stores, scattered stores, a remote urgent stop, a tight receiving window, an oversized order, an unreachable stop, and insufficient fleet capacity. Check an asymmetric matrix and a route that misses its return deadline.
6. Replay with 20% longer travel and 50% longer unloading as explicitly assumed stress cases, then re-optimize. These are sensitivity checks, not forecasts or confidence intervals.

Accept the prototype only if every proposed complete plan passes independent constraint checks and its metrics can be reproduced from the saved inputs. A useful demo shows a valid baseline and candidate, explains any trade-off, and makes unserved orders visible. There is no defensible savings percentage until this comparison is actually run; synthetic gains would still need validation on real operating days.
