# Planning API contract v0

Shared contract for parallel implementation, 2026-09-23. Quantities serialize as decimal strings, dates as YYYY-MM-DD, identifiers as strings. All defaults must be displayed/labelled as scenario policies. Unknown source values remain null.

## Pure package

`replenishment.planning.models`: `PlanningRequest`, `PlanningResult` (Pydantic models).

`replenishment.planning.calculator.calculate(request: PlanningRequest) -> PlanningResult`.

`replenishment.planning.demo.demo_cases() -> list[dict]`: each `{id, name, description, input}`; input validates as PlanningRequest. Russian names/descriptions preferred. Cases include baseline transit 100→70, bulk, seasonal/growth, stockout, and missing inputs across both suppliers.

## PlanningRequest

Fields:

- `planning_date`: date, required.
- `lead_time_days`: int or null, default null, range 0..365.
- `review_days`: int, default 7, range 1..365; total coverage at most 730 days.
- `buffer_days`: Decimal, default 0, nonnegative.
- `category_buffer_days`: dictionary of exact category strings to nonnegative Decimal days, default empty. Explicit scenario policy only; row buffer override takes precedence over mapped category, then global buffer. Unmapped source codes have no invented meaning.
- `growth_pct`: Decimal, default 0, greater than -100.
- `seasonality`: dictionary of month strings `1`..`12` to nonnegative Decimal factors, default empty (factor 1).
- Seasonal factors are explicit relative adjustments to the selected baseline, not automatically learned or deseasonalized absolute indices.
- `exclude_bulk`: bool, default false.
- `compensate_stockouts`: bool, default false.
- `rows`: list of InputRow, 1..200.

InputRow:

- `row_id`, `supplier`, `sku`, `name`, `stock_unit`: strings; name may be empty.
- `warehouse`, `purchase_unit`: nullable strings, default null.
- `free_stock`: nullable nonnegative Decimal, default null.
- `stock_as_of`: nullable date; `stock_scope_confirmed`: bool default false.
- `incoming_complete`, `constraints_confirmed`: bool default false.
- `stock_per_purchase_unit`, `minimum_order`, `order_multiple`: nullable Decimal. Conversion/multiple must be positive; minimum nonnegative. Null remains unknown. No extra restrictions are represented explicitly by minimum 0 and multiple 1.
- `lead_time_days`, `buffer_days`, `growth_pct`: nullable per-row overrides, same bounds as global fields.
- `category`: nullable string. `seasonality`: nullable month-factor dictionary overriding global factors.
- `daily_demand`: nullable nonnegative Decimal; explicit scenario assumption when supplied.
- `history_start`, `history_end`: nullable dates; history_end is inclusive and before planning_date.
- `sales`: default []; entries `{day: date, quantity: Decimal >=0, document: str, customer_id: str|null=null}`. These are selected eligible outgoing sales; rejected raw movements remain source notes.
- `stockout_days`: default [], dates of known full-day unavailability within declared history.
- `incoming`: default []; entries `{id: str, quantity: Decimal|null, expected_on: date|null, warehouse: str|null, stock_unit: str|null}`.
- `basis`: `observed|assumed|synthetic`, default assumed. Default configured planning policies do not establish observed business policy.
- `notes`: string[], default [].
- `sources`: default []; entries `{label: str, source_row_id?: str, workbook_id?: str, normalizer_version?: str}`.

No implicit category-code arithmetic or BOM expansion. Source notes record unresolved usage. Calendar-day coverage is [planning_date, planning_date + lead_time + review_days). Arrivals occur before daily consumption; unmet demand carries forward in v0. Explain these assumptions in results/docs.

Input decimals support up to 30 digits, at most 12 fractional and 18 whole digits. Internal purchasing decisions use exact arithmetic before ceiling; repeating display decimals must never create an extra purchase unit.

## PlanningResult

- `planning_date`: date.
- `rows`: list ResultRow in input order.
- `warnings`: string[].

ResultRow stable required fields:

