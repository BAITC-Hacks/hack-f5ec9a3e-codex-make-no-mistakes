# Client delivery recommendations

The backend now recommends **which SKU quantities to send to each client, on which
date, with which vehicle and in which route position**. This is outbound client
replenishment, separate from the existing supplier purchasing calculator.

## API

- `GET /api/v1/delivery-planning/demo-input`: a complete request using the captured
  real Almaty locations/road matrix and explicitly synthetic product, stock and
  forecast inputs. It reads the repository's saved fixtures; no network is needed.
- `POST /api/v1/delivery-planning/recommend`: validates the request, calculates
  quantities, checks shared warehouse availability, and optimizes the delivery plan.
  It does not access the database or a routing provider, reserve stock, change orders
  or dispatch a delivery. Full input/output schemas are available in `/docs`.

With the backend running on port 8000, this PowerShell example exercises both:

```powershell
$deliveryInput = Invoke-RestMethod http://127.0.0.1:8000/api/v1/delivery-planning/demo-input
$deliveryJson = $deliveryInput | ConvertTo-Json -Depth 100
$deliveryResult = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/delivery-planning/recommend -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($deliveryJson))
$deliveryResult.clients | Select-Object name,recommended_date,vehicle_id,reason
$deliveryResult.clients | ForEach-Object { $_.items | Select-Object sku,quantity,unit }
```

The demo recommends 40 synthetic electrical-product packs per site, then proposes
moving DisTEL from Monday 2026-09-28 to Thursday 2026-10-01. Its road costs reproduce
the earlier Almaty example. These demo quantities are not actual orders from those
businesses. For real operation, post actual client/SKU forecasts and opening stock.

## Inputs and units

| Field | Meaning |
| --- | --- |
| `input_revision`, `forecast_reference`, `inventory_reference` | Caller-provided revision/source identifiers echoed for review; retain the complete request with its response |
| `basis` | `observed`, `assumed` or `synthetic`; supplied by the caller, not independently verified |
| `horizon_start`, `horizon_days`, `timezone` | Local start date and 1–14 days of planning; offset changes within the horizon are rejected |
| `stock_as_of` | Must equal `horizon_start`; stock is opening available stock before the forecast's first consumption |
| `demand_start_minute` | Local minute at which each daily demand bucket starts; defaults to midnight, conservatively requiring delivery before that day |
| `depot_id` | Start and return location; must be matrix row/column zero |
| `products` | Stable product ID, supplier/SKU/unit, confirmed unallocated warehouse quantity, weight/volume per unit, shipment multiple and optional minimum |
| `clients[].items` | Product ID, client available stock, reserve, and exactly one nonnegative forecast quantity for every horizon day; omitted days are invalid, not zero |
| `clients[].receiving_windows` | Allowed pairs of integer minutes since horizon midnight; interpreted as permission to use these dates |
| `preferred_day`, `locked_day` | Day offset from horizon start and whether that day is a hard commitment |
| `latest_delivery_minute` | Optional contractual unloading-completion deadline; combined with stock deadlines |
| `service_minutes` | Unloading/service duration for the whole client shipment |
| `shifts` | One uninterrupted shift per vehicle/day, depot departure/return limits, kg/litre limits, fuel rate and optional activation cost |
| `costs`, `currency` | Integer fuel price per litre, paid cost per minute and optional changed-day penalty, in the same currency |
| `matrix` | Directed integer `metres` and `minutes`, plus ordered location IDs, provider/profile and aware capture timestamp; matching `null` entries mean unreachable |

All stock, forecasts and shipment rules for a product use its declared unit. Supply
conversions before calling; the endpoint does not guess pack/metre/piece conversions.
Each supplier/SKU appears once in `products`, in that single normalized unit.
Weights and volume are summed from the recommended quantities and then rounded up
to integer kg/litres for the solver. Decimal quantities/costs serialize as strings.
Matrix IDs must contain exactly the depot and all clients, even clients eventually
found to need no shipment. Matrix values must already be rounded conservatively;
the existing `routing_osrm.road_matrix_from_osrm()` adapter converts OSRM responses.

