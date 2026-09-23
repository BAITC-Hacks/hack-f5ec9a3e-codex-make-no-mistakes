# Интерфейс данных и закупок / Data and purchasing interface

## Русский

Рабочая спецификация к [задаче №6](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/6), 23.09.2026. Текущий этап — просмотр импортированных данных через FastAPI. Рекомендации и сценарии из [плана сдачи](DELIVERY_PLAN.md) остаются следующим этапом, зависящим от расчёта.

### Какие данные доступны

| Представление | Полезные колонки | Важные ограничения |
| --- | --- | --- |
| Номенклатура из источников | Поставщик, код 1С, артикул, название, единица, категория, источник | Это наблюдения: один SKU может встречаться в разных книгах и строках. Количество строк не равно количеству уникальных товаров. |
| Движения | Дата, SKU, документ/номер, количество, единица, склад, источник | 248 915 движений; склад в этих выгрузках — Алматы. Отрицательные движения сохраняются. Клиентских ID и цены сделки нет. |
| Месячные продажи | SKU, месяц, количество, единица, источник | Январь 2024 — сентябрь 2026; неизвестный склад, неполный сентябрь. Месячные отчёты расходятся с движениями. |
| Месячные остатки | SKU, месяц, вид остатка, количество, источник | IEK — начальный остаток; момент снимка Systeme не подтверждён. Не показывать как текущий остаток. |
| Текущие остатки | SKU, компонент запаса, количество, подпись области, дата и основание даты | Systeme: 497 SKU с остатком, резервом, свободным остатком и другими компонентами; текущего снимка IEK нет. Компоненты не суммируются автоматически. |
| Условия количества | SKU, исходная подпись, минимум/кратность, значение, подтверждение смысла | 15 ошибок MOQ IEK; ноль в одном источнике может конфликтовать с единицей в другом. |
| Поставки в пути | Поставщик, документ/шапка, ожидаемая дата, основание даты, SKU, количество | IEK — шесть заказов; Systeme — колонка «24.09» без года. Не угадывать год или склад. |
| Показатели отчёта | SKU, название показателя, значение, период, источник | Рост/сезонность, суммы/средние, «СС реал», «Запас» — исходные показатели, не результат нашего алгоритма. |
| Сезонность | Поставщик, год/месяц, показатель, значение, основание, источник | Агрегаты поставщика; повторяющиеся листы не являются независимыми наблюдениями. |
| Качество данных | Код проблемы, описание, статус, источник и доказательство | Ошибки и допущения доступны рядом с данными, не скрываются нулевыми значениями. |
| Файлы и листы | Имя, SHA-256, размер, версия захвата, лист, размеры | Список версий и происхождение. Бинарные оригиналы не загружаются в браузер вместе с таблицей. |

Фактические числа импорта API берёт из PostgreSQL; frontend не содержит жёстко заданных счётчиков из этой спецификации.

### Текущий экран

- Русский интерфейс: выбор представления, поставщика и файла, поиск, сортировка, размер страницы и переход между страницами.
- Серверная фильтрация/сортировка/пагинация; не загружать сотни тысяч строк для клиентского фильтра. Смена фильтра возвращает на первую страницу.
- Сортировка с устойчивым вторичным ключом; строковые SKU сохраняют ведущие нули и `_`.
- Видимые по умолчанию столбцы — предметные. UUID, SHA и версии доступны в деталях; они не должны вытеснять названия и количества.
- Явно различать «Нет данных», числовой ноль и ошибку Excel. Decimal приходит строкой: не терять точность через безусловный `Number()`.
- Детали источника по строке: файл → лист → строка/ячейка; исходное значение, формула и кешированный результат, если имеются. Показать неопределённый склад и основание даты.
- Состояния: загрузка, пустая БД, пустая выборка, ошибка API, повтор запроса. При смене фильтра устаревший ответ не должен подменять новую выборку.
- Доступность: подписи фильтров, клавиатурная сортировка с `aria-sort`, фокус и закрытие панели источника, горизонтальная прокрутка на узком экране.