- `row_id`, `supplier`, `sku`, `name`, `stock_unit`, `purchase_unit` (nullable), `basis`.
- `status`: `needs_input|scenario_only|ready_for_review`.
- `missing_inputs`: string[]; `warnings`: string[]; `explanation`: string.
- Decimal-or-null fields: `daily_demand`, `raw_daily_demand`, `excluded_bulk_quantity`, `lost_demand_quantity`, `forecast_demand`, `buffer`, `free_stock`, `eligible_incoming`, `raw_need`, `recommended_quantity`, `stock_equivalent`, `rounding_surplus`, `maximum_prearrival_shortfall`.
- Date-or-null fields: `coverage_end`, `arrival_date`, `first_shortage_date`.
- `incoming_decisions`: entries `{id, credited: bool, quantity: Decimal|null, reason: str}`.
- `daily_balances`: entries `{day: date, demand: Decimal, incoming: Decimal, balance: Decimal}`; [] for uncalculable rows.
- `demand_adjustments`: string[]; `sources`: same source-ref shape.

Unknown or invalid row-critical values produce needs_input and no numeric recommendation. Structurally invalid payloads return 422. Repeated shipment identities are explicitly rejected or blocked, never summed twice.

## HTTP endpoints

Workflow router factory: `replenishment.api.orders.create_orders_router(engine)`.
Register before the legacy `/api/v1/{table}` route.

- GET `/api/v1/planning/demo-cases` → demo_cases list.
- POST `/api/v1/planning/calculate` with PlanningRequest → PlanningResult; read-only preview.
- GET `/api/v1/scenarios` → `{items: [{id,name,revision,approved_revision,updated_at}]}`.
- POST `/api/v1/scenarios` with `{name, input: PlanningRequest}` → ScenarioDetail.
- GET `/api/v1/scenarios/{id}` → ScenarioDetail.
- PUT `/api/v1/scenarios/{id}` with `{expected_revision: int, name, input: PlanningRequest, overrides: Override[]}` → ScenarioDetail (append revision, clear current approval).
- POST `/api/v1/scenarios/{id}/approve` with `{expected_revision: int, approved_by: str, acknowledge_scenario: bool=false}` → ScenarioDetail. Reject needs_input rows; acknowledge_scenario required for any scenario_only row.
- GET `/api/v1/scenarios/{id}/export?expected_revision=N` → UTF-8 CSV attachment; reject missing/stale approval. Include scenario basis and approved revision.

Override is `{row_id: str, quantity: Decimal >=0, reason: str}`; reason must be nonblank. Reject unknown/duplicate row IDs and overrides of needs_input rows. Approval name is an attributed local-demo actor, not authenticated enterprise identity.

ScenarioDetail is `{id,name,revision,input,result,overrides,approved_revision: int|null,approved_by: str|null,approved_at: str|null,updated_at: str}`.

Errors: 404 missing scenario; 409 stale revision/unapproved export/blocked approval; 422 invalid payload; 503 unavailable database. Detail is a readable string. No source-system writes or supplier sending.

## Controller-owned source preparation

- POST `/api/v1/planning/source-input` with `{product_ids: UUID[], planning_date: date, warehouse: str, normalizer_version: str|null=null, workbook_ids: UUID[]=[]}` → `{input: PlanningRequest, usage: [{source,status,reason}]}`. Optional workbook_ids restrict source selection; empty means inspect all candidates without merging competing movement books.
- Product picker uses existing `/api/v1/tables/catalog` and `/api/v1/tables/suppliers`. Catalog is supplier-scoped identity; display names may be obtained from product observations.
- Limit preparation to 20 selected products per request initially. Choose no ambiguous version automatically. Include references in each row, keep unknown scope/units/rules unconfirmed, and expose conflicting sources.
- Input preparation supplies no invented lead time, availability, conversion, or customer mapping. Returned defaults are editable scenario settings. UI must preserve notes/sources when editing.
- Source preparation uses the 56 complete calendar days before planning_date for gross-positive outgoing history, explicitly assuming no-transaction days are zero recorded sales. It does not establish extraction completeness or underlying demand. Missing/negative movements remain source notes. All calculable v0 outputs are scenario_only until business planning policies have a confirmation mechanism.

## Changes

Workers must send proposed contract changes to the controller before changing shared field names or route behavior. Controller communicates accepted changes to all lanes and updates this file.
