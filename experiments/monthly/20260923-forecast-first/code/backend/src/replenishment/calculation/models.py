"""Run-owned snapshots and typed results; calculation arithmetic never imports ORM."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from replenishment.kernel.db import Base, Id, Number


class CalculationRun(Base):
    __tablename__ = "calculation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status"),
        CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name="fingerprint"),
    )
    id: Mapped[Id]
    fingerprint: Mapped[str] = mapped_column(index=True)
    contract_version: Mapped[str]
    planning_date: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str]
    source_selection: Mapped[list] = mapped_column(JSONB)
    parameters: Mapped[dict] = mapped_column(JSONB)
    versions: Mapped[dict] = mapped_column(JSONB)
    quality: Mapped[dict] = mapped_column(JSONB)
    llm_accounting: Mapped[dict] = mapped_column(JSONB)
    failure: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CalculationInput(Base):
    __tablename__ = "calculation_inputs"
    __table_args__ = (UniqueConstraint("run_id", "series_id"),)
    id: Mapped[Id]
    run_id: Mapped[UUID] = mapped_column(ForeignKey("calculation_runs.id"), index=True)
    series_id: Mapped[str]
    supplier: Mapped[str]
    sku: Mapped[str]
    scope: Mapped[str]
    unit: Mapped[str | None]
    snapshot: Mapped[dict] = mapped_column(JSONB)


class ForecastValue(Base):
    __tablename__ = "calculation_forecasts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "series_id"], ["calculation_inputs.run_id", "calculation_inputs.series_id"]
        ),
        UniqueConstraint("run_id", "series_id", "target_month"),
        CheckConstraint("extract(day from target_month) = 1", name="month_start"),
        CheckConstraint("quantity >= 0 AND quantity <> 'NaN'::numeric", name="nonnegative"),
        CheckConstraint("status IN ('ok', 'insufficient_data', 'unsupported')", name="status"),
        CheckConstraint("(status = 'ok') = (quantity IS NOT NULL)", name="quantity_status"),
    )
    id: Mapped[Id]
    run_id: Mapped[UUID] = mapped_column(index=True)
    series_id: Mapped[str]
    target_month: Mapped[date]
    quantity: Mapped[Number | None]
    model: Mapped[str]
    status: Mapped[str]
    explanation: Mapped[dict] = mapped_column(JSONB)


class OrderDraftLine(Base):
    __tablename__ = "calculation_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "series_id"], ["calculation_inputs.run_id", "calculation_inputs.series_id"]
        ),
        UniqueConstraint("run_id", "series_id"),
        CheckConstraint("state IN ('ready', 'estimated', 'blocked')", name="state"),
        CheckConstraint("quantity >= 0 AND quantity <> 'NaN'::numeric", name="nonnegative"),
        CheckConstraint("(state = 'blocked') = (quantity IS NULL)", name="quantity_state"),
        CheckConstraint("coverage_end >= coverage_start", name="coverage"),
    )
    id: Mapped[Id]
    run_id: Mapped[UUID] = mapped_column(index=True)
    series_id: Mapped[str]
    quantity: Mapped[Number | None]
    purchase_unit: Mapped[str | None]
    coverage_start: Mapped[date]
    coverage_end: Mapped[date]
    urgency: Mapped[str]
    state: Mapped[str]
    blocking_reason: Mapped[str | None]
    components: Mapped[dict] = mapped_column(JSONB)
    evidence: Mapped[list] = mapped_column(JSONB)
    assumptions: Mapped[list] = mapped_column(JSONB)
