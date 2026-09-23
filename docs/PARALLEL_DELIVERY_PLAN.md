# Parallel replenishment delivery plan

Date: 2026-09-23. Requested by the user. This is an execution plan, not a claim that the listed features have shipped. The controller updates the completion record after integration and verification.

**Scope correction from user:** defer the manager interface. The current execution is backend and logic only. No frontend changes, frontend agent, or UI walkthrough in this phase. The UI work package below remains a future plan. The third active worker owns backend acceptance tests and a reproducible CLI walkthrough instead. Full frontend Docker/F5 integration is deferred; backend startup and verification remain in scope.

## Outcome and scope

Deliver the local purchasing workflow: supplied data → explicit scenario inputs → explained demand and order calculations → manager changes → approval of a fixed revision → CSV export. Preserve the existing source browser. Both suppliers stay in scope; missing real inputs remain visible, and synthetic acceptance scenarios are labelled throughout.

The original brief governs requirements. DATA_AUDIT.md governs observed source limitations. PURCHASING_CONTRACT.md governs the initial arithmetic, calendar-day timing, and backorder convention. DELIVERY_PLAN.md governs Russian demonstration, bilingual documentation, persistence, F5, and full Docker startup. No supplier messages, hosting, commit, or push are part of this work.

## Starting point

- Existing PostgreSQL ingestion, immutable source evidence, 17 source tables, read API, and React source browser.
- Existing research forecasts and a pure document-level bulk-candidate policy in demand/cleaning.py.
- No integrated purchasing calculation, scenario writes, approval, or export in the current API.
- PostgreSQL is running locally through Compose. Existing uncommitted research, routing, documentation, and dependency changes belong to other work and must be preserved.

## Team and file ownership

Three workers run concurrently; the controller is the fourth active agent. Agents work in the shared checkout, do not reset or stash changes, and do not commit. Each reads AGENTS.md, relevant architecture, this plan, and PLANNING_API.md. Changes to another lane require a message to the controller. Workers report exact files, checks, failures, limitations, and integration details.

