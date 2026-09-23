# README, демо и сдача / README, demo and submission

## Русский

Согласовано с пользователем 23.09.2026 после обсуждения задачи [№8](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/8). Это требования к будущей реализации, а не отчёт о готовых функциях.

### Результат и границы

Основное доказательство пользы — объяснимый расчёт на предоставленных данных: откуда взялось рекомендуемое количество и почему оно меняется при изменении спроса, остатков или транзита. Нужен полностью рабочий путь: данные → расчёт → проверка и корректировка менеджером → утверждение → экспорт.

Учитываем все предоставленные источники обоих поставщиков. Склад, товары и примеры для живого показа выбираем по результатам аудита; выбор примеров не отменяет обязательные требования брифа. Неизвестные входы, допущения и синтетические примеры обозначаем явно. Не выдаём месячные остатки за точные интервалы отсутствия товара или номер документа за ID клиента.

Демонстрация проходит на русском. README, инструкции, описание методики, ограничения и остальные материалы сдачи — на русском и английском. Видеозапись не требуется. Сдаём репозиторий и воспроизводимый локальный запуск; публикация сервиса сейчас не входит в задачу.

### Настройки и сценарии

- Общие параметры расчёта и изменения отдельных SKU, включая остаток, транзит, рост и срок поставки.
- Пересчёт результата после изменения входов с объяснением влияния изменений.
- Сохранение и загрузка сценариев с параметрами и изменениями SKU, в том числе после перезапуска.
- Возможность вернуться к исходным данным; исходные файлы сохраняются неизменными.
- Исходный сценарий и подготовленные варианты для демонстрации требований брифа.
- Проверка и редактирование количества менеджером, явное утверждение и экспорт утверждённых значений. Отправка поставщику без подтверждения запрещена.

### Стек и запуск

Основной стек выбран по [TenderVision](https://github.com/dimashisenov/tendervision-product/blob/main/README.md): Python 3.12, FastAPI, SQLAlchemy 2, Alembic, uv; PostgreSQL 17; React 19, TypeScript и Vite. Проверки: pytest и Ruff для Python; Vitest, TypeScript и oxlint для frontend. Это выбор технологий, а не требование копировать предметную архитектуру TenderVision.

Два обязательных режима:

1. **Разработка:** F5 в VS Code запускает Python API и React с отладкой и автоматической перезагрузкой; PostgreSQL запускается через Docker. Необходимые начальные установки и подготовка описаны в README.
2. **Полный Docker:** `docker compose up --build` запускает frontend, backend и PostgreSQL с демонстрационными данными. Данные и сценарии сохраняются между обычными перезапусками. Комплект должен допускать последующий хостинг, но развёртывание сейчас не требуется.

Эти режимы ещё предстоит реализовать и проверить с чистого клона. В TenderVision Compose запускает только базу, поэтому единый запуск всего приложения необходимо добавить здесь.

### Содержание README и демонстрации

- Предварительные зависимости, точные шаги первого запуска, F5 и Docker, адрес приложения, остановка и повторный запуск, типичные ошибки.
- Источники данных, правила импорта, единицы, методика расчёта, исключение разовых крупных заказов, ограничения и допущения.
- Демонстрация сезонности и устойчивого роста; компенсации потерянного спроса; устойчивости к разовому крупному заказу; влияния транзита и остатков; группировки и объяснений по поставщикам.
- Изменение общих параметров и отдельного SKU, сохранение/загрузка сценария, корректировка менеджером и экспорт.
- Воспроизводимые приёмочные проверки с ожидаемыми результатами. Недоступные в реальных данных случаи показываем на явно помеченных синтетических входах.

Задача №8 завершена, когда новый участник по документации воспроизводит оба режима запуска и живой сценарий, а результаты проверок соответствуют реальной реализации. Для сдачи зависит от [№7](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/7); сценарии требуют функций [№5](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/5) и [№6](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/6).

## English

Approved by the user on 2026-09-23 following the discussion of [issue #8](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/8). These are requirements for future implementation, not a claim that the features already exist.

### Outcome and scope

The main evidence of value is an explainable calculation on supplied data: where the recommended quantity comes from and why it changes with demand, stock or incoming shipments. Deliver a working flow: data → calculation → manager review and adjustment → approval → export.

Account for all supplied sources for both suppliers. Select warehouses, products and live examples based on the data audit; selecting examples does not reduce the mandatory brief requirements. Identify unknown inputs, assumptions and synthetic examples explicitly. Do not treat monthly stock snapshots as exact stockout intervals or document numbers as customer IDs.

The live demonstration is in Russian. The README, instructions, methodology, limitations and other submission materials are bilingual Russian/English. No video recording is required. Deliver the repository and reproducible local startup; hosting the service is outside the current scope.

### Configuration and scenarios

- Global calculation parameters and per-SKU overrides, including stock, transit, growth and lead time.
- Recalculate after input changes and explain their effect.
- Save and load scenarios containing parameters and SKU overrides, including after restart.
- Restore the original data; preserve source files unchanged.
- A baseline scenario and prepared variants demonstrating the brief requirements.
- Manager review and quantity editing, explicit approval and export of approved values. Sending orders without confirmation is prohibited.

### Stack and startup

Use the core stack from [TenderVision](https://github.com/dimashisenov/tendervision-product/blob/main/README.md): Python 3.12, FastAPI, SQLAlchemy 2, Alembic and uv; PostgreSQL 17; React 19, TypeScript and Vite. Checks: pytest and Ruff for Python; Vitest, TypeScript and oxlint for the frontend. This selects technologies rather than requiring a copy of TenderVision's domain architecture.

Two required modes:

1. **Development:** F5 in VS Code starts the Python API and React with debugging and automatic reload; PostgreSQL starts through Docker. Document initial prerequisites and preparation in the README.
2. **Full Docker:** `docker compose up --build` starts the frontend, backend and PostgreSQL with demonstration data. Data and scenarios survive normal restarts. Keep the package suitable for future hosting; deployment is not currently required.

Both modes still need implementation and verification from a clean clone. TenderVision's Compose file starts only the database, so whole-application startup must be added here.

### README and demonstration contents

- Prerequisites, exact first-run steps, F5 and Docker, application address, shutdown/restart and troubleshooting.
- Data sources, import rules, units, calculation methodology, bulk-order exclusion, limitations and assumptions.
- Demonstrate seasonality and sustained growth, lost-demand compensation, robustness to one-off bulk orders, stock/transit effects, supplier grouping and explanations.
- Change global parameters and one SKU; save/load a scenario; adjust as manager and export.
- Reproducible acceptance checks with expected results. Use explicitly labeled synthetic inputs for cases unavailable in real data.

Issue #8 is complete when a new teammate can reproduce both startup modes and the live scenario from the documentation, and reported checks match the implementation. Submission depends on [#7](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/7); the scenarios require functionality from [#5](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/5) and [#6](https://github.com/BAITC-Hacks/hack-f5ec9a3e-codex-make-no-mistakes/issues/6).
