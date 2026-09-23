# Business readiness / Готовность закупочного решения

Date: 2026-09-23. Team working plan following the requirements review. This records direction and unresolved questions; it does not claim partner confirmation or implemented purchasing features.

## Decision and next milestone

Pause further model searches as the main workstream. Use the existing explainable baseline for the first purchasing flow; retain challenger results in [experiments](../experiments/INDEX.md). Deliver: **a manager can inspect, adjust, approve and export a defensible supplier order, and see which rows still need inputs**.

The business user needs to know what to buy today, when stock is needed, and why the quantity is reasonable. Forecast error alone does not answer that question. Existing experiments evaluate recorded sales, which may include one-off orders and omit demand lost during unavailable periods. They do not prove inventory savings, lost-demand recovery or customer-concentration detection.

## Evidence and authority

- [Original brief](sources/HackAlem%20AI_%20Автоматизация%20формирования%20заказов%20поставщикам.docx.md): required capabilities, user workflow and confirmation before sending.
- [Project context](PROJECT_CONTEXT.md): brief summary and outstanding business definitions.
- [Data audit](DATA_AUDIT.md): observed coverage/conflicts in 12 workbooks and 14 sheets, dated 2026-09-23. This review reuses that audit, not a fresh workbook audit.
- [Delivery plan](DELIVERY_PLAN.md): agreed scenarios, persistence, approval/export and bilingual delivery.
- [Frontend requirements](FRONTEND_REQUIREMENTS.md) and [API](../backend/API.md): documented read-only data slice; calculation and purchasing workflow remain subsequent work.

The original brief governs requirements; the audit governs what was observed in supplied data. Plans are not evidence of shipped features. Unknown inputs remain unknown until confirmed or explicitly supplied as scenario assumptions.

## Blocking questions and action

Owners below are required roles, not assignments to teammates or requests already sent to the partner.

| Priority / question | Evidence and consequence | Resolution owner / next action | Interim behavior |
| --- | --- | --- | --- |
| P0: Which warehouse and stock snapshot? | Sales movements are Алматы; Systeme stock scope is uncertain; IEK lacks a current snapshot. Wrong scope can subtract unavailable or duplicate stock. | Partner buyer/data owner: identify authoritative free stock, reservations and snapshot date for the selected warehouse. | Missing/conflicting scope blocks a real recommendation; labelled scenario overrides permit demonstration. |
| P0: When will replenishment arrive? | Expected dates exist for some shipments, but supplier lead-time rules are missing. Transit arriving after a shortage cannot prevent it. | Buyer: confirm lead time, review frequency, order calendar, destination and arrival reliability. | Explicit scenario dates; report pre-arrival shortages separately. No silent 7/28-day purchasing horizon. |
| P0: What unit is ordered? | IEK includes coils versus meters; minimum versus multiple is unresolved and source values conflict. | Procurement/master-data owner: confirm conversion, minima, multiples and source priority. | Preserve demand in stock units; block actionable purchase quantity if conversion/required terms are unresolved. |
| P0: What does a reservation cover? | Systeme has on-hand/reserved/free values; outstanding customer commitments are not fully defined. | Buyer: decide how known commitments relate to forecast and reservations. | Do not subtract reservations twice or add a committed order already covered by another component. |
| P1: What is repeatable demand? | Customer IDs are absent. A large sale can be a project, ordinary variation or sustained growth. | Buyer + demand owner: define reviewable bulk-event policy and obtain anonymized customer mapping. | Flag suspected events with before/after impact; do not claim customer-based detection on current data. |
| P1: When was demand suppressed? | No exact stockout intervals. Monthly blanks cannot supply durations. | Inventory owner: supply availability intervals and completeness meaning. | Lost-demand correction unavailable on real data; use labelled synthetic acceptance cases. |
| P1: How much buffer is acceptable? | Service priorities, shortage/holding costs and price meaning are not agreed. | Buyer: choose explicit buffer policy and product priorities. | Configured buffer with provenance; no invented optimal service level or monetary savings. |
| P1: Categories, growth and BOM? | Systeme category codes lack definitions; growth fields are historical calculations; BOM is absent. | Partner: explain meanings and whether BOM expands component requirements. | Report usage/non-use with reason. No forced multiplication, double-counted growth, or invented BOM. |
| P1: How does an approved order leave the app? | Brief requires compatible export and human confirmation; schema is unknown. | Buyer/accounting owner: supply accepted export columns and identity rules. | Clearly labelled draft export format until verified; no automatic supplier sending. |

Missing inputs block only the affected real-world claim or actionable row. They do not block development using explicit scenarios. Both suppliers remain in scope; choosing a clear demonstration SKU does not remove mandatory brief requirements.

## Work order

1. **Now: calculation contract and acceptance cases** — [PURCHASING_CONTRACT.md](PURCHASING_CONTRACT.md), linked to issue #5. Resolve arithmetic, timing and unknown-input behavior before integrating a model.
2. **Next implementation slice:** a deterministic calculator accepting normalized scenario inputs, returning quantity components, warnings and shortages before arrival. No supplier sending. Feed the existing baseline forecast through a clearly defined input boundary.
3. **Then workflow:** saved scenarios, manager quantity edits with reasons, approval of a fixed revision, export of approved values. Changes invalidate approval. Coordinate with issue #6.
4. **Then brief acceptance:** seasonality, sustained growth, stockout recovery, bulk/customer examples and supplier grouping, with synthetic cases clearly separated. Track under issue #7; update launch/demo instructions under #8.
5. **Only then model promotion:** compare candidates inside the agreed inventory policy. Historical stock/availability and cost gaps limit claims; simulated outcomes must be labelled.

Start the representative example with Systeme SKU `300200745_` / `ATN540126`: audit records on-hand 42, reserved 19, free 23, transit 120, multiple 6. Warehouse, arrival assumptions and demand are not thereby confirmed. Demonstrate IEK's missing snapshot and conversion requirements as visible unresolved inputs, not fabricated quantities.

## What success means

First acceptance is functional: trace every component, preserve unknowns, reproduce scenario arithmetic, retain edits, invalidate stale approvals, and export the approved revision. A human walkthrough should record elapsed time from selected inputs to draft order, how many eligible rows need clarification, and override reasons. Set targets after an observed manual baseline; none is established yet. Fewer clicks or lower WAPE alone does not establish less excess stock or fewer lost sales.

## Русский

Главный следующий результат — понятный заказ: менеджер видит исходные данные, проверяет количество, исправляет его, утверждает конкретную версию и экспортирует её. Новые ML-эксперименты пока не главный приоритет; результаты сохраняются, базовый прогноз используется как начальный вход.

Критичные пробелы: склад и дата свободного остатка, срок и календарь поставки, единицы закупки и кратность, смысл резервов. Для stockout и концентрации у клиента реальных полей нет; обязательные проверки выполняются на явно помеченных синтетических сценариях. Неизвестное значение не становится нулём. Рост, категории и BOM требуют расшифровки; импорт источника не означает, что его можно автоматически использовать в формуле.

Роли в таблице — кого нужно привлечь для ответа, а не уже назначенные участники. Следующий шаг — реализация [контракта расчёта](PURCHASING_CONTRACT.md), затем сценарии, корректировка, утверждение и экспорт. Экономия и уровень сервиса пока не доказаны.
