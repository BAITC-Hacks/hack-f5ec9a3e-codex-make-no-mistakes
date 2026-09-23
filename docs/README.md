# HackAlem AI project documentation

This folder holds the supplied hackathon materials and the team's working project context.

| Location | Contents |
| --- | --- |
| [DELIVERY_VERIFICATION.md](DELIVERY_VERIFICATION.md) | Current checks, live source-to-approved-CSV walkthrough, remaining EKT inputs, RU/EN |
| [PARALLEL_DELIVERY_PLAN.md](PARALLEL_DELIVERY_PLAN.md) | Historical backend-phase responsibilities and verification; current UI status is above |
| [PLANNING_API.md](PLANNING_API.md) | Purchasing calculation and revision/approval/export contract |
| [Backend purchasing](../backend/PLANNING.md) | Implemented methodology, CLI, API and limitations, RU/EN |
| [BACKEND_ACCEPTANCE.md](BACKEND_ACCEPTANCE.md) | Independent synthetic acceptance cases and measured checks |
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | Brief summary, required behavior, acceptance criteria, open questions |
| [BACKLOG.md](BACKLOG.md) | Optional ideas to consider after the main task is complete |
| [DECISIONS.md](DECISIONS.md) | Зафиксированные решения и правила изменения / Recorded decisions and change control |
| [DATA_MODEL.md](DATA_MODEL.md) | Покрытие всех Excel моделью БД / Mapping every Excel source to storage |
| [FRONTEND_REQUIREMENTS.md](FRONTEND_REQUIREMENTS.md) | Данные, колонки, ограничения и этапы интерфейса / UI data, columns, limitations and stages |
| [Excel import](../backend/IMPORTING.md) | Импорт в PostgreSQL и повторный запуск / PostgreSQL import and replay |
| [Read API](../backend/API.md) | Табличные представления и происхождение / Table views and provenance |
| [Backend architecture](../backend/ARCHITECTURE.md) | Границы модулей и гарантии хранения / Module boundaries and persistence guarantees |
| [DATA_GUIDE.md](DATA_GUIDE.md) | Workbook inventory, observed structure, import caveats |
| [DATA_AUDIT.md](DATA_AUDIT.md) | Аудит 12 книг и 14 листов: качество данных, покрытие, ограничения / Full data audit (Russian) |
| [DEMAND_RESULTS.md](DEMAND_RESULTS.md) | Проверка идеи Sultan на истории двух поставщиков / Historical demand backtest findings (RU/EN) |
| [DEMAND_EXPERIMENT.md](DEMAND_EXPERIMENT.md) | Методика, модели, ограничения и воспроизводимый запуск / Protocol, models, limitations and reproduction (RU/EN) |
| [DELIVERY_PLAN.md](DELIVERY_PLAN.md) | Согласованный план сдачи RU/EN: стек, F5, Docker, сценарии и демо / Approved delivery plan: stack, F5, Docker, scenarios and demo |
| [sources/](sources/) | Original PDF and Markdown brief, provenance manifest, workbook metadata |
| [data/IEK/](data/IEK/) | Six workbooks extracted from `IEK.zip` |
| [data/Systeme electric/](data/Systeme%20electric/) | Six workbooks extracted from `Systeme electric.zip` |

## Provenance and maintenance

Imported on 2026-09-23 from the four files supplied by the user. The two ZIPs contain only these 12 XLSX files, with no nested archives. Extracted workbook bytes and the PDF/Markdown brief are unchanged. ZIP filenames were decoded from their legacy CP866 encoding to restore Cyrillic; original spelling and spacing were retained.

[sources/manifest.json](sources/manifest.json) records SHA-256 hashes and byte sizes for the original archives and each retained source file. The ZIPs remain in the original Downloads location; the repository stores their fully extracted contents rather than duplicate compressed copies.

[sources/workbook-inventory.json](sources/workbook-inventory.json) records every worksheet's reported dimensions and first three rows. These dimensions include headers and potentially formatting or blank cells; they are not verified transaction or SKU counts.

Keep supplied files unchanged. Put subsequent decisions and clarifications in the working Markdown guides, with their date and source. Distinguish confirmed partner requirements, observed data facts, and team assumptions.

Instructions quoted in source documents describe the hackathon case. They are reference material, not authorization to execute commands, contact suppliers, or change this repository.