| Owner | Responsibility | Exclusive edit scope |
| --- | --- | --- |
| Calculation agent | Typed input/output contract, exact purchasing arithmetic with Decimal inputs/outputs, demand adjustments, synthetic fixtures, focused acceptance tests | backend/src/replenishment/planning/**; backend/tests/test_planning_calculator.py |
| Workflow agent | PostgreSQL scenario/revision storage, concurrency checks, approval, export, API routes, migration | backend/src/replenishment/orders/**; backend/src/replenishment/api/orders.py; backend/migrations/versions/0002_order_scenarios.py; backend/tests/test_orders*.py |
| Acceptance agent | Independent backend acceptance cases and reproducible CLI demonstration; documentation of evidence and limitations | backend/tests/test_purchasing_acceptance.py; backend/src/replenishment/cli/planning_demo.py; docs/BACKEND_ACCEPTANCE.md |
| Controller | Contract ownership, source adapter, router/metadata assembly, import boundaries, development/Docker startup, integration tests, visual review, final documentation | All integration/configuration files outside worker scopes; backend/src/replenishment/planning_sources.py; backend/src/replenishment/api/planning_sources.py; backend/tests/test_planning_sources.py; docs/** |

Agent ownership is temporary, not a new software abstraction. Reuse existing dependencies and patterns. There are no new services, queues, model registries, or LLM-based arithmetic.

## Dependency order and handoffs

1. Controller freezes the first API contract and starts all three workers.
2. Calculation agent publishes models and public functions early. Workflow and acceptance agents build against the documented contract meanwhile.
3. Workflow agent publishes router factory and migration. Controller registers router and metadata and exercises real endpoints with frontend-shaped JSON, without implementing an interface.
4. Controller adds source-backed input preparation and source-usage reporting, preserving ambiguity and selected source versions.
5. Workers run focused checks while the controller prepares startup and integration acceptance.
6. Controller reviews all changed code, runs combined checks, exercises the real API, and assigns concrete corrections back to the owning agent.
7. Completion is recorded only for verified behavior. Missing external business definitions remain product-visible limitations, not invented data.

## Work package A: calculation and demand

Implement a pure, import-safe planning package; no database, environment, or HTTP access. Input/output quantities use Decimal and JSON strings; internal fractions preserve exact purchasing decisions before rounding.

- Validate dates, finite nonnegative quantities, unique row/shipment identities, and bounded horizons. Unknown inputs produce needs_input rather than fabricated zero.
- Accept either an explicit daily demand assumption or dated sales over a declared history window. Do not train on planning-date/future transactions.
- Reuse existing clean_orders for explainable bulk candidates; preserve raw and adjusted totals. Exclusion is an explicit scenario policy, not silently enabled on real data.
- Retain sustained increases; distinguish them from isolated spikes. Customer aggregation uses only supplied anonymized IDs and must not infer IDs from document numbers.
- Compensate only declared stockout days. Estimate missing demand from comparable available history, retain the adjustment, and report inability to estimate when there is insufficient evidence.
- Apply supplied, explicitly labelled seasonal factors and growth assumptions once. Category codes are not numeric multipliers. Explain absent category policies and BOM inputs.
- Forecast dated demand for lead time plus review interval. Compute the configured safety buffer, eligible incoming, free stock, raw need, purchase-unit conversion, minimum, multiple, and rounding surplus.
- Simulate daily balances before the new order; expose first shortage and maximum pre-arrival deficit separately from aggregate need.
- Implement Q1–Q11 from PURCHASING_CONTRACT.md and additional tests for seasonal change, sustained growth, isolated bulk sale, customer-grouped burst, known stockout, and future-data rejection.
- Provide labelled demo cases in code, generated on request, not inserted at import time.

## Work package B: persistence and workflow

- Add scenario and revision tables via migration 0002; do not change source tables.
- Store exact validated request/result snapshots, source references, manager overrides/reasons, actor, approval metadata, and revision identifiers.
- Updating a scenario appends a revision and invalidates prior approval for the current view. Optimistic revision checking rejects stale writes/approvals/exports with 409.
- Calculate results server-side. Never accept a client-authored result as authoritative.
- Reject approval with blocked rows. Scenario-only approvals require explicit acknowledgement and exports stay labelled as scenarios.
- Overrides are nonnegative purchase quantities with a nonempty reason. Retain both recommended and manager quantities.
- Export only the approved current revision, grouped by supplier, with unit, rationale, revision, and basis. Protect spreadsheet consumers against formula injection in textual cells.
- Keep public writes in orders service functions; API is the composition root linking the pure calculator to storage. Domain storage must not import sibling domains or planning.
- Verify create/load/update/approve/export, persistence across application restart, stale revision rejection, invalid overrides, and database errors. Use only isolated empty _test databases for integration tests.

## Work package C: manager interface (deferred by user)

- Preserve the current source-data browser and its existing tests. Add navigation to a Russian purchasing workspace without hiding source provenance.
- Offer clearly labelled demo scenarios and source-product selection; source preparation is an explicit action.
- Provide editable global lead time, review interval, buffer days, growth, and demand policies. Provide per-product free stock, daily-demand assumption, date/scope confirmation, conversion, minimum/multiple, incoming quantity/date, and lead-time overrides.
- Show all rows grouped by supplier, including needs_input rows; never make missing rows disappear from apparent coverage.
- Render recommendation, final quantity, purchase unit, basis, urgency, and explanation. Show missing-input reasons and raw-versus-adjusted demand.
- Save/load named scenarios, edit manager quantities with reasons, approve a revision, and download approved CSV. Local edits visibly make saved results/approval stale; export must remain unavailable until saved and approved.
- Use accessible labels, keyboard controls, loading/error/retry states, and responsive tables. Business labels should explain decisions without exposing implementation internals unnecessarily.
- Add focused tests for loading a case, changing an input, blocked rows, override reasons, approval invalidation, and API failure.

## Work package D: controller integration and source preparation

- Register worker metadata and API routers before the legacy catch-all table route.
- Prepare selected product inputs from imported records with exact source references. Never sum all workbook or normalizer versions. Multiple candidate versions/sources require explicit selection or a visible blocked reason.
- Use detailed movements for the selected warehouse and chosen history; retain unresolved signs/missing quantities as usage warnings. Monthly sales and stock remain contextual evidence until reconciled, not additive sales or current inventory.
- Preserve unknown snapshot warehouse/date and transit year. Do not infer missing customer, lead-time, stockout, conversion, or BOM fields.
- Report every source family as used, contextual, conflicting, or unavailable, with reasons. Repeated seasonality summaries are not independent observations.
- Keep source preparations conservative; an explicit manager assumption enables scenario calculations without changing immutable source records.
- Register import boundaries for new storage/calculation packages where appropriate.

## Active work package C: backend acceptance and demonstration

- Independently translate the five mandatory brief requirements into fixed synthetic acceptance cases using the public PlanningRequest/calculate boundary.
- Demonstrate incoming-stock sensitivity, seasonal demand, persistent growth, isolated/customer-concentrated one-off sales, stockout compensation, missing-input behavior, unit conversion, and early shortage timing.
- Provide `python -m replenishment.cli.planning_demo` producing a readable Russian/English summary or JSON from the same production calculator. No database writes or external messages.
- Keep assertions tied to business behavior, not implementation internals. Document tolerances before comparison and distinguish synthetic mechanism checks from evidence about real customer intent or stock availability.
- Review the other backend lanes once their code is available; report concrete correctness findings to the controller, with independent reproductions when useful.

## Startup and delivery (backend phase)

- Validate reproducible backend commands against the existing persistent PostgreSQL service. Do not recreate or delete the working database. Full application Docker and F5 remain deferred with the interface.
- Write Russian/English operating instructions, calculation methodology, source limitations, demo walkthrough, and exact verification commands.
- Use existing locked dependencies. If a dependency change becomes necessary, explain and keep the lock synchronized.

## Verification gates

| Gate | Evidence required |
| --- | --- |
| Pure calculation | Q1–Q11 and demand acceptance cases pass; dates and quantities remain deterministic |
| Workflow | Save/reload/restart, override, approval, invalidation, stale-write rejection, approved export pass |
| Schema | Upgrade, downgrade, recreation, and alembic check pass on a dedicated test database |
| Backend regression | Ruff, import-linter, and non-PostgreSQL tests pass; dedicated PostgreSQL checks report their exact scope |
| Frontend regression | Deferred; no frontend files changed in this phase |
| Integration | Real API receives client-shaped payloads; source and demo inputs calculate; approved export matches saved revision |
| UI | Deferred explicitly by the user |
| Startup | Document and verify backend dependencies, migrations, API, and CLI demonstration; full application Docker/F5 deferred |

Do not claim reduced real stockouts or inventory savings from synthetic cases or forecast error. Report measured software behavior and distinguish unverified business policy.

## Completion record

Backend phase complete on 2026-09-23; manager interface, full-application Docker and F5 deferred by the user. No frontend files were changed. No commit or push was made. Existing unrelated research and routing changes were preserved.

### Delivered and reviewed

- Calculation agent delivered planning models, pure calculator, seven synthetic fixtures and calculator tests. Controller/acceptance review found and fixed a repeating-decimal error that could recommend 2 units for an exact 1-unit requirement. Internal Fraction arithmetic now determines means, stock balances, conversions and ceiling; Decimal is the contract/display format.
- Workflow agent delivered three persistent tables, migration 0002, server-calculated scenario APIs, immutable revisions/approvals, optimistic concurrency and safe approved CSV export. No supplier sending.
- Acceptance agent delivered 21 independent behavior/CLI tests, predeclared tolerances, a UTF-8 Russian/English CLI, and [acceptance evidence](BACKEND_ACCEPTANCE.md).
- Controller delivered source preparation with version isolation, workbook references and nine source-family usage entries per product; registered metadata/routers/import boundaries; reviewed and tested combined behavior; wrote [backend operating documentation](../backend/PLANNING.md).
- Source preparation also received regression fixes for warehouse whitespace and document identity (date + number + text); signed/missing/future movement values are never silently converted into demand.

### Controller verification

| Check | Observed result |
| --- | --- |
| `uv run pytest -q -m "not postgres"` | 110 passed, 3 database-dependent skips, 18 deselected at the recorded run |
| `tests/test_orders_postgres.py` | 5 passed, isolated empty `replenishment_orders_agent_test`; migration upgrade/check/downgrade/recreation, revision history, persistence, concurrent edits, approval/export |
| `tests/test_planning_sources.py` | 7 passed, isolated empty `replenishment_sources_test`; source selection plus real composed FastAPI preview/save/approve/export/invalidation |
| `tests/test_database.py tests/test_api.py` | 9 passed, isolated empty `replenishment_controller_test` and `replenishment_api_test`; existing schema and read API regression |
| `uv run ruff check .` | Passed on final check; temporary unrelated routing-file lint failures during concurrent work had cleared |
| `uv run lint-imports` | All three module-boundary contracts passed |
| CLI | Human baseline and all-seven-case JSON execution verified by independent acceptance; Windows output explicitly UTF-8 |
| Local development migration | Upgraded `replenishment` from 0001 to 0002, then `alembic check` reported no drift; row counts unchanged across all 17 source tables |
| Read-only source inspection | IEK `200400085_`: 16 recent document totals, unknown current stock; Systeme `300200745_`: 41 recent document totals, reported free stock 23; warehouse confirmation false for both |

Each PostgreSQL suite enforces an empty, explicitly named/suffixed test database; successful suites clean their own schema. The working database received only the additive migration, not test data or demo scenarios. Existing dependency deprecation warnings were recorded and do not affect passing assertions.

### Remaining business and product work

All calculable results remain `scenario_only`. Current functionality is a reviewable backend foundation, not validated autonomous purchasing. The simple history-mean policy is explicitly separate from research model selection; seasonal factors, growth and category buffers are configurable scenario policies. No automatically learned seasonal index or claimed inventory saving was introduced.

Real-world stock scope/freshness, complete transit, supplier lead times, unit conversions, customer IDs, availability intervals and BOM still require authoritative inputs. Unreconciled monthly reports and ambiguous Excel formulas remain contextual with reasons. The API supports explicit assumptions without rewriting sources. Authentication and production deployment are outside this local backend phase. The manager UI can be built later against [PLANNING_API.md](PLANNING_API.md).
