# Запуск / Startup

## Docker: всё приложение / Entire application

Install and start Docker Desktop, then from the repository root:

```powershell
docker compose up --build -d --wait --wait-timeout 600
```

Open http://127.0.0.1:8080. Backend migration and idempotent import of all bundled
Excel workbooks run before the API becomes healthy. The first build/import takes
several minutes. The synthetic examples are available inside the main application;
they are calculated by the backend and are not inserted as approved orders.

```powershell
docker compose ps
docker compose logs --tail 50 backend
docker compose stop
docker compose start
```

The named `pgdata` volume preserves imports and scenarios. Do not use `down -v` if you
want to retain them. Source workbooks are mounted read-only. Only the frontend at
localhost:8080 and the development database at localhost:55432 are published;
the API is reached through the frontend `/api` proxy. These are local-demo credentials
and settings, not a production deployment.

Из корня выполните команду выше и откройте http://127.0.0.1:8080. Первый запуск
применяет миграции и импортирует исходные книги; повторный импорт одинаковых файлов
пропускается. `stop`/`start` сохраняют данные. Исходники Excel подключены только для
чтения. Для синтетического примера нажмите «Синтетический пример» в основном экране.

For an independent verification installation alongside an existing instance:

```powershell
$env:DB_PORT = '55433'
$env:WEB_PORT = '8081'
docker compose -p ektverify up --build -d --wait --wait-timeout 600
```

This project uses its own named volume and http://127.0.0.1:8081. These environment
variables apply only to that shell; omit them for the default ports.

## F5 / Local development

Install uv, Node.js/npm, Docker Desktop and VS Code's Microsoft Python and Python
Debugger extensions. Open the repository root in VS Code. First-time preparation:

```powershell
docker compose up -d --wait db
cd backend
uv sync --frozen
$env:DATABASE_URL = 'postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment'
uv run alembic upgrade head
uv run python -m replenishment.cli.import_excel ../docs/data
cd ../frontend
npm ci
```

Select the interpreter in `backend/.venv` if VS Code has an older workspace selection.
Choose **EKT: full development (F5)** in Run and Debug, then press F5. The API runs
on 127.0.0.1:8000 and Vite on 127.0.0.1:5173; both support reloading. Stop any earlier
manually started API/Vite processes on those ports before F5. The frontend task uses
`--strictPort` so a collision fails visibly instead of silently opening another port.
Stop debugging to stop the debugger sessions; terminate the background frontend task
using VS Code's **Tasks: Terminate Task** when finished. Database data stays in Docker.

В VS Code выберите конфигурацию **EKT: full development (F5)**. Предварительно
выполните подготовку выше и выберите Python из `backend/.venv`. Освободите порты
8000/5173 от предыдущих ручных запусков. Остановка отладки не удаляет БД;
фоновую задачу frontend завершите через **Tasks: Terminate Task**.

The checked-in F5 configuration has been structurally inspected; launching it inside
VS Code is a separate manual acceptance step, not established by the CLI/build checks.

## Demo / Показ

Follow [the verified source-based walkthrough](DELIVERY_VERIFICATION.md). Also use the
synthetic baseline and increased-transit cases: recommendations are respectively
100 and 70 units. Unknown inputs remain blocked. Overrides require reasons, approval
applies to a specific saved revision, and CSV exports its approved quantities.
