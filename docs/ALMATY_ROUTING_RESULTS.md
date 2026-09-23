# Almaty: delivery-day optimization on real roads

Run date: 2026-09-23. **Nine real candidate delivery sites, one real business used as
an example depot, and a fetched road matrix.** The delivery orders and operating
conditions are hypothetical. This demonstrates the decision logic; it does not
estimate savings for an existing distribution operation.

The executed scenario moves **DisTEL from Monday 28 September to Thursday 1 October
2026**, reducing total travel from **74.614 km to 66.431 km (10.97%)** while serving
all nine deliveries. A Wednesday stock deadline or insufficient Thursday capacity
prevents the move. No frontend, HTTP endpoint, customer notification, or database
rescheduling was added.

## Where the data comes from

**Businesses and coordinates:** public company contact pages, their branch map
markers, and public 2GIS business listings. There is no Places API or paid geocoding
API behind this sample. The [location fixture](sources/almaty-routing/locations.json)
records an address, business source, coordinate source, coordinate evidence, and
category-fit rationale for every site. These are potential electrical-goods outlets
or distributors, not verified customers or confirmed prospective buyers. This is a
purposive sample, not an exhaustive Almaty business directory.

| Role / ID | Business | Published Almaty address |
| --- | --- | --- |
| Example depot | Электрокомплекс | Рыскулова, 39 |
| `electroset` | Электросеть | Масанчи, 5 |
| `elkom_tole_bi` | Электрокомплекс | Толе би, 211 |
| `electrika` | Electrika.kz | Прокофьева, 112, Тастак |
| `eltech` | ELTECH Ltd | Нурпеисова, 2а; map lists 2 |
| `tekled` | TEKLED | Рыскулова, 99; another official page lists 99/1 |
| `svetotehnika` | Светотехника | Рыскулова, 103/21 |
| `distel` | DisTEL | Хан-Тенгри, 55В |
| `otvertka` | Отвертка.kz pickup site | О. Жандосова, 2Б, угол Яссауи |
| `220volt` | 220 Volt | Толе би, 180 |