Визуальный ориентир — [таблица Sultan OS](https://github.com/dimashisenov/sultan-os/blob/main/director_dashboard/frontend/src/components/ui/table.tsx): компактная семантическая таблица, сдержанный фон заголовка, ровные числовые колонки, подсветка строки и прокрутка. Логику чужих закупок не переносим. Установка shadcn не обязательна; выбор конкретного компонента оставлен frontend-субагенту.

### Контракт с backend

`GET /api/v1/tables` описывает доступные таблицы, колонки, типы, nullable, разрешённые фильтры и сортировки. `GET /api/v1/tables/{table}` возвращает `{table, items, total, page, page_size}`. Фильтры включают поиск, поставщика, товар, файл и версию нормализатора там, где применимы; точные поля определяются контрактом API, не догадками frontend.

`GET /api/v1/source-rows/{id}` возвращает адресуемое сырьё и происхождение без бинарного файла. Общие типы находятся в `frontend/src/api/types.ts`, пример — в `contracts/`, описание — в `backend/API.md`.

Версии и источники сохраняются явно. Нельзя выбирать «последнюю истину» или объединять конфликтующие источники по названию товара. Выбор источника для расчёта — отдельная бизнес-функция.

### Следующий этап закупок

После задач №3–5: выбор склада/категории, запуск расчёта, рекомендации по поставщикам, объяснение и срочность каждой строки. Общие настройки и изменения SKU, сохранение/загрузка сценария, сброс к исходным данным; корректировка количества, подтверждение менеджером и экспорт. До появления backend-реализации интерфейс не показывает фиктивные рекомендации, работающие кнопки утверждения или сохранения сценария.

Критерии текущего этапа: на реально импортированных файлах можно найти SKU, открыть движения/остатки/поставки, изменить фильтр и сортировку, перейти по страницам и проверить источник значения. Пустоты/ошибки/неизвестный склад не становятся нулями или «Алматы». Это не закрывает весь объём задачи №6.

## English

Working specification for issue #6. The current slice is a read-only browser of imported PostgreSQL data through FastAPI. Recommendations and configurable persisted scenarios remain later work dependent on the calculation engine.

Available views: source product observations; 248,915 signed sales movements; monthly sales and stock; Systeme's current stock components for 497 SKUs; MOQ/multiple observations; incoming shipments; report metrics; supplier-level seasonality; quality findings; workbook/sheet provenance. Names, articles, units and categories come from observations, not a silently merged master record. Repeated SKU observations are not unique-product counts. The UI obtains actual counts from PostgreSQL rather than hardcoding audit numbers.

Show domain columns first: supplier, SKU, article/name, dates, quantities/units, stock component or metric, source. Keep technical identifiers and hashes in details. Unknown warehouses remain unknown; monthly snapshots are not current stock. Negative quantities, blanks, zero and Excel errors stay distinct. Preserve decimal-string precision. Missing customer IDs, transaction prices, exact stockout intervals, lead times and BOM must not be invented.

The Russian-language screen provides view/supplier/workbook selection, search, server-side sorting and pagination, with stable row ordering and filter changes resetting the page. Do not download the full movement dataset. Ignore stale requests when filters change. Provide loading, empty database, no matches, error and retry states. Use labeled controls, keyboard-accessible sorting, `aria-sort`, accessible evidence details and horizontal overflow on small screens.

Evidence details show file, sheet, row/cell, original value, formula and cached result when present, plus date/scope uncertainty. Workbook binary content is excluded from list responses. Visual reference: Sultan OS's compact semantic table, muted header, aligned numbers and restrained row hover; do not copy its business logic. Component choice belongs to the frontend implementer; shadcn installation is optional.

API: `GET /api/v1/tables` supplies table/column/filter/sort descriptors; `GET /api/v1/tables/{table}` returns `{table, items, total, page, page_size}`; `GET /api/v1/source-rows/{id}` returns raw cell evidence. Use actual documented filter applicability and shared TypeScript contracts. See `backend/API.md`, `contracts/` and `frontend/src/api/types.ts`.

Later purchasing scope: warehouse/category selection, calculation, supplier-grouped recommendations, explanations/urgency, global and SKU overrides, scenario persistence/reset, manager edits/approval and export. Do not present unimplemented calculations or approval/scenario actions as working features.

Acceptance for this slice: browse the real import, find a SKU, inspect movements/stock/shipments, filter/sort/page and trace a value to its Excel source without hiding uncertainty. This does not complete the whole purchasing UI issue.
