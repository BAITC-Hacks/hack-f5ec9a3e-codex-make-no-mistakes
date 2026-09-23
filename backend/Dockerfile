FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync python -m replenishment.cli.import_excel /app/docs/data && exec uv run --no-sync uvicorn replenishment.api.app:create_app --factory --host 0.0.0.0 --port 8000"]
