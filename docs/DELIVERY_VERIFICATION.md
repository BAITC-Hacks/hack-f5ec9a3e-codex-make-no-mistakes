# Текущая проверка / Current delivery verification

2026-09-23. This record supersedes the older backend-phase statement that the
manager interface is deferred. It describes the working tree, not a tagged release.

## Проверено / Verified

| Check | Observed result |
| --- | --- |
| `uv run pytest -q -m "not postgres"` | 223 passed, 3 skipped, 20 deselected; 4 dependency deprecation warnings |
| `uv run pytest -q tests/test_orders_postgres.py tests/test_planning_sources.py` | 12 passed against isolated empty databases, 4 dependency warnings |
| `uv run ruff check .` | Passed after the evaluation fixes |
| `uv run lint-imports` | All 3 contracts passed |
| Connected frontend tests/build | Two connected-workspace tests pass: exact decimal overrides, required reasons, revision conflict, approval/export and reload; production build passed. Full suite at 17:37: 7 passed, 1 failing in the separately changing prototype's custom-period expectation. |
| Live Chrome → Vite → FastAPI → PostgreSQL | Imported SKU selection, missing-input state, explicit assumptions, calculation, draft, override, approval, CSV link and page-reload persistence checked |

The PostgreSQL run used `replenishment_review_orders_test` and the verified-empty
`replenishment_sources_test`. It includes migration upgrade/check/downgrade/recreation,
revision persistence, stale edits, approval invalidation and export. Source tests use
isolated fixtures; the live walkthrough below used the existing imported workbook data.

Evaluation fixes: forecast-date sales cannot qualify a product with no past sales,
even when `min_history_days=0`; constant training history has undefined scaled-error
denominators. Existing independent regression cases now pass. Research runs were not
rerun, changed or promoted into the purchasing calculator.

## Живой сценарий / Live source-based walkthrough

### New connected design

The main entry now mounts `connected-workspace.jsx` using the new Elektrokomplekt
layout. Catalog selection, source preparation, calculation, scenario revisions,
approval and CSV use the real API. There is no synthetic fallback on API failure.
History dates are separately validated by source-input (both required together,
before the calculation date); an isolated source test confirms later sales are excluded.

Docker was built and started under project `ektverify` with a separate fresh volume,
database port 55433 and web port 8081. All three services became healthy. After a
second build/recreation, the first saved scenario remained available.
`python scripts/verify_purchasing_http.py --base-url http://127.0.0.1:8081` passed:
41 real sales documents, 18 source references, recommendation 0, exported override 6,
and revision 3 invalidated approval. In Chrome, the new design loaded this saved
scenario, blocked an override without a reason, saved revision 4 and approved it
as a verification-only scenario. The CSV link identified exactly revision 4.
Scenario: `651c51ba-291b-4d2a-bab6-ace1b7dd9e15` in the isolated Docker database.

The source-window and evaluation subset subsequently reported 22 passed. That run
also printed a Windows WMI exception after its test summary despite exiting zero;
it is not counted as a clean new full-suite run. Other tasks continue changing the
shared working tree, including forecast-period and import features.

### Earlier frontend walkthrough

Open the main `/` application, choose **Выбрать товары**, and search for
`300200745_` (Systeme Electric, ATN540126). Select Алматы and 2026-09-23.
The observed free stock is 23 and the incoming quantity is 120, but stock scope,
freshness, arrival date and purchasing rules are unresolved. The initial result
correctly remains `needs_input`, with no numeric recommendation.

For the verification only, **Уточнить входы** recorded these explicit assumptions:

- Stock remains 23 on 2026-09-23, for Алматы.
- Stock/purchase units are шт, conversion 1:1, MOQ 0, multiple 6.
- New supplier lead time is 7 days; review interval is 7 days; buffer is 0.
- Existing 120 units arrive in Алматы on 2026-09-25; incoming list is assumed complete.
- The existing imported sales history is retained; no explicit daily demand overrides it.
- The reason states that these conditions are not confirmed by EKT and this is not a real order.

The result was `scenario_only`, with recommendation **0 шт**. This is a valid outcome
under those assumptions, not evidence that the real business should order zero.

The browser then saved **ПРОВЕРКА E2E 2026-09-23 — НЕ РЕАЛЬНЫЙ ЗАКАЗ — 300200745_**,
changed the quantity to **6** with a test-only reason, and created revision **2**.
The approval dialog displayed 6. Approval was attributed to
**Codex — проверка сценария, не закупка**, not to a real employee.

The saved scenario ID is `83b1d2dd-7a6d-4e2c-85ad-beb69af88fae` in the existing local
development database. The approved CSV link was exercised. An independent HTTP CSV
parse asserted `recommended_quantity=0`, `approved_quantity=6`, and
`revision=approved_revision=2`. Reloading the browser retained the approved scenario.
The deliberately labelled record remains available for inspection. No supplier was
contacted; source records were not edited.

Кратко: реальный товар сначала заблокирован из-за неизвестных входов. После явных
учебных допущений получено 0 шт; ручная корректировка до 6 шт сохранена в версии 2,
утверждена только как проверочный сценарий и совпала с CSV. Перезагрузка сохранила
сценарий. Это проверка программного пути, а не подтверждение бизнес-политики.

## Входы от EKT / Inputs EKT still needs to confirm

| Required clarification | Why it matters |
| --- | --- |
| Available stock, warehouse scope, snapshot date and reservation meaning | Avoid subtracting unavailable stock or reservations twice |
| Complete inbound list, arrival dates, lead times and review calendar | Distinguish stock coverage from shortages before arrival |
| Stock/purchase units, conversions, minimums and multiples | Produce quantities a supplier can actually accept |
| Anonymous customer IDs and project-order policy | Validate customer concentration and recurring versus exceptional demand |
| Exact availability/stockout history | Validate lost-demand recovery on real observations |
| BOM semantics and component requirements | Component expansion is not implemented; do not claim full brief coverage |
| Accepted 1C export columns and identities | Current CSV is reviewable but compatibility is not confirmed |

No automatic seasonal model is deployed: monthly factors and future growth are
explicit scenario inputs. Some monthly reports and ambiguous source fields remain
contextual with a stated reason. No real inventory saving, service level, or production
authorization claim follows from these checks. Ask the sponsor's purchasing/data owner
to resolve the table above; no messages have been sent on the team's behalf.

## Запуск / Startup

See [local and container startup](STARTUP.md). Full Docker verification uses a separate
Compose project and volume so it does not recreate the working database. F5 requires
the VS Code Python/Python Debugger extensions and first-time environment preparation.
