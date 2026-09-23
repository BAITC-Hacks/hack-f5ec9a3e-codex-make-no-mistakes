# Purchasing calculation v0 / Контракт расчёта закупки

Date: 2026-09-23. Implementation specification for issue #5, derived from [business readiness](BUSINESS_READINESS.md). **Proposed team rules, not confirmed partner policy or implemented behavior.** Synthetic examples below are acceptance fixtures, not measured business outcomes.

## Calculation boundary

One row is supplier + exact SKU + warehouse + stock unit at an explicit planning date. Inputs are pinned to source versions or labelled manual/synthetic overrides. A zero is a known quantity; null means unknown. The calculator takes a dated demand forecast, not a model name alone.

Required for an actionable quantity: confirmed stock scope/date, available stock, dated forecast over the coverage interval, new-order arrival date, next review interval, explicit buffer, a statement that incoming-delivery coverage is complete, and valid purchasing-unit conversion/required quantity constraints. The UI must list missing/conflicting inputs. A scenario can supply them explicitly, but its result remains labelled as assumed/synthetic.

New-order arrival is planning date + configured lead time under an explicit day convention. v0 scenario convention: calendar days. Coverage ends at new-order arrival + review interval, exclusive. Forecasted demand on a date is consumed after arrivals at the start of that date. This daily convention is an assumption requiring business confirmation; it must not be silently applied to intraday promises.

## Quantity arithmetic

For the first slice, reservations protect committed demand outside the regular forecast. Use **free stock once**; do not also subtract reserved quantity. Additional commitments/backorders require an explicit non-overlapping definition and due dates. If their relationship to forecast/reservations is unresolved, mark the affected calculation as needing input.

Within the v0 scenario boundary:

`raw need = max(0, regular demand over coverage + buffer - free stock - eligible incoming)`

Eligible incoming has a matching warehouse, confirmed stock-unit conversion, and expected availability within the coverage interval. Already-received stock must not also appear as incoming. Undated, overdue-unconfirmed or differently scoped incoming cannot be treated as known zero or automatically credited; require review. Explicitly outside-horizon deliveries contribute zero, with an explanation.

This aggregate quantity assumes unmet demand within the interval remains a requirement (backorder treatment). If the partner treats it as lost sales instead, that is a different policy and must be implemented/tested separately. The aggregate formula does not prove every day's demand can be served.

Compute the daily balance from free stock + dated eligible arrivals - dated demand, before adding the proposed order. Report the first shortage date and maximum shortfall before the new order can arrive. A routine order arriving later cannot repair earlier missed service; show an expedite/transfer review flag, without assuming either action is feasible. Negative balances carry forward under the explicit backorder convention. Buffer breach and inability to serve demand are separate facts.

Convert raw need from stock units to purchase units before applying supplier rules. For positive need, use the larger of converted need and a confirmed minimum, then round up to a confirmed purchase-unit multiple. Zero need remains zero; a minimum alone does not force an order. If no extra restriction applies, that must be explicitly configured. A minimum is not automatically a multiple. Report rounding surplus in stock units. Arithmetic must preserve decimal quantities.

## Explanation and state

Return supplier/SKU/warehouse, planning date, coverage end, forecast demand, buffer, free stock, each credited/excluded arrival with reason, raw need, conversion, minimum/multiple, purchase quantity/unit, stock equivalent, rounding surplus, first shortage date and missing-input reasons. The explanation is derived from these same values.

Distinguish `needs_input`, `scenario_only`, and `ready_for_review`; none means automatically approved. Need zero is a valid result distinct from inability to calculate. Label forecast, observed inputs and assumptions separately. Preserve all source inputs and manager overrides.

Later workflow: save the scenario and calculation revision; manager edits require an attributable reason. Approval references that revision and exact approved quantities. Recalculation, new inputs or edits invalidate prior approval. Export the approved revision only as an approved order, with draft exports clearly labelled. Generating/exporting must not itself send a supplier order. Do not silently drop blocked rows from a supplier total; disclose excluded rows.

## Fixed acceptance cases

All quantities are synthetic unless the row explicitly cites the audit. No case below is yet reported as passing implementation.

