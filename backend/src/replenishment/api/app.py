"""Application composition root. Importing this module does not connect to PostgreSQL."""

import os
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from replenishment.api.orders import create_orders_router
from replenishment.api.planning_sources import create_planning_sources_router
from replenishment.browsing.tables import TABLES, describe_tables, read_table, source_row
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
    ):
        if table not in TABLES:
            raise HTTPException(404, "Unknown table")
        filters = {"supplier_id": supplier_id, "product_id": product_id, "workbook_id": workbook_id,
                   "sheet_id": sheet_id, "normalizer_version": normalizer_version,
                   "warehouse_id": warehouse_id, "metric": metric, "kind": kind,
                   "status": status, "category_code": category_code, "sku": sku}
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

    return app
