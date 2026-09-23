.DEFAULT_GOAL := help

DATABASE_URL ?= postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment
export DATABASE_URL

.PHONY: help install dev-setup db-up db-stop migrate import-data dev-api dev-ui lint build test test-backend test-ui test-postgres test-eval test-eval-strict test-registry evaluate evaluate-strict check

help: ## List available tasks
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install locked backend and frontend dependencies (uv, Node.js 22+)
	cd backend && uv sync --frozen
	cd frontend && npm ci

dev-setup: install ## Start local database, migrate and import workbooks
	$(MAKE) db-up
	$(MAKE) migrate
	$(MAKE) import-data

db-up: ## Start PostgreSQL and wait until healthy (Docker required)
	docker compose up -d --wait db

db-stop: ## Stop PostgreSQL, preserving data
	docker compose stop db

migrate: ## Apply migrations and check schema drift
	cd backend && uv run --frozen alembic upgrade head
	cd backend && uv run --frozen alembic check

import-data: ## Import docs/data (identical imports are skipped)
	cd backend && uv run --frozen python -m replenishment.cli.import_excel ../docs/data

dev-api: ## Run API with reload on 127.0.0.1:8000
	cd backend && uv run --frozen uvicorn replenishment.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000

dev-ui: ## Run Vite on 127.0.0.1:5173 (separate terminal)
	cd frontend && npm run dev

lint: ## Check backend style and module boundaries
	cd backend && uv run --frozen ruff check . ../scripts/evaluate.py ../scripts/check_eval_contract.py
	cd backend && uv run --frozen lint-imports

build: ## Type-check and build frontend
	cd frontend && npm run build

test: test-backend test-ui ## Run backend and frontend tests without PostgreSQL

test-backend: ## Run backend tests without PostgreSQL
	cd backend && uv run --frozen pytest -q -m "not postgres"

test-ui: ## Run frontend tests once
	cd frontend && npm test

test-postgres: ## Run database tests; requires TEST_DATABASE_URL to an empty *_test database
	@test -n "$$TEST_DATABASE_URL" || { echo 'Set TEST_DATABASE_URL to a dedicated empty *_test database (see backend/README.md).'; exit 1; }
	cd backend && uv run --frozen pytest -q -m postgres

test-eval: ## Check evaluation contracts and tests (no database)
	cd backend && uv run --frozen python ../scripts/check_eval_contract.py
	cd backend && uv run --frozen pytest -q tests/evaluation

test-eval-strict: ## Run evaluation acceptance tests, requiring the calculation app
	cd backend && uv run --frozen pytest -q tests/evaluation --require-app

test-registry: ## Check forecast experiment registry rejection rules
	cd backend && uv run --frozen python ../scripts/check_experiment_registry.py

evaluate: ## Write a real-data 2024 readiness report under artifacts/inventory-evaluation
	cd backend && uv run --frozen python ../scripts/evaluate.py --year 2024

evaluate-strict: ## Evaluate 2024, requiring the app and at least one evaluated case
	cd backend && uv run --frozen python ../scripts/evaluate.py --year 2024 --require-app

check: lint test build test-registry ## Run routine checks without PostgreSQL or research dependencies