| ID | Inputs/change | Expected result |
| --- | --- | --- |
| Q1 | Coverage demand + buffer 220; free 50; timely incoming 70; conversion 1; minimum 0; multiple 1 | Raw and final need 100. |
| Q2 | Q1, incoming becomes 100 | Need 70; explanation attributes the 30-unit decrease to incoming. |
| Q3 | Q1, incoming becomes 300 | Need 0, never negative. |
| Q4 | On-hand 42, reserved 19, free 23; total requirement 100; no incoming | Need 77. Subtracting reservations again and obtaining 96 fails. |
| Q5 | Raw need 13 pieces; conversion 1; minimum 20; multiple 6 | Order 24 pieces; rounding/minimum surplus 11. Raw need 0 still orders 0. |
| Q6 | Raw need 130 meters; 100 meters per coil; minimum 0; multiple 1 coil | Order 2 coils = 200 meters; surplus 70 meters. Missing conversion returns needs_input. |
| Q7 | Free stock or warehouse unknown | No numeric actionable recommendation; identify missing input. An explicit override creates scenario_only. |
| Q8 | Planning day 0; coverage [0,10); demand 10/day; buffer 0; free 20; incoming 80 at day 5; new order can arrive day 7 | Aggregate need 0, but first shortage day 2 and maximum pre-arrival shortfall 30 by end of day 4. Show review urgency despite zero routine order. |
| Q9 | Q8, incoming moves to day 10 (outside coverage) | Incoming contributes 0; raw need 80; first shortage remains day 2. Day-7 routine arrival cannot prevent that earlier shortage. |
| Q10 | Same incoming line imported twice | One business delivery is counted once after identity reconciliation; unresolved duplicate identity blocks calculation rather than guessing. |
| Q11 | Negative quantity/invalid multiple or unknown transit completeness | Explicit validation/needs_input result, not abs(), zero substitution or silent omission. |
| W1 | Save, reload and restart scenario | Same inputs, assumptions and calculation revision remain recoverable. |
| W2 | Approve, then edit quantity or change stock | Approval becomes stale; a fresh approval is required for approved export. |
| W3 | Manager approves 24 instead of suggested 18 | Approved export contains 24 and retains suggested 18 plus override reason; no automatic sending. |

## Demand acceptance beyond the calculator

Issue #3/#4 must supply regular demand and adjustment evidence. Required tests include a labelled one-off bulk event, customer-concentrated events using synthetic anonymized IDs, a sustained level increase, a seasonal pattern, and known availability intervals. Fix inputs and tolerances before execution. A universal spike cap that also erases the sustained increase fails the intent. Stockout compensation must compare equivalent demand histories with known unavailable days, not infer stockouts from monthly blanks.

These tests remain to be specified at the forecasting boundary; the table above only defines calculation/workflow cases. Do not call issue #5 or the whole brief complete based on arithmetic tests alone. Category/growth/BOM handling requires explicit source usage or a documented unresolved dependency; never multiply growth twice or explode nonexistent BOM data.

## First real-data walkthrough

Use audited Systeme `300200745_` / `ATN540126`: free stock 23, transit 120 and multiple 6. Preserve evidence links to the imported source rows. Obtain or label warehouse, arrival date, forecast, buffer and lead-time assumptions before calculating. The source numbers alone do not establish an order quantity. Show IEK rows needing stock/conversion input rather than silently excluding the supplier.

## Русский

Единица расчёта — поставщик, точный SKU, склад, единица хранения и дата. Все исходные данные фиксируются по версии; неизвестное не равно нулю. Горизонт v0 — срок новой поставки плюс интервал пересмотра, календарные дни как явное допущение сценария.

Потребность = максимум из нуля и «регулярный спрос за горизонт + буфер − свободный остаток − подходящий транзит». Резерв второй раз не вычитается. Этот вариант предполагает перенос неудовлетворённого спроса; правило потерянных продаж требует отдельного согласования. Дневной баланс показывает дефицит до прихода: итоговый нулевой заказ не означает отсутствие риска.

Потребность сначала переводится в закупочные единицы, затем применяются подтверждённые минимум и кратность. Нулевая потребность не создаёт заказ из-за MOQ. Нет конверсии, склада или актуального остатка — нет достоверного числового заказа; ручное допущение даёт только помеченный сценарий.

Менеджер видит арифметику, источники и причины исключения поставок, меняет количество с причиной, утверждает конкретную версию. Новое изменение отменяет актуальность утверждения. Экспорт содержит утверждённые значения; отправка поставщику автоматически не выполняется. Q1–Q11 и W1–W3 — спецификация синтетических проверок, не отчёт о готовности кода.
