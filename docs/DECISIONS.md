# Решения / Decisions

Решения фиксируются добавлением новой записи; прежнее решение помечается заменённым со ссылкой на новое. Выводы аудита — наблюдения, а неизвестные значения остаются неизвестными до получения подтверждения.

Decisions are updated by appending a new entry and explicitly superseding the old one. Audit findings are observations; unknowns remain unknown until supported by evidence.

| ID | Дата / Date | Решение / Decision | Основание / Basis |
| --- | --- | --- | --- |
| D01 | 2026-09-23 | Python 3.12/FastAPI, SQLAlchemy 2/Alembic/uv, PostgreSQL 17; React 19/TypeScript/Vite. Модульный монолит с одним пакетом, БД и историей миграций. / Modular monolith with one distribution, database and migration history. | Выбор пользователя и [TenderVision](https://github.com/dimashisenov/tendervision-product/blob/main/backend/ARCHITECTURE.md) / User selection and reference architecture |
| D02 | 2026-09-23 | Два режима: F5 (API + React, БД в Docker) и полный Compose. Демо RU, материалы RU/EN, без видео; сценарии сохраняются. / F5 and full Compose; Russian demo, bilingual materials, no video; persisted scenarios. | [Согласованный план / Approved plan](DELIVERY_PLAN.md) |
| D03 | 2026-09-23 | Аудит v1 закреплён хешами 14 исходных файлов и исполняемыми проверками ключевых фактов. Не менять baseline ради прохождения тестов: для новых файлов создавать новую версию и описывать отличия. / Audit v1 is pinned by 14 source hashes and executable checks; changed inputs require a new baseline with a documented delta. | [Аудит / Audit](DATA_AUDIT.md), [baseline](sources/audit-baseline.json) |
| D04 | 2026-09-23 | Разделить неизменяемое сырьё и типизированные наблюдения. Хранить оригинальные XLSX в БД, лист/строку/ячейку, формулы и кешированные значения; сохранять ошибки и NULL отдельно от нуля. / Separate immutable source evidence from typed observations, retaining complete XLSX bytes, provenance, formulas, cached values, errors and missingness. | Запрос пользователя на все данные Excel и результаты аудита / User's full Excel coverage request and audit |
| D05 | 2026-09-23 | Идентификатор товара — поставщик + исходный строковый код 1С; артикул и имя хранятся в наблюдениях, не перезаписывают историю. / Product identity is supplier + exact 1C SKU; source articles and names remain observations. | Дубликаты и различия справочников / Duplicate and conflicting source entries |
| D06 | 2026-09-23 | Месячные продажи, движения и текущие остатки — отдельные источники; неизвестный склад остаётся NULL. Отрицательные значения не преобразовывать автоматически; пустоты не считать нулями. / Keep monthly sales, movements and snapshots separate; unknown warehouse stays NULL; no automatic sign or blank conversion. | Расхождения источников и неясный охват / Source discrepancies and uncertain scope |
| D07 | 2026-09-23 | Коэффициенты, итоги и готовые расчёты Excel сохраняются как наблюдения, не становятся алгоритмом приложения. Customer ID, stockout, lead time, BOM и конверсии не выдумывать. / Retain spreadsheet calculations as evidence rather than adopting them as application policy; do not invent missing inputs. | Формула 13 месяцев, неизвестные бизнес-определения / Thirteen-month formula and unresolved definitions |
| D08 | 2026-09-23 | Текущий срез — модели, миграция и регрессионные проверки. Нормализатор всех файлов, расчёт, API, React и сохранение сценариев реализуются следующими задачами. / Current slice delivers models, migration and regression checks; full normalization, calculations, API, React and scenario persistence are subsequent work. | Разделение задач №1/№2/№3–8 / Task boundaries |
| D09 | 2026-09-23 | Начат следующий срез D08: импорт Excel, read-only API и React-таблицы. CLI собирает публичные интерфейсы записи модулей; парсер живёт в intake/adapters. Новый browsing — read-only модуль сборки SQL-проекций, получает metadata через точку сборки; api — HTTP-транспорт. / Advance D08 with Excel import, read-only API and React tables; CLI composes module write interfaces, intake owns parsing, browsing composes read-only SQL projections with injected metadata, api owns HTTP transport. | Прямой запрос пользователя на импорт, endpoints и frontend / User request |
| D10 | 2026-09-23 | Таблицы отображают наблюдения и версии с происхождением, серверной пагинацией и Decimal-строками; не суммируют источники и не имитируют готовые рекомендации. / Tables show provenance-bearing versioned observations with server pagination and decimal strings, without cross-source aggregation or fabricated recommendations. | Аудит и [frontend-контракт](FRONTEND_REQUIREMENTS.md) / Audit and frontend scope |
| D11 | 2026-09-23 | Каталог показывает одну строку на идентичность поставщик + SKU; атрибуты источников доступны отдельно. При конфликте названия/артикула не выбирать случайное наблюдение. / The catalog shows one supplier-scoped SKU identity per row; source attributes remain a separate view, without arbitrary conflict resolution. | 3 909 товаров и 261 098 наблюдений после импорта / Imported identities versus observations |

Изменение границ модулей, направления зависимостей, идентичности, происхождения данных или контракта API фиксируется новой записью вместе с кодом и проверками. Внутренний рефакторинг без изменения поведения не требует отдельного согласования.

Changes to module ownership, dependency direction, identity, provenance or API contracts require a new recorded decision alongside code and checks. Internal behavior-preserving refactors do not need separate approval.

## D12 — Forecast-first core / Основной расчёт, 2026-09-23

Supersedes the pending-calculation portion of D08 and the v1 application assumptions in
`INVENTORY_EVALUATION.md` and `PURCHASING_CONTRACT.md`. Saved reports and registered experiments
remain immutable. The main entry point is `replenishment.calculation.calculate(batch)`, contract `2`.

Один конвейер: существующие документы → проверенная карта листа → нормализованные наблюдения →
канонические месячные ряды → прогнозы → черновики по поставщику → PostgreSQL/CSV.
Основная история — отдельные месячные отчёты. Движения Алматы и встроенные отчёты — отдельные
источники сверки; их нельзя прибавлять к месячным продажам. Дубликаты сводок не удваивают спрос.

One pipeline uses existing XLSX readers, immutable evidence and versioned domain observations.
Validated worksheet mappings replace positional interpretation. Source hashes and normalizer versions
are pinned before calculation. A dedicated calculation module owns pure forecasting/purchasing;
its input adapter composes read queries through supplied metadata, and its persistence adapter owns
four result tables. CLI composes the run, API remains read-only. One migration (`0002`) adds results.

Дата планирования среза — **22.09.2026**, явное допущение. Обучение по завершённым месяцам до августа;
сентябрь — внутренний мост; публикация — **октябрь–декабрь 2026**. Пропуск ≠ ноль, неизвестная
единица ≠ штуки, неизвестный склад ≠ Алматы. Продажи не равны неограниченному спросу.

The fixed inexpensive candidates are recent-three-observation level, EWMA (`alpha=0.3`), and
seasonal damped trend (`alpha=0.3`, damping `0.8`). Fit preprocessing at each historical origin.
Do not apply historical spreadsheet growth/seasonality coefficients again. Raw and adjusted
variants retain unchanged actual targets; document anomalies are candidates, not confirmed customers.

ML and numerical LLM forecasts must pass the same development gate: at least 3% less normalized
error, no worse absolute normalized bias, no supplier/horizon degradation above 5%, and no coverage
loss. Freeze selection before the January–May 2026 retrospective comparison. Research dependencies
remain separate unless this evidence justifies production promotion. Historical 7/28-day runs stay intact.

LLM: strict outputs plus semantic validation, exact input/schema/prompt/model cache, explicit prices,
worst-case reservation before every request, retry and escalation, **maximum $1 per run**. Unknown
pricing disables paid calls. A failed diagnostic cannot invalidate deterministic forecasts.

Черновики: `ready`, `estimated`, `blocked`; дата прихода транзита и дефицит до неё учитываются
отдельно, резерв вычитается один раз. Единицы закупки и смысл ограничений требуют основания.
Systeme допускает только явно помеченные межотчётные допущения; отсутствие актуального остатка IEK
не превращается в ноль. Без lead time нельзя обещать своевременность пополнения.

Customer concentration, exact stockout durations/lost-demand uplift, lead times, BOM and unsupported
unit conversions remain unverified where the supplied documents lack evidence. No invented business
data, inventory simulation, supplier sending, purchasing UI, new service or model registry. No claim
of inventory savings. CSV is a recommendation document, not an executable or approved order.

## D13 — Forecast-first completion / Проверка основного расчёта, 2026-09-23

Normalizer **v2.3** appends corrected observations; original workbooks, earlier normalizers and
registered experiments are preserved. Two-level headers supply Systeme's explicitly labeled
order multiple. IEK's ambiguous minimum-shipment interpretation remains unconfirmed. A completed
hash/version is checked before parsing or paid extraction, then rechecked under the import lock.

Canonical inputs exclude embedded sales from the forecast catalogue, deduplicate selected sources,
infer a unit only from consistent existing SKU observations, and keep transactions under their own
scope. Matching embedded monthly history permits an explicitly estimated Systeme report-scope link;
it does not establish a physical warehouse. An undated `24.09` receipt may use the snapshot year only
as a recorded assumption. Missing receipts, stock, conversions and contradictory rules remain blockers.
Current stock must match the planning date. Monthly snapshots do not become current free stock.

The [frozen monthly comparison](../experiments/monthly/20260923-forecast-first/results.json) retains
recent level. LightGBM development error is 15.24% worse and fails every supplier/horizon degradation
check; no research dependencies are promoted. The 2.47% best statistical improvement does not clear
the fixed 3% threshold. Runtime selection uses completed 2025 development targets only. Historical
raw actuals remain unchanged; 2026 is retrospective, not unseen. LLM numerical promotion remains
unverified, with no paid calls required when configuration is absent.

Русский: версия нормализатора v2.3 сохраняется дополнительно, не переписывая исходники. Основной
прогноз выбирается по development-периоду; LightGBM не прошёл порог. Межотчётное совпадение Systeme
даёт только оценочный охват. Неизвестное не подменяется нулём или единицей конверсии. Месячные остатки
не доказывают текущий свободный запас, интервалы stockout или потерянный спрос.
