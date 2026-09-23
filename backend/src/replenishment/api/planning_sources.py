"""HTTP validation for read-only, explicitly selected planning source snapshots."""

from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError

from replenishment.planning_sources import prepare_source_input


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]
    planning_date: date
    warehouse: Annotated[str, Field(min_length=1, max_length=200)]
    normalizer_version: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    workbook_ids: Annotated[list[UUID], Field(max_length=50)] = []
    history_start: date | None = None
    history_end: date | None = None

    @model_validator(mode="after")
    def history_window(self):
        if (self.history_start is None) != (self.history_end is None):
            raise ValueError("Supply both history_start and history_end")
        if self.history_start is not None:
            if not self.history_start <= self.history_end < self.planning_date:
                raise ValueError("History must be ordered and strictly before planning_date")
            if (self.history_end - self.history_start).days > 3659:
                raise ValueError("History window must contain at most 3660 days")
        return self

    @field_validator("product_ids", "workbook_ids")
    @classmethod
    def unique_ids(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Identifiers must be unique")
        return values

    @field_validator("warehouse")
    @classmethod
    def nonblank_warehouse(cls, value):
        if not value.strip():
            raise ValueError("Warehouse must not be blank")
        return value.strip()

    @field_validator("planning_date")
    @classmethod
    def history_fits(cls, value):
        if value < date.min + timedelta(days=56):
            raise ValueError("Planning date must allow 56 preceding history days")
        return value


def create_planning_sources_router(engine, metadata):
    router = APIRouter(prefix="/api/v1/planning", tags=["planning sources"])

    @router.post("/source-input")
    def source_input(request: SourceSelection):
        try:
            with engine.connect() as connection:
                # A transaction-wide snapshot avoids mixing concurrent import versions.
                connection = connection.execution_options(isolation_level="REPEATABLE READ")
                return prepare_source_input(connection, metadata, request)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database unavailable") from error

    return router
