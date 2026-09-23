# hack-f5ec9a3e-codex-make-no-mistakes
Hackathon team repository for Codex, make no mistakes

HackAlem AI case: supplier order recommendations for Elektrokomplekt LLP (ekt.kz).

Start with the [project documentation](docs/README.md), then read the
[project context](docs/PROJECT_CONTEXT.md) and [data guide](docs/DATA_GUIDE.md).
The original brief and all 12 extracted supplier workbooks are included in `docs/`.

Current state: source documentation, audit checks, Excel ingestion, read API and React source tables,
plus backend purchasing calculations, saved scenario revisions, approval and CSV export are implemented.
The new Elektrokomplekt purchasing workspace connects imported products, calculation, saved revisions, approval and CSV export to the backend. Explicitly labelled synthetic examples remain available.
Calculable v0 recommendations are explicitly labelled scenarios. See the
[current verification and demo walkthrough](docs/DELIVERY_VERIFICATION.md).
Start with [purchasing backend RU/EN](backend/PLANNING.md) and the [parallel execution plan](docs/PARALLEL_DELIVERY_PLAN.md).
See [backend setup RU/EN](backend/README.md), [architecture](backend/ARCHITECTURE.md)
and [Excel-to-database mapping](docs/DATA_MODEL.md).

Текущее состояние: импорт Excel, API чтения и React-таблицы, backend расчёта закупок, сохранение версий,
утверждение и CSV. Новое рабочее место Электрокомплект подключено к backend: импортированные товары, расчёт, версии сценариев, утверждение и CSV. Учебные примеры явно обозначены.
Актуальная проверка и сценарий показа: [RU/EN](docs/DELIVERY_VERIFICATION.md).

Запуск / Run: [backend + import](backend/README.md), [frontend](frontend/README.md).
API: [contract RU/EN](backend/API.md). UI scope: [requirements RU/EN](docs/FRONTEND_REQUIREMENTS.md).

Проверка импорта / Import validation: [independent data-quality report](docs/reports/data-quality.md)
and [reproduction command](backend/IMPORTING.md#независимая-сверка--independent-reconciliation).

Согласованные требования к стеку, запуску через F5 и Docker, сценариям и демонстрации:
[план сдачи RU/EN](docs/DELIVERY_PLAN.md). Инструкции запуска: [Docker и F5](docs/STARTUP.md).

Approved stack, F5/Docker startup, scenarios and demonstration requirements:
[delivery plan RU/EN](docs/DELIVERY_PLAN.md). See [Docker and F5 startup](docs/STARTUP.md); Docker was verified, F5 configuration has not been launched in VS Code.
