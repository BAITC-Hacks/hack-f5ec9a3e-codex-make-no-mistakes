# Purchasing worktree / Рабочая ветка закупок

2026-09-23. Branch: `codex/purchasing-business-flow`.
Local checkout: `C:/Users/User/Desktop/hackathon-purchasing`.

The user selected the main checkout's existing planning/approval backend. This branch snapshots that
implementation, not the alternative calculator/UI in `hackathon-replenishment`. Both original worktrees
were left unchanged. `PURCHASING_HANDOFF.json` records source hashes; later edits are recorded by Git.
The unrelated OR-Tools dependency and delivery-router registration were excluded.

## Implemented scope and limits

Purchasing arithmetic, early shortages, conversions, minima/multiples, bulk processing, stockout adjustment,
source preparation, saved scenario revisions, manager overrides, approval and CSV export are included.
The existing source browser remains; the manager interface is not connected in this branch.
All calculable results are `scenario_only`. Forecasts use a simple history mean or explicit daily assumption,
not automatic selection of a research model. Seasonality/growth are explicit factors. Missing real customer,
stockout, lead-time, conversion and BOM data still limit real recommendations. Approval names are local-demo
attribution, not authenticated identities. No supplier orders are sent.

## Run without a database

From this checkout's `backend/`:

```powershell
uv sync --frozen
uv run python -m replenishment.cli.planning_demo --json
uv run pytest -q -m "not postgres"
uv run ruff check .
uv run lint-imports
```

Seven synthetic examples demonstrate behavior. Baseline orders 100, increased transit orders 70,
and early-shortage orders zero while reporting a pre-arrival shortfall of 30. Unknown rows remain visible.

## Separate development database/API

Do not migrate the shared application database just to try this branch. Example local-only instance:

```powershell
docker run --detach --name hackathon-purchasing-dev -e POSTGRES_USER=replenishment -e POSTGRES_PASSWORD=local_dev_only -e POSTGRES_DB=replenishment_purchasing -p 127.0.0.1:55440:5432 postgres:17
# Wait for accepting connections:
docker exec hackathon-purchasing-dev pg_isready -U replenishment
# From backend/:
$env:DATABASE_URL = 'postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55440/replenishment_purchasing'
uv run alembic upgrade head
uv run uvicorn replenishment.api.app:create_app --factory --host 127.0.0.1 --port 8002
```

Open `http://127.0.0.1:8002/docs`. This developer instance was not started during handoff.
Synthetic scenarios need no import; source preparation needs data imported into this separate database.
Stop/start using `docker stop/start hackathon-purchasing-dev`. Removing the container discards its unmounted
database. The branch-specific commands here supersede the shared database/port examples in PLANNING.md.

## Verification performed here

- Non-PostgreSQL suite: 94 passed, 3 skipped, 20 deselected, initially one failed source-hash check.
  Git had converted the original Markdown brief to CRLF. Added `.gitattributes`, restored exact tracked bytes
  after verifying the existing SHA-256, and reran the failed check: passed. No baseline hashes changed.
- Ruff passed; all three import-boundary contracts passed.
- All 16 selected PostgreSQL/API checks passed on a new disposable PostgreSQL 17 container, port 55439,
  using separate empty orders/source/API test databases. This covers migration upgrade/check/downgrade/
  recreation, restart persistence, concurrent/stale updates, approval invalidation and CSV output.
- The disposable container was stopped/removed. The existing database on port 55432 was untouched.
- Existing FastAPI test-client dependency emits a deprecation warning; tests pass with the pinned lockfile.

These are synthetic mechanism checks, not proof of inventory savings. Next: review representative
source preparation and buyer definitions, then connect the manager interface to the existing workflow.

## Русский

В отдельную ветку перенесён backend закупок из основной папки. Две исходные рабочие папки не изменялись.
Расчёт, версии, утверждение и CSV проверены; UI менеджера ещё не подключён. Все результаты остаются
сценариями. База для проверок была отдельной и удалена после завершения; основная БД не затронута.
Для этой ветки используются отдельные БД и порт API. Следующий шаг — проверка реальных источников
с явными бизнес-допущениями, затем подключение интерфейса к готовому процессу версий и утверждения.
