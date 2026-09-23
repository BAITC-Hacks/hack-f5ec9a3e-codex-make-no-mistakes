# Интерфейс данных / Data viewer

## Русский

React 19 + TypeScript + Vite. Компактная таблица на нативном HTML: без дополнительной библиотеки компонентов.

После установки Node.js 22+ выполните `npm ci`, затем `npm run dev` в `frontend`. API должен работать на `127.0.0.1:8000`; Vite проксирует `/api` на него. Проверка: `npm test` и `npm run build`.

Интерфейс читает таблицы PostgreSQL через API. Поиск, сортировка и пагинация выполняются сервером. Наблюдения разных книг и версий не объединяются; их можно отфильтровать. Подробности строки показывают источник, хеш, версию и исходные ячейки, включая формулы и ошибки Excel. NULL, ноль и пустая строка отображаются раздельно. Это просмотр данных: расчёт заказов, редактирование, сценарии и экспорт ещё не реализованы.

## English

React 19 + TypeScript + Vite with a compact semantic HTML table, without a component framework.

With Node.js 22+ installed, run `npm ci` and `npm run dev` inside `frontend`. Start the API on `127.0.0.1:8000`; Vite proxies `/api` to it. Validate with `npm test` and `npm run build`.

Search, sorting and pagination run on the server. Workbook/version observations stay separate. The evidence drawer exposes provenance, hashes, normalization versions and raw cells including formulas and Excel errors. NULL, zero and empty string remain distinct. Ordering calculations, editing, scenarios and export are outside this read-only viewer.
