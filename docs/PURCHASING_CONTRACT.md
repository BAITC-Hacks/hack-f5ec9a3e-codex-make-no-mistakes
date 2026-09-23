# Supplier draft contract v2 / Черновики заказов v2

The forecast-first contract in [D12](DECISIONS.md) supersedes the former v0 scenario/lead-time
calculator assumptions. Manager approval and supplier sending are separate tasks.

## Русский

Каждый ряд прогноза получает строку черновика: поставщик, точный SKU, охват, единица закупки,
количество либо причина блокировки, период покрытия, срочность, компоненты, доказательства
и допущения. Состояния: `ready`, `estimated`, `blocked`. Числовой прогноз и возможность заказа —
разные статусы; неизвестный остаток не мешает прогнозу и не превращается в ноль для заказа.

Расчёт покрытия учитывает остаток на подтверждённую дату, оставшийся спрос текущего месяца,
три целевых месяца и совместимый транзит с даты прибытия. Равномерное распределение месячного
спроса по дням — явное допущение. `free` уже учитывает резерв; иначе `on_hand - reserved` применяется
ровно один раз. Несовместимые склады и единицы не складываются. Каждая поставка учитывается один
раз. Будущее поступление не стирает дефицит, возникший до его даты.

Нет выдуманного lead time, safety stock или конверсии. Минимум и кратность применяются только
с установленным смыслом и совместимыми закупочными единицами. Нулевая потребность не становится
положительной из-за MOQ. Неизвестные обязательные количества/конверсии блокируют строку.

Systeme может дать только оценочный черновик в охвате отчёта с явными межотчётными допущениями.
Отсутствующий актуальный остаток IEK остаётся блокировкой. Неизвестное время новой поставки не
позволяет обещать своевременность пополнения, даже если количество покрытия оценимо.

## English

The pure boundary is `build_drafts(batch, forecasts, bridge_forecasts)`. Every canonical series
gets a line. The published forecast covers the next three calendar months; purchasing also covers
the remaining current month from the stock snapshot/planning date, with a disclosed proportional
daily allocation where used. Raw and adjusted forecasts retain their provenance.

A draft is:

- `ready` when required quantities, scope, units and purchasing inputs are supported;
- `estimated` when its quantity depends on identified evidence-supported assumptions;
- `blocked` when essential quantities, scope or conversions cannot be established.

The coverage gap is nonnegative demand less compatible free stock and eligible incoming shipments.
Reservations are deducted once. Arrival timing is evaluated separately from the end-of-horizon gap;
a later receipt cannot erase an earlier shortage. Minima/multiples operate in identified purchase
units after any supported conversion. Unsupported quantity-rule interpretations are not applied.
No lead time or safety-stock policy is invented.

Input snapshots, calculation components, shortage dates, excluded receipts, assumptions and evidence
are persisted with the run. CSV is a **recommendation document**, includes `state` and blocking reasons,
and exports the exact stored quantity. It does not represent an approved or executable supplier order.
No automatic sending takes place.

Source-derived acceptance checks cover free/on-hand/reservation reconciliation, transit monotonicity,
arrival timing, missing essentials, exact SKU/unit/scope identity, no double receipts and zero-need MOQ.
Customer concentration and exact stockout/lost-demand handling remain unverified without the missing
customer identifiers and availability intervals. No savings or inventory-service claim follows from
these arithmetic checks.