The API does not invent customer-level demand from supplier-level totals in the
source workbooks. Those sources do not establish each client's opening stock,
product demand, address or receiving permissions. A forecast adapter should populate
this explicit contract when those inputs exist.

## Calculation and safeguards

For each client/SKU:

```text
net_need = max(0, sum(daily_forecast) + reserve_units - available_stock)
quantity = 0 when net_need = 0
quantity = ceil(max(net_need, minimum_shipment) / shipment_multiple) * shipment_multiple otherwise
```

Stock is simulated without the new shipment to find the first demand bucket that
would leave less than the reserve. The shipment must finish unloading before that
bucket starts. The earliest SKU deadline constrains the whole client shipment. If
stock is already below reserve, its deadline is minute zero and ordinary later
delivery cannot be presented as safe; the result requires intervention.

Quantities cover the entire supplied horizon and stay fixed while dates/routes are
optimized. Delaying a delivery cannot hide due demand beyond the horizon. Minimums
and multiples can create a reported `rounding_surplus`. Products with no need do not
generate an order merely because a minimum shipment exists.

Warehouse availability is checked across **all** clients after rounding. If required
stock exceeds availability, the result is blocked with a `warehouse_shortage` issue;
the endpoint does not silently prioritize some clients or reuse the same inventory.
All nonzero client shipments are mandatory for the route solver. It compares
optimized preferred-day routes against a plan allowing permitted day changes.
Confirmed days, receiving windows, contractual/stock deadlines, loads and depot
return constraints remain hard limits.

## Response handling

| Overall `status` | Frontend meaning |
| --- | --- |
| `ready_for_review` | Every needed shipment is scheduled; display SKU quantities, date, vehicle and service times |
| `no_delivery_needed` | Every supplied client is covered through the forecast horizon; quantities are zero |
| `blocked` | Warehouse availability is insufficient; show computed needs and `issues`, without promised dates |
| `no_feasible_plan` | No complete route was found within the constraints/search budget; show needs and route status, without claiming impossibility was proved |

Each client stays in the response, including `no_delivery_needed` clients. Planned
clients have `recommended_date`, `vehicle_id`, `service_start_minute`,
`service_end_minute` and a reason code. A moved client receives
`lower_weekly_cost_within_allowed_windows`, or `feasible_alternative_within_allowed_windows`
when no baseline was found. `routing` retains both plans, ordered visits, whole-plan
costs, changes and savings. Savings are `null` if there is no valid baseline.
Never display blocked quantities as already allocated or approved shipments.

Invalid inputs return HTTP 422; missing demo fixtures return 503. Solver search is
bounded to at most 5 seconds per solve, two solves per request. Limits are 200
clients, 200 products, 2,000 client/product rows and 100 shifts. The endpoint is a
synchronous FastAPI worker function, keeping solver work off the async event loop.

## Scope and checks

One depot and one shipment per client are modeled. All warehouse quantities must be
available before departure. Other client receipts, shelf/storage limits, changing
payload fuel, vehicle-specific roads, departure-time traffic and driver breaks are
not modeled. The request's receiving windows and matrix must already reflect the
vehicle/customer restrictions that apply. Recheck stock, forecasts and commitments
before a later approval/dispatch operation; this preview performs no reservation or
revision-locking transaction. It adds no persistence schema or frontend changes.

From `backend/`:

```powershell
uv run pytest -q tests/test_delivery_planning.py tests/test_routing.py tests/test_routing_osrm.py
uv run ruff check .
uv run lint-imports
```

Tests exercise the actual application routes without database access, the Almaty
day change, stock/capacity/commitment guards, multi-SKU deadlines, shared warehouse
stock, fractional rounding, zero need, impossible deadlines and invalid requests.

See [routing methodology](../docs/MULTIDAY_ROUTING.md) and
[Almaty source/result audit](../docs/ALMATY_ROUTING_RESULTS.md).
