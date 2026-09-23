"""HTTP boundary for employee-attributed order documents (demo identities, not authentication)."""

from contextlib import contextmanager
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from replenishment.ordering import documents

Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateDocument(Request):
    run_id: UUID
    employee_id: UUID


class Approval(Request):
    employee_id: UUID
    expected_revision: Annotated[int, Field(strict=True, ge=1)]


class LineEdit(Request):
    id: UUID
    quantity: Decimal | None = None
    purchase_unit: Unit = None
    included: Annotated[bool, Field(strict=True)] = True
    manual_completion_reason: Annotated[str | None, Field(max_length=10000)] = None


class EditDocument(Approval):
    note: Annotated[str | None, Field(max_length=10000)] = None
    lines: Annotated[list[LineEdit], Field(max_length=10000)] = []


def router(engine, metadata):
    api = APIRouter(prefix="/api/v2")

    @contextmanager
    def transaction():
        try:
            with engine.begin() as connection:
                yield connection
        except documents.DocumentError as error:
            raise HTTPException(error.status, str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(503, "Database unavailable") from error

    def encode(value):
        return jsonable_encoder(value, custom_encoder={Decimal: lambda number: format(number, "f")})

    @api.get("/employees")
    def employees():
        with transaction() as connection:
            return encode(
                [
                    dict(row)
                    for row in connection.execute(
                        select(documents.employees).order_by(
                            documents.employees.c.display_name, documents.employees.c.id
                        )
                    ).mappings()
                ]
            )

    @api.post("/order-documents")
    def create(body: CreateDocument):
        with transaction() as connection:
            return encode(documents.create(connection, metadata, body.run_id, body.employee_id))

    @api.get("/order-documents")
    def listing(
        page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
        run_id: UUID | None = None,
        status: Literal["editable", "approved"] | None = None,
    ):
        with transaction() as connection:
            return encode(
                documents.summaries(connection, page=page, page_size=page_size, run_id=run_id, status=status)
            )

    @api.get("/order-documents/{document_id}")
    def detail(document_id: UUID):
        with transaction() as connection:
            return encode(documents.detail(connection, metadata, document_id))

    @api.patch("/order-documents/{document_id}")
    def edit(document_id: UUID, body: EditDocument):
        with transaction() as connection:
            return encode(
                documents.mutate(
                    connection,
                    metadata,
                    document_id,
                    body.employee_id,
                    body.expected_revision,
                    edits=body.model_dump(exclude_unset=True, exclude={"employee_id", "expected_revision"}),
                )
            )

    @api.post("/order-documents/{document_id}/approve")
    def approve(document_id: UUID, body: Approval):
        with transaction() as connection:
            return encode(
                documents.mutate(
                    connection, metadata, document_id, body.employee_id, body.expected_revision, approve=True
                )
            )

    return api
