# Backend purchasing acceptance

This phase implements backend calculation and persistence only. The manager interface is deferred at the user's request. The acceptance cases below exercise `PlanningRequest` and `calculate`, the same public boundary used by the HTTP preview and saved scenarios. No tests in this document establish real-world purchasing accuracy or authorize sending orders.

## Fixed synthetic evidence

The independent cases live in `backend/tests/test_purchasing_acceptance.py`. Inputs and tolerances were selected before running the implementation. Direct quantity arithmetic uses exact Decimal comparisons. Estimated stockout recovery permits absolute error of `0.000000001` stock units. Bulk scenarios may change the regular recommendation by at most 10% from the uncontaminated scenario.

| Requirement | Fixed input | Passing behavior |
| --- | --- | --- |
| Stock and transit sensitivity | Demand 200 + buffer 20, free stock 50; incoming 70, 100, then 300 | Recommended quantities 100, 70, then 0 |
| Calendar seasonality and explicit growth | September 29–October 2, baseline 10/day, October factor 2, growth 20% | Dated demand 12, 12, 24, 24; total 72; growth applied once |
| Explicit category policy | Baseline 10/day; category A buffer 2 days, B buffer 5 days; then row override 3 days | B adds 30 units to the order; explicit row override gives the same 30-unit buffer for either category |
| Preserve sustained growth | 84-day history, first 63 days 10/day, last 21 days 60/day | No volume excluded as bulk; forecast and order at least twice the constant-history baseline |
| Isolated large order | 84-day history at 10/day; one historical day replaced with 1,010 | Raw rate rises, excluded quantity is positive, regular recommendation remains within 10% of baseline |
| Anonymized customer concentration | One 10-unit day replaced by five documents of 30 for one synthetic customer | Same tolerance as isolated bulk; individual documents alone do not cross the document threshold |
| Known stockout compensation | Fourteen declared unavailable days omitted from an otherwise uniform 84-day history at 10/day | Recover 140 missing units and a 10/day rate; order exceeds raw-sales recommendation |
| Unknown critical values | Missing warehouse, free stock, conversion, or transit-completeness confirmation | `needs_input`, missing reasons, no numeric recommendation |
| Purchase units | Need 130 metres; 100 metres/coil; whole coils only | 2 coils = 200 metres; surplus 70 metres |
| Repeating average | One unit sold over 18 days; forecast another 18 days | Exactly 1 unit forecast and ordered; numeric division residue does not add a purchase unit |
| Timing before new-order arrival | 10/day for 10 days, free 20, incoming 80 on day 5, new-order arrival day 7 | Aggregate order 0, first shortage day 2, maximum pre-arrival deficit 30 |
| Exclusive horizon | Same transit shifted to day 10 | Transit excluded with reason; order 80; shortage still day 2 |
| No future training data | A sale on the planning date | Payload rejected |
| Both suppliers visible | Complete Systeme row plus IEK row missing stock | Both remain in results with explanations; IEK stays blocked |

Each requirement is a behavioral assertion rather than a snapshot of implementation details. The calculator owner's narrower tests cover additional validation, free-stock semantics, minimum quantities, duplicate delivery identity, and contract Q1–Q11. Workflow tests separately cover persistence, revision conflicts, approval, overrides, and export; these acceptance tests do not substitute for those checks.

## Read-only command-line walkthrough

From `backend/`:

```powershell
rtk uv run python -m replenishment.cli.planning_demo
rtk uv run python -m replenishment.cli.planning_demo --json
rtk uv run python -m replenishment.cli.planning_demo --case CASE_ID --json
rtk uv run pytest -q tests/test_purchasing_acceptance.py
```

The first command displays case IDs, recommendations grouped by supplier, explanations, shortages, and missing inputs. Use one of those IDs instead of `CASE_ID` to isolate a scenario. The JSON form includes validated inputs and complete results, preserving Decimal quantities as strings. The CLI uses `planning.demo.demo_cases()` and the production calculator; it does not independently reimplement the arithmetic. It reads no database, creates no scenario, and sends no order.

