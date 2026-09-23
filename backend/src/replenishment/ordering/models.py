from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id, Number


class Employee(Base):
    __tablename__ = "ordering_employees"
    id: Mapped[Id]
    display_name: Mapped[str]


class OrderDocument(Base):
    __tablename__ = "ordering_documents"
    __table_args__ = (
        UniqueConstraint("run_id"),
        UniqueConstraint("id", "run_id"),
        CheckConstraint("status IN ('editable', 'approved')", name="status"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint(
            "(status = 'approved' AND approver_id IS NOT NULL AND approved_at IS NOT NULL) OR "
            "(status = 'editable' AND approver_id IS NULL AND approved_at IS NULL)",
            name="approval",
        ),
    )
    id: Mapped[Id]
    run_id: Mapped[UUID] = mapped_column(ForeignKey("calculation_runs.id"))
    status: Mapped[str] = mapped_column(default="editable")
    revision: Mapped[int] = mapped_column(default=1)
    note: Mapped[str | None]
    creator_id: Mapped[UUID] = mapped_column(ForeignKey("ordering_employees.id"))
    last_editor_id: Mapped[UUID] = mapped_column(ForeignKey("ordering_employees.id"))
    approver_id: Mapped[UUID | None] = mapped_column(ForeignKey("ordering_employees.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderDocumentLine(Base):
    __tablename__ = "ordering_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "run_id"], ["ordering_documents.id", "ordering_documents.run_id"]
        ),
        ForeignKeyConstraint(
            ["run_id", "series_id"], ["calculation_drafts.run_id", "calculation_drafts.series_id"]
        ),
        UniqueConstraint("document_id", "series_id"),
        CheckConstraint("quantity >= 0 AND quantity < 1e18 AND quantity <> 'NaN'::numeric", name="quantity"),
        CheckConstraint("purchase_unit IS NULL OR length(trim(purchase_unit)) > 0", name="unit"),
    )
    id: Mapped[Id]
    document_id: Mapped[UUID]
    run_id: Mapped[UUID]
    series_id: Mapped[str]
    quantity: Mapped[Number | None]
    purchase_unit: Mapped[str | None]
    included: Mapped[bool] = mapped_column(default=True)
    manual_completion_reason: Mapped[str | None]