Examples of product fit: [Электросеть](https://electroset.kz/company/) lists IEK and
Systeme Electric; [DisTEL](https://distel-almaty.kz/about_us) describes electrical and
telecom products; [ELTECH](https://www.eltech.kz/en/about) supplies industrial
electrical equipment. Lighting retailers are included by category fit, without
assuming they sell a particular supplier's brands. The real Электрокомплекс address
is our chosen example start/end point; its use as our warehouse is hypothetical.

**Road distances, times and shapes:** the
[FOSSGIS public OSRM service](https://routing.openstreetmap.de/about.html), using
OpenStreetMap road data and the car profile. No API key was required for this small
demonstration.

```text
Base:  https://routing.openstreetmap.de/routed-car
Table: /table/v1/driving/{longitude,latitude;...}?annotations=distance,duration
Route: /route/v1/driving/{longitude,latitude;...}?overview=full&geometries=geojson&steps=false&continue_straight=false
```

The Table call fetched all 100 directed origin/destination cells for the ten
locations at **2026-09-23 11:09:58 UTC**. The exact URL, coordinate order, attribution,
retrieval time, and unmodified response are in
[osrm-table.json](sources/almaty-routing/osrm-table.json). Four subsequent Route
calls captured the road shapes for the two baseline and two proposed routes.
Calls respect the service's one-request-per-second limit and identify the client.
The response did not include a map-data version; retrieval time is not a claim
about the exact age of the underlying map.

OSRM supplies travel costs; **OR-Tools chooses delivery days and stop order**.
Table distances follow the service's fastest paths, not necessarily the shortest
possible paths. The optimizer minimizes assumed fuel cost plus paid elapsed time,
with support for vehicle activation and day-change penalties. The public service is
used for this small captured experiment, not as an operational service guarantee.
[OSRM API semantics](https://github.com/Project-OSRM/osrm-backend/blob/master/docs/http.md)

## The hypothetical operating inputs

The horizon starts Monday 2026-09-28, in `Asia/Almaty`. One van is available Monday
and Thursday, 10:00–14:00, with capacity 1,000 kg / 4,000 litres. Each delivery weighs
100 kg, occupies 150 litres, takes 15 minutes, and has a 10:00–13:00 receiving window.
All goods are assumed ready. Fuel consumption is assumed to be 10 L/100 km; fuel
price is 250 KZT/L and paid time 50 KZT/minute. These are illustrative inputs, not
researched prices or measured vehicle performance. Activation and change penalties
are zero in this demonstration.

- Monday originally serves Электросеть, TEKLED, Светотехника and DisTEL.
- Thursday originally serves ELTECH, Отвертка, Электрокомплекс Толе би, Electrika and 220 Volt.
- Only DisTEL permits either day. The other eight delivery days are fixed.
- DisTEL's assumed stock is 50 units, its reserve 10, and forecast consumption
  10/day at the start of the 09:00 demand bucket. The first reserve breach is Friday
  09:00, so Thursday unloading can finish safely before that deadline.

This deliberately creates the user's requested example: a southern Monday stop
that may fit into Thursday's southwest route. The [scenario snapshot](../experiments/routing/20260923T111348Z-almaty-road-v1/scenario.json)
makes these assumptions inspectable. An accurate forecast alone is insufficient:
actual stock, customer permission to change days, load, service times, receiving
hours and vehicle availability are still required in operation.

## Results

Both columns optimize stop order. The comparison therefore measures the benefit of
allowing a delivery-day change, rather than comparing with a deliberately bad stop
sequence. Both plans start and finish at the same depot on each day.

| Whole-plan measure | Preferred days fixed | DisTEL allowed to change day | Reduction |
| --- | ---: | ---: | ---: |
| Orders delivered | 9 | 9 | — |
| Road distance | 74.614 km | 66.431 km | 8.183 km / 10.97% |
| Scheduled driving time | 93 min | 84 min | 9 min |
| Paid time, including unloading and waiting | 228 min | 219 min | 9 min |
| Estimated fuel | 7.4614 L | 6.6431 L | 0.8183 L |
| Cost at assumed rates | 13,265.350 KZT | 12,610.775 KZT | 654.575 KZT / 4.93% |

The suggested routes are:

| Day | Stop order, between depot departure and return | Distance | Return |
| --- | --- | ---: | --- |
| Monday | TEKLED → Светотехника → Электросеть | 20.023 km | 11:10 |
| Thursday | ELTECH → Отвертка → **DisTEL** → Электрокомплекс Толе би → Electrika → 220 Volt | 46.408 km | 12:29 |

DisTEL receives service **Thursday 11:00–11:15**. Every delivery fits the declared
receiving hours, both routes fit the van shift, and all loads fit capacity.

The same real road matrix was also used for two counterexamples:

| Scenario | DisTEL move | Explanation | Delivered |
| --- | --- | --- | ---: |
| Flexible day, sufficient stock/capacity | Monday → Thursday | Cheaper complete feasible plan | 9 |
| Latest safe completion Wednesday 09:00 | None | Thursday would violate the stock deadline | 9 |
| Thursday capacity limited to 550 kg | None | Thursday's existing five orders total 500 kg; adding DisTEL needs 600 kg | 9 |

Both counterexamples retain the 74.614 km baseline. These are executed cases, not
just expected behavior. The full inputs, visits, totals and changes for all three
are in [results.json](../experiments/routing/20260923T111348Z-almaty-road-v1/results.json).

## Data and calculation checks

- Ten unique location IDs and coordinates; nine candidate delivery sites; no
  unreachable cells in the directed 10 × 10 matrix.
- Largest marker-to-road snap: **40.01 m**. A business marker is not a verified
  loading entrance. Address suffix discrepancies remain recorded for ELTECH and TEKLED.
- Rejected a general map-center coordinate incorrectly repeated in Электрокомплекс
  Толе би's structured data; used its actual branch marker. Also distinguished
  Electrika and ELTECH map viewport centers from their business markers.
- Metres and each leg's travel minutes are rounded upward before scheduling. This
  makes the 93 → 84 minute comparison conservative. The raw Route responses total
  approximately 86.43 → 78.63 driving minutes; neither includes live traffic.
- Each route geometry differs from its summed rounded matrix distance by under
  3.1 m. All raw responses and both kinds of distance are preserved.
- The planner independently validates visit coverage, time windows, stock deadline,
  readiness, capacity, depot return, distance, fuel and cost after solving. The
  time-limited heuristic returns a feasible result, not a proof of global optimality.

Validation completed: **15 routing tests passed**; the full non-PostgreSQL backend
suite returned **110 passed, 3 skipped, 18 deselected**. Ruff and import-boundary
checks passed. No schema migration was needed.

## Reproduce and hand off

From `backend/`, the default replay uses saved data and makes no network requests:

```powershell
uv sync --frozen
uv run python -m replenishment.cli.almaty_routes
uv run pytest -q tests/test_routing.py tests/test_routing_osrm.py
```

The [frozen run](../experiments/routing/20260923T111348Z-almaty-road-v1/manifest.json)
contains SHA-256 checksums, the Python/OR-Tools versions, source snapshots and the
exact command using archived inputs. Keep that directory unchanged. A replay may
find a different feasible route within its time budget; the saved results document
this specific run.

To fetch new roads, choose a new matrix path (existing captures cannot be overwritten):

```powershell
uv run python -m replenishment.cli.almaty_routes --fetch-roads --fetch-geometry --matrix ../artifacts/almaty-new-matrix.json --output ../artifacts/almaty-new-run
```

The frontend teammate can consume these existing data artifacts:

- [locations.geojson](../experiments/routing/20260923T111348Z-almaty-road-v1/locations.geojson):
  ten Point features with names, addresses and provenance.
- [routes.geojson](../experiments/routing/20260923T111348Z-almaty-road-v1/routes.geojson):
  those points plus four actual road LineStrings. Filter lines by `plan` (`baseline`
  or `proposed`) and `day` (0 = Monday, 3 = Thursday); `delivery_ids` gives stop order.
- [results.json](../experiments/routing/20260923T111348Z-almaty-road-v1/results.json):
  `scenarios.flexible_day.recommendation` contains both plans and suggested changes;
  `baseline_metrics` and `proposed_metrics` contain whole-plan totals. Visit times
  are integer minutes since the horizon's local midnight. Decimal values serialize
  as strings. Scenario time zone and date are in `scenario.json`.

Display the supplied OpenStreetMap/OSRM attribution when showing the routes. The
archived GeoJSON already includes road shapes; an offline rerun intentionally emits
points only with `geometry_status=not_requested_points_only`. Request
`--fetch-geometry` only when new shapes are needed.

## What this establishes, and remaining limits

The backend can suggest a beneficial day change using real Almaty geography and
road connectivity, while retaining hard stock, receiving and vehicle constraints.
The fuel reduction follows directly from an assumed constant consumption rate;
traffic, payload-dependent fuel, idling and actual driving behavior are unmeasured.
The shared static car matrix does not model weekday/hour congestion or heavy-truck
restrictions. All locations need operational address/entrance confirmation before
dispatch. Customer demand, shipment quantities and day flexibility must come from
real business inputs before these percentages can support an operational claim.

See [MULTIDAY_ROUTING.md](MULTIDAY_ROUTING.md) for the forecast-to-deadline logic,
backend input/output contract, optimization objective and integration boundaries.