All CLI cases are explicitly synthetic. Policies use calendar days, arrivals before daily consumption, and carry unmet demand forward. The output distinguishes a calculable scenario from a row that needs more input. A zero routine order can still carry an early-shortage warning.

## Interpretation and unresolved inputs

- The examples verify implementation mechanisms, not forecast quality, reduced excess inventory, or fewer real stockouts.
- Supplied source data lack anonymized customer identifiers and exact availability intervals. Synthetic customer and stockout cases do not demonstrate those facts in the real sales files.
- A statistical bulk candidate is not proof of a customer's intent. Exclusion must be an explicit policy, with raw totals and adjustments preserved.
- Supplied seasonal and growth factors are explicit assumptions. The seasonal acceptance case validates dated application, not estimation of seasonal factors from the original workbooks.
- Category codes do not define buffer or growth multipliers on their own. An explicitly supplied `category_buffer_days` map can assign a scenario buffer policy; row buffer overrides take precedence. The map is not inferred from category codes. No bill of materials is invented; unresolved dependencies must remain visible in source usage and row notes.
- Sustained elevated demand is preserved in the historical mean. This simple baseline does not extrapolate a fitted growth trend or automatically select the separately researched forecasting models; forward growth remains an explicit scenario assumption.
- Real lead times, warehouse scope, unit conversion, stock freshness, and transit dates still need confirmation before a production purchasing decision.
- Saved-scenario actors are local-demo attribution, not authenticated enterprise identities. No production access-control claim is made.

## Verification record

Acceptance-agent verification on 2026-09-23, from `backend/`:

| Command/check | Observed result |
| --- | --- |
| `rtk uv run pytest -q tests/test_purchasing_acceptance.py` | 21 passed in 0.30 seconds |
| `rtk uv run ruff check tests/test_purchasing_acceptance.py src/replenishment/cli/planning_demo.py` | All checks passed |
| `rtk uv run python -m replenishment.cli.planning_demo --case baseline` | Exit 0; bilingual output; recommendation 100 pieces and an explicit early-shortage warning |
| `python -m replenishment.cli.planning_demo --json`, launched and parsed through `subprocess.run` in the same `uv run python` environment | Exit 0; 7 valid JSON cases; every case labelled synthetic and every result row explained |
| CLI JSON, selected-case, unknown-case, and human-output checks | Included in the 21 passing tests |

The seven public demo IDs are `baseline`, `more-transit`, `bulk`, `seasonal-growth`, `stockout`, `early-shortage`, and `missing-inputs`. The independent test suite also covers category policy, customer-split bulk events, purchase conversion, and other edge cases beyond those demonstration presets.

Independent review found a real quantity error before sign-off: repeated division/summation could turn a one-unit requirement over 18 days into `1.000…001`, which rounded to two purchase units. The calculation owner replaced the decision arithmetic with exact rational calculations and fixed the Decimal display context. The independent 18-day regression now passes; the calculator owner's suite covers more periods and caller rounding modes. CLI execution also exposed a Windows cp1251 encoding failure on arithmetic symbols; the CLI now emits UTF-8.

The acceptance agent reviewed the calculation, workflow, and source adapter code. These checks did not run PostgreSQL migrations or persistence tests; the controller and workflow agent record those separate gates. No manager interface, real-data predictive accuracy study, BOM calculation, or production authorization system was validated here.

## По-русски

Текущий этап — backend и расчётная логика; интерфейс менеджера отложен. Команда `python -m replenishment.cli.planning_demo` показывает синтетические рекомендации по поставщикам, причины расчёта, дефицит и недостающие данные. `--json` выводит исходные параметры и полный результат того же калькулятора. Записи в базу и отправка поставщику не выполняются.

Проверки фиксируют чувствительность к транзиту, сезонность, рост, разовые крупные продажи, группировку по анонимному клиенту, восстановление спроса при известном отсутствии товара, перевод единиц и дефицит до прихода. Они подтверждают работу механизма на заданных примерах, но не точность закупок на реальных данных. Неизвестные остатки, склад, конверсия и полнота транзита не заменяются нулём.
