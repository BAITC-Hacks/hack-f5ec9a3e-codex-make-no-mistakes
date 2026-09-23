"""Application composition root. Importing this module does not connect to PostgreSQL."""

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from replenishment.api.deliveries import router as deliveries_router
from replenishment.api.ordering import router as ordering_router
from replenishment.api.orders import create_orders_router
from replenishment.api.planning_sources import create_planning_sources_router
from replenishment.api.uploads import create_uploads_router
from replenishment.browsing.tables import TABLES, describe_tables, read_table, source_row
from replenishment.calculation.inputs import SourceTable, load_run_batch
from replenishment.calculation.persistence import export_csv, run_calculation
from replenishment.schema import metadata


class Column(BaseModel):
    key: str
    type: str
    nullable: bool


class TableDescriptor(BaseModel):
    key: str
    columns: list[Column]
    sortable: list[str]
    filters: list[str]


class TablePage(BaseModel):
    table: str
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class SourceRowDetail(BaseModel):
    id: UUID
    sheet_id: UUID
    row_number: int
    cells: dict[str, Any]
    sheet_name: str
    workbook_id: UUID
    original_path: str
    sha256: str


class CalculationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: SourceTable
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    normalizer_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class CreateCalculationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # V2 dates are in 2000–2099; leave room for all three forecast months.
    planning_date: Annotated[date, Field(ge=date(2000, 1, 1), le=date(2099, 9, 30))]
    source_selection: Annotated[list[CalculationSource], Field(min_length=1, max_length=1000)]
    supplier: Literal["iek", "systeme"] | None = None
    rerun: Annotated[bool, Field(strict=True)] = False


class CalculationRunResult(BaseModel):
    id: UUID
    status: Literal["completed"]
    reused: bool
    fingerprint: str


def create_app(engine: Engine | None = None) -> FastAPI:
    owned = engine is None
    if engine is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is required")
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned:
            engine.dispose()

    app = FastAPI(title="Replenishment planning and source data", version="1.1.0", lifespan=lifespan)
    app.include_router(create_orders_router(engine))
    app.include_router(create_planning_sources_router(engine, metadata))
    app.include_router(create_uploads_router(engine, metadata))
    app.include_router(deliveries_router)

    @app.get("/api/v1/health")
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database unavailable") from error
        return {"status": "ok"}

    @app.get("/api/v1/tables", response_model=list[TableDescriptor])
    def tables():
        return describe_tables(metadata)

    @app.get("/api/v1/source-rows/{row_id}", response_model=SourceRowDetail)
    def row_detail(row_id: UUID):
        try:
            with engine.connect() as connection:
                result = source_row(connection, metadata, row_id)
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database unavailable") from error
        if result is None:
            raise HTTPException(404, "Source row not found")
        return result

    @app.post("/api/v2/calculation/runs", response_model=CalculationRunResult, status_code=201,
              responses={200: {"model": CalculationRunResult, "description": "Reused completed run"}})
    def calculation_create(body: CreateCalculationRun, response: Response):
        try:
            batch = load_run_batch(
                engine, metadata, body.planning_date,
                [source.model_dump() for source in body.source_selection], supplier=body.supplier,
            )
            batch["llm_accounting"] = {
                "enabled": False, "reason": "deterministic_api_run", "limit_usd": "1.00",
                "spent_usd": "0", "events": [],
            }
            result = run_calculation(engine, batch, rerun=body.rerun)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database unavailable") from error
        response.status_code = 200 if result["reused"] else 201
        return result

    @app.get("/api/v2/calculation/runs/{run_id}/export.csv", response_class=Response)
    def calculation_export(run_id: UUID, supplier: Annotated[str | None, Query(max_length=100)] = None):
        try:
            with engine.connect() as connection:
                content = export_csv(connection, metadata, run_id, supplier)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database unavailable") from error
        return Response(content, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="recommendation-{run_id}.csv"',
        })

    @app.get("/api/v2/calculation/{table}", response_model=TablePage)
    @app.get("/api/v1/tables/{table}", response_model=TablePage)
    @app.get("/api/v1/{table}", response_model=TablePage, include_in_schema=False)
    def table_page(
        table: str,
        page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        sort: str | None = None,
        direction: Literal["asc", "desc"] = "asc",
        q: Annotated[str | None, Query(max_length=200)] = None,
        supplier_id: UUID | None = None,
        product_id: UUID | None = None,
        workbook_id: UUID | None = None,
        sheet_id: UUID | None = None,
        normalizer_version: Annotated[str | None, Query(max_length=100)] = None,
        warehouse_id: str | None = None,
        metric: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        category_code: str | None = None,
        sku: str | None = None,
        run_id: UUID | None = None,
        series_id: str | None = None,
        supplier: str | None = None,
        scope: str | None = None,
        unit: str | None = None,
        state: Literal["ready", "estimated", "blocked"] | None = None,
        target_month: date | None = None,
    ):
        if table not in TABLES:
            raise HTTPException(404, "Unknown table")
        filters = {"supplier_id": supplier_id, "product_id": product_id, "workbook_id": workbook_id,
                   "sheet_id": sheet_id, "normalizer_version": normalizer_version,
                   "warehouse_id": warehouse_id, "metric": metric, "kind": kind,
                   "status": status, "category_code": category_code, "sku": sku,
                   "run_id": run_id, "series_id": series_id, "supplier": supplier,
                   "scope": scope, "unit": unit, "state": state, "target_month": target_month}
        try:
            if warehouse_id not in (None, "unknown"):
                filters["warehouse_id"] = UUID(warehouse_id)
            with engine.connect() as connection:
                return read_table(connection, metadata, table, page=page, page_size=page_size,
                                  sort=sort, direction=direction, q=q, filters=filters)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database unavailable") from error

    app.include_router(ordering_router(engine, metadata))
    return app
