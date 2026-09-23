# hack-f5ec9a3e-codex-make-no-mistakes
Hackathon team repository for Codex, make no mistakes

HackAlem AI case: supplier order recommendations for Elektrokomplekt LLP (ekt.kz).

Start with the [project documentation](docs/README.md), then read the
[project context](docs/PROJECT_CONTEXT.md) and [data guide](docs/DATA_GUIDE.md).
The original brief and all 12 extracted supplier workbooks are included in `docs/`.

Current state: source documentation, locked audit checks, modular SQLAlchemy models, PostgreSQL migration,
Excel ingestion, read API and React tables are implemented. Order calculation remains subsequent work.
See [backend setup RU/EN](backend/README.md), [architecture](backend/ARCHITECTURE.md)
and [Excel-to-database mapping](docs/DATA_MODEL.md).

Текущее состояние: документация, проверки аудита, модульные модели SQLAlchemy, миграция PostgreSQL,
импорт Excel, API чтения и React-таблицы. Расчёт заказов — следующий этап.

Запуск / Run: [backend + import](backend/README.md), [frontend](frontend/README.md).
API: [contract RU/EN](backend/API.md). UI scope: [requirements RU/EN](docs/FRONTEND_REQUIREMENTS.md).

Согласованные требования к стеку, запуску через F5 и Docker, сценариям и демонстрации:
[план сдачи RU/EN](docs/DELIVERY_PLAN.md). Режимы запуска ещё предстоит реализовать.

Approved stack, F5/Docker startup, scenarios and demonstration requirements:
[delivery plan RU/EN](docs/DELIVERY_PLAN.md). Startup modes are not implemented yet.
