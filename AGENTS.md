# Repository Guidelines

## Project Structure & Module Organization

The application backend lives in `backend/src/replenishment/`. It is a modular monolith: `kernel` owns persistence primitives; `intake`, `catalog`, `demand`, `inventory`, and `supply` own separate data domains. Keep domain packages independent and assemble metadata in `schema.py`. Alembic migrations are under `backend/migrations/`, with tests in `backend/tests/`.

Forecast research scripts live in `scripts/`; immutable registered outputs and comparison tables live in `experiments/`. Source workbooks, audit records, and design documents are under `docs/`. Read `backend/ARCHITECTURE.md` and `docs/DATA_MODEL.md` before changing storage behavior.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

- `uv sync --frozen` installs the locked Python 3.12 environment.
- `uv run ruff check .` checks formatting-independent style, imports, and common bugs.
- `uv run lint-imports` enforces module boundaries.
- `uv run pytest -q -m "not postgres"` runs checks that need no database.
- `uv run pytest -q` runs everything when `TEST_DATABASE_URL` targets an empty `_test` database.
- `uv run alembic upgrade head && uv run alembic check` applies migrations and detects schema drift.

From the repository root, `docker compose up -d --wait db` starts PostgreSQL on `127.0.0.1:55432`. Experiments use their separately pinned Python 3.10 environment; follow `experiments/README.md` rather than installing research dependencies into the backend.

## Coding Style & Naming Conventions

Use four-space indentation, type-aware Python 3.12 code, and Ruff's 110-character line limit. Name modules and functions `snake_case`, classes `PascalCase`, and tests `test_<behavior>`. Domain models may import `kernel`, but not sibling domain packages. Keep imports side-effect free: importing a package must not read files, environment, network, or database state.

## Testing Guidelines

Use pytest and add the smallest regression test covering changed behavior. Mark database tests with `@pytest.mark.postgres`. Never point tests at a working database; integration tests require an empty database whose name ends in `_test`. Schema changes need a new migration and should pass upgrade, downgrade, recreation, and `alembic check`.

## Commit & Pull Request Guidelines

History favors concise imperative subjects, often Conventional Commit prefixes such as `feat:` or `docs:`. Keep commits focused. Pull requests should explain intent, affected modules, verification commands, migration or data implications, and linked issues. Include screenshots only for visible UI changes. Do not commit secrets, generated virtual environments, or ignored large prediction archives.
